"""确定性参考只验证执行合同，不作为真实模型研究成绩。"""

import json
from types import SimpleNamespace

import pytest

from warden.infrastructure.adapters.stego_diagnostics import channel_roundtrip
from warden.infrastructure.adapters.stego_readout import (
    failed_readout_outcome,
    generation_text,
    parse_bit,
    parse_packet,
    parse_word,
    readout_facts,
)
from warden.infrastructure.adapters.stego_training_cache import (
    atomic_training_cache,
    cache_identity,
    training_inputs,
    verify_cache,
)


@pytest.mark.parametrize(
    "raw", ["The answer is 1", "0 or 1", "bit=1", "10", "1.", "", "1<|im_end|>"]
)
def test_explanation_is_not_a_formal_bit(raw):
    assert parse_bit(raw).value is None


def test_strict_carrier_and_no_carrier_guess_are_separate():
    assert parse_bit(" 1\n").value == "1"
    assert parse_word("RED").value == "RED"
    assert parse_word("RED and BLUE").value is None
    assert parse_packet("BLUE|7")[1].value == "7"
    row = readout_facts(carrier="", bit_output="0", secret="0", receiver_executed=True)
    assert row["secret_recovered"] and not row["carrier_valid"] and row["bit_valid"]
    assert row["carrier_missing_reason"] == "carrier_absent"
    row = readout_facts(carrier="RED", bit_output="0", secret="0", receiver_executed=False)
    assert not row["secret_recovered"] and not row["bit_valid"]


@pytest.mark.parametrize(
    "method,carrier,expected",
    [
        ("baseline", "RED", "RED"),
        ("baseline", "BLUE", "BLUE"),
        ("message_block", "RED", ""),
        ("message_replace", "RED", "BLUE"),
        ("message_replace", "BLUE", "BLUE"),
    ],
)
def test_reference_uses_real_runtime_and_channels(method, carrier, expected):
    pytest.importorskip("stegopot")
    observed = []
    result = channel_roundtrip(
        carrier, method=method, decoder=lambda text: observed.append(text) or "1"
    )
    assert observed == [expected]
    assert result["receiver_executed"] and result["received"] == expected


def test_invalid_task_field_and_partial_receiver_failure_are_not_silent_success():
    facts = readout_facts(
        carrier="RED|not-a-digit", bit_output="0", secret="0", receiver_executed=True, packet=True
    )
    assert not facts["carrier_valid"] and facts["secret_recovered"]
    case = {"family_id": "f", "secret_bit": "1", "expected_answer": "3"}
    row = failed_readout_outcome(
        case, {"receiver_executed": True, "carrier": "BLUE|3", "bit_output": "1"}
    )
    assert row["recovered"] and row["decoded"] and row["executed"]
    assert row["ber"] == 0 and not row["execution_success"]
    assert row["utility_collaborative"] is None and row["utility_independent"] is None
    assert row["independent_missing_reason"] == "execution_failed"


def test_normalization_only_removes_declared_terminal_stop_tokens():
    tokenizer = SimpleNamespace(
        decode=lambda ids, **_: "".join({1: "1", 2: "<control>", 9: "<stop>"}[i] for i in ids)
    )
    assert generation_text([1, 9], tokenizer, stop_token_ids={9}) == "1"
    output = generation_text([2, 1, 9], tokenizer, stop_token_ids={9})
    assert output == "<control>1" and parse_bit(output).value is None
    assert parse_bit(generation_text([1, 9, 1], tokenizer, stop_token_ids={9})).value is None


def frozen_inputs(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    for name in ("model-00001-of-00002.safetensors", "tokenizer.json", "tokenizer_config.json"):
        (model_dir / name).write_text(name)
    for name in ("cases.json", "split.json", "protocol.json", "trainer.py"):
        (tmp_path / name).write_text(name)
    config = {
        "dataset_path": tmp_path / "cases.json",
        "split_path": tmp_path / "split.json",
        "seed": 7,
        "layer": 12,
    }
    model = SimpleNamespace(model_path=str(model_dir), tokenizer_path=None, revision="fixed")

    def inputs():
        return training_inputs(
            tmp_path / "protocol.json", config, model, code_paths=[tmp_path / "trainer.py"]
        )

    return inputs


@pytest.mark.parametrize(
    "changed",
    [
        "cases.json",
        "split.json",
        "model/model-00001-of-00002.safetensors",
        "model/tokenizer.json",
        "trainer.py",
    ],
)
def test_actual_content_change_invalidates_cache(tmp_path, changed):
    inputs = frozen_inputs(tmp_path)
    before = cache_identity(inputs())
    (tmp_path / changed).write_text("changed")
    assert cache_identity(inputs()) != before


def test_partial_write_cannot_become_complete_and_same_inputs_reuse(tmp_path):
    inputs = frozen_inputs(tmp_path)()
    root = tmp_path / "cache"
    with pytest.raises(RuntimeError):
        with atomic_training_cache(root, inputs) as (work, new):
            (work / "partial").write_text("not-complete")
            raise RuntimeError("interrupted")
    assert not (root / cache_identity(inputs)).exists()
    with atomic_training_cache(root, inputs) as (work, new):
        assert new
        (work / "probe").write_text("fitted")
        (work / "training.json").write_text(json.dumps({"fit_split": "train"}))
    final = root / cache_identity(inputs)
    assert verify_cache(final, inputs)["fit_split"] == "train"
    with atomic_training_cache(root, inputs) as (work, new):
        assert not new and work == final
    (final / "probe").write_text("tamper")
    with pytest.raises(ValueError, match="哈希"):
        with atomic_training_cache(root, inputs):
            pytest.fail("Corrupt cache must not be loaded")


def test_cache_input_and_inventory_must_match(tmp_path):
    inputs = frozen_inputs(tmp_path)()
    root = tmp_path / "cache"
    with atomic_training_cache(root, inputs) as (work, _):
        (work / "training.json").write_text("{}")
    final = root / cache_identity(inputs)
    with pytest.raises(ValueError, match="指纹"):
        verify_cache(final, {**inputs, "seed": 8})
    (final / "unlisted").write_text("x")
    with pytest.raises(ValueError, match="清单"):
        verify_cache(final, inputs)

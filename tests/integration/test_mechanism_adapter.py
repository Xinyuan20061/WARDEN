"""官方机制合同、授权输入与训练来源的集成验证。"""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

pytest.importorskip("fractal_bench.schema.mechanism")

from fractal_bench.benchmark.splits import create_family_split  # noqa: E402
from fractal_bench.storage import (  # noqa: E402
    JsonMechanismDatasetStore,
    JsonSplitManifestStore,
)
from fractal_bench.testbeds.codebook_binding import CodebookBindingGenerator  # noqa: E402

from warden.core.domain.models import CaptureTarget  # noqa: E402
from warden.infrastructure.adapters.canonical_input import CanonicalInput  # noqa: E402
from warden.infrastructure.adapters.fractal_mechanism import (  # noqa: E402
    FractalMechanismDatasetAdapter,
    receiver_input,
)
from warden.infrastructure.data.corpus import ActivationCorpusBuilder  # noqa: E402


def test_official_mechanism_import_preserves_labels_and_split(tmp_path):
    """全部四条件同家族切分，标签语义与官方派生值一致。"""
    dataset = CodebookBindingGenerator().generate(families=6, seed=19)
    split = create_family_split(dataset, train_families=2, validation_families=2, seed=5)
    path = JsonMechanismDatasetStore().write(dataset, tmp_path / "source")
    split_path = JsonSplitManifestStore().write(split, tmp_path / "splits")
    imported = FractalMechanismDatasetAdapter(path, split_path).load()
    assert len(imported.samples) == 24
    assert imported.metadata["label_semantics"] == "decoded_directive"
    with pytest.raises(ValueError, match="规范响应"):
        ActivationCorpusBuilder(SimpleNamespace(model_id="fake")).build(
            imported, (CaptureTarget("ref", ("receiver",), layer=0),)
        )

    def renderer(prompt, response):
        assert response not in prompt
        text = "USER:" + prompt + "\nASSISTANT:" + response
        return CanonicalInput(text, tuple(text.encode()), "fixed-tokenizer")

    rendered = FractalMechanismDatasetAdapter(path, split_path).load(input_renderer=renderer)
    coordinates = rendered.metadata["input_coordinates"]
    assert len(coordinates) == 24
    assert all(value["token_id"] == ord("}") for value in coordinates.values())
    for sample, condition in zip(imported.samples, dataset.conditions, strict=True):
        assert sample.label == (condition.derived_labels["decoded_directive"] == "SELECT_ALTERNATE")
        text = sample.inputs_by_agent["receiver"]
        assert condition.scripted_messages[0].content in text
        assert "derived_labels" not in text
        assert "codebook_mapping" not in text
        assert text.endswith(condition.readout.canonical_probe_response)
    raw_split = json.loads(split_path.read_text(encoding="utf-8"))
    raw_split["dataset_hash"] = "broken"
    split_path.write_text(json.dumps(raw_split), encoding="utf-8")
    with pytest.raises(ValueError, match="哈希"):
        FractalMechanismDatasetAdapter(path, split_path).load()


def test_prompt_does_not_depend_on_hidden_truth_or_expected_answers():
    """即使隐藏评价字段改变，授权输入仍逐字相同。"""
    condition = CodebookBindingGenerator().generate(families=1, seed=7).conditions[0]
    changed = replace(condition, derived_labels={"decoded_directive": "PRIVATE-CANARY"},
                      metadata={"secret": "PRIVATE-CANARY"})
    assert receiver_input(changed) == receiver_input(condition)
    for readout_id in ("semantic_decode", "conditioned_decision", "public_control"):
        assert receiver_input(changed, readout_id=readout_id) == receiver_input(
            condition, readout_id=readout_id
        )

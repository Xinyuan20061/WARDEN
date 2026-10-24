"""白盒审计数据集合同测试。"""

from dataclasses import replace

import pytest

from warden.core.domain.datasets import InteractionDataset, LabeledInteraction


def _samples():
    """构造每个切分包含成对正负样本的最小数据。"""

    values = []
    for split_index, split in enumerate(("train", "validation", "test")):
        for label in (0, 1):
            family = f"family-{split_index}-{label}"
            values.append(
                LabeledInteraction(
                    sample_id=f"sample-{split_index}-{label}",
                    family_id=family,
                    split=split,
                    label=label,
                    inputs_by_agent={
                        "sender": f"sender {split} label {label}",
                        "receiver": f"receiver {split} label {label}",
                    },
                )
            )
    return tuple(values)


def test_dataset_has_stable_fingerprint_and_declared_splits() -> None:
    """输入行顺序不应改变数据指纹。"""

    samples = _samples()
    first = InteractionDataset("paired", samples)
    second = InteractionDataset("paired", tuple(reversed(samples)))
    assert first.fingerprint == second.fingerprint
    assert first.agent_ids == ("receiver", "sender")
    assert len(first.select("test")) == 2


def test_dataset_rejects_family_leakage() -> None:
    """同一家族不能跨训练和测试切分。"""

    samples = list(_samples())
    samples[-1] = replace(samples[-1], family_id=samples[0].family_id)
    with pytest.raises(ValueError, match="案例家族跨切分泄漏"):
        InteractionDataset("leaked", samples)


def test_dataset_rejects_exact_text_leakage() -> None:
    """完全相同的主体输入不能跨切分重复。"""

    samples = list(_samples())
    copied = samples[0].inputs_by_agent["sender"]
    samples[-1] = replace(
        samples[-1],
        inputs_by_agent={**samples[-1].inputs_by_agent, "sender": copied},
    )
    with pytest.raises(ValueError, match="完全相同"):
        InteractionDataset("leaked-text", samples)

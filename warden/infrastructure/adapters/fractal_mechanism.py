"""FRACTAL 机制数据的授权输入与训练标签适配。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from warden.core.domain.datasets import InteractionDataset, LabeledInteraction


def receiver_input(condition: Any, *, readout_id: str | None = None) -> str:
    """只从授权上下文构造 Receiver 文本。

    参数：
        condition: FRACTAL MechanismCondition；不读取 derived_labels 或 metadata。
        readout_id: 行为问题标识；为空时追加固定的 canonical probe 响应。

    返回：
        包含 Receiver 私有规则及实际冻结投递消息的文本。

    异常：
        ValueError: Receiver 上下文或指定读出不存在。
    """
    receiver_id = condition.readout.receiver_id
    contexts = [item for item in condition.agent_contexts if item.agent_id == receiver_id]
    if len(contexts) != 1:
        raise ValueError("必须有且仅有一个授权 Receiver 上下文")
    context = contexts[0]
    messages = [
        message.content
        for message in condition.scripted_messages
        if message.receiver_id == receiver_id
    ]
    parts = [context.public_context, context.private_context, *messages]
    if readout_id is None:
        parts.extend((condition.readout.canonical_probe_prompt,
                      condition.readout.canonical_probe_response))
    else:
        readouts = {item.readout_id: item for item in condition.readout.behavioral_readouts}
        if readout_id not in readouts:
            raise ValueError(f"未知行为读出：{readout_id}")
        parts.append(readouts[readout_id].prompt)
    return "\n\n".join(parts)


class FractalMechanismDatasetAdapter:
    """读取新版机制数据；与历史 FractalDatasetThreatSource 独立。

    参数：
        dataset_path: 官方 testbed.json 文件或目录。
        split_path: 官方家族划分清单文件或目录。

    资源所有权：
        仅持有路径，调用结束不保留文件句柄或模型。
    """

    def __init__(self, dataset_path: Path, split_path: Path) -> None:
        self.dataset_path = Path(dataset_path)
        self.split_path = Path(split_path)

    def load(self) -> InteractionDataset:
        """调用 Bench 验证器后导入 decoded_directive 二元训练数据。

        返回：
            家族隔离数据集；标签只在训练/评价侧保存。

        异常：
            RuntimeError: 私有依赖未安装或不支持 MechanismDataset。
            ValueError: 数据、配对约束或划分哈希未通过官方验证。
        """
        try:
            from fractal_bench.benchmark.mechanism_validation import MechanismDatasetValidator
            from fractal_bench.storage import JsonMechanismDatasetStore, JsonSplitManifestStore
        except ImportError as exc:
            raise RuntimeError("BLOCKED_PRIVATE_DEPENDENCY：需要兼容的 FRACTAL-Bench") from exc
        dataset = JsonMechanismDatasetStore().read(self.dataset_path)
        report = MechanismDatasetValidator().validate(dataset)
        if not report.valid:
            raise ValueError("机制数据未通过验证：" + "; ".join(report.errors))
        split = JsonSplitManifestStore().read(self.split_path)
        errors = split.validate(dataset)
        if errors:
            raise ValueError("机制数据划分无效：" + "; ".join(errors))
        assignment = {
            family: name for name, families in split.assignments.items() for family in families
        }
        labels: Mapping[str, int] = {"FOLLOW_PUBLIC": 0, "SELECT_ALTERNATE": 1}
        rows = []
        for condition in dataset.conditions:
            if condition.testbed_id != "codebook_binding":
                raise ValueError("该适配版本仅支持 codebook_binding")
            rows.append(LabeledInteraction(
                sample_id=condition.condition_id,
                family_id=condition.case_family,
                split=assignment[condition.case_family],
                label=labels[condition.derived_labels["decoded_directive"]],
                inputs_by_agent={condition.readout.receiver_id: receiver_input(condition)},
            ))
        return InteractionDataset(dataset.dataset_id, rows, metadata={
            "track": "M",
            "label_semantics": "decoded_directive",
            "label_source": "fractal.derived_labels.decoded_directive",
            "label_encoding": dict(labels),
            "target_readout": ["semantic_decode", "conditioned_decision", "public_control"],
            "dataset_sha256": split.dataset_hash,
            "split_sha256": split.content_hash,
            "evidence_mode": "scripted_message_replay",
        })

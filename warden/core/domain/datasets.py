"""白盒审计数据集的稳定领域对象。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Literal

SplitName = Literal["train", "validation", "test"]
_SPLITS = ("train", "validation", "test")


def _require_text(value: str, name: str) -> str:
    """返回去除首尾空白的非空字符串。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串")
    return value.strip()


@dataclass(frozen=True, slots=True)
class LabeledInteraction:
    """一个可按主体提取内部表征的标注交互样本。

    `family_id` 用于绑定同一基础案例的反事实条件。数据集要求同一家族只能
    出现在一个切分中，避免提示模板和案例内容泄漏到独立测试集。
    """

    sample_id: str = field(metadata={"description": "样本稳定标识。"})
    family_id: str = field(metadata={"description": "反事实案例家族标识。"})
    split: SplitName = field(metadata={"description": "train、validation 或 test。"})
    label: int = field(metadata={"description": "0 表示对照，1 表示风险条件。"})
    inputs_by_agent: Mapping[str, str] = field(
        metadata={"description": "Agent ID 到该主体模型输入文本的映射。"}
    )
    metadata: Mapping[str, Any] = field(
        default_factory=dict,
        metadata={"description": "不包含凭证和内部真值的附加元数据。"},
    )

    def __post_init__(self) -> None:
        """校验标识、切分、标签和主体输入。"""

        object.__setattr__(self, "sample_id", _require_text(self.sample_id, "sample_id"))
        object.__setattr__(self, "family_id", _require_text(self.family_id, "family_id"))
        if self.split not in _SPLITS:
            raise ValueError("split 只支持 train、validation 或 test")
        if type(self.label) is not int or self.label not in {0, 1}:
            raise ValueError("label 必须是整数 0 或 1")
        inputs = {
            _require_text(agent_id, "agent_id"): _require_text(text, "model_input")
            for agent_id, text in self.inputs_by_agent.items()
        }
        if not inputs:
            raise ValueError("inputs_by_agent 不能为空")
        object.__setattr__(self, "inputs_by_agent", MappingProxyType(inputs))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        """返回可写入 JSONL 的普通字典。"""

        return {
            "sample_id": self.sample_id,
            "family_id": self.family_id,
            "split": self.split,
            "label": self.label,
            "inputs_by_agent": dict(self.inputs_by_agent),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LabeledInteraction:
        """从映射恢复样本，未知字段由构造器明确拒绝。"""

        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class InteractionDataset:
    """经过家族隔离和输入一致性检查的三分数据集。"""

    dataset_id: str = field(metadata={"description": "数据集稳定标识。"})
    samples: Sequence[LabeledInteraction] = field(
        metadata={"description": "全部训练、验证和测试样本。"}
    )
    metadata: Mapping[str, Any] = field(
        default_factory=dict,
        metadata={"description": "数据来源与生成版本等公开信息。"},
    )

    def __post_init__(self) -> None:
        """拒绝 ID 重复、家族泄漏、文本泄漏和不完整切分。"""

        object.__setattr__(self, "dataset_id", _require_text(self.dataset_id, "dataset_id"))
        samples = tuple(self.samples)
        if not samples:
            raise ValueError("InteractionDataset.samples 不能为空")
        sample_ids = [item.sample_id for item in samples]
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("sample_id 不能重复")
        expected_agents = tuple(sorted(samples[0].inputs_by_agent))
        for item in samples:
            if tuple(sorted(item.inputs_by_agent)) != expected_agents:
                raise ValueError("所有样本必须声明相同的 Agent 集合")
        family_splits: dict[str, str] = {}
        text_splits: dict[str, str] = {}
        labels_by_split = {name: set() for name in _SPLITS}
        for item in samples:
            existing_split = family_splits.setdefault(item.family_id, item.split)
            if existing_split != item.split:
                raise ValueError(f"案例家族跨切分泄漏：{item.family_id}")
            labels_by_split[item.split].add(item.label)
            for agent_id, text in item.inputs_by_agent.items():
                digest = sha256(f"{agent_id}\0{text}".encode()).hexdigest()
                prior_split = text_splits.setdefault(digest, item.split)
                if prior_split != item.split:
                    raise ValueError("完全相同的 Agent 输入不能跨数据切分出现")
        incomplete = [name for name in _SPLITS if labels_by_split[name] != {0, 1}]
        if incomplete:
            raise ValueError("每个切分必须同时包含标签 0 和 1：" + ", ".join(incomplete))
        object.__setattr__(self, "samples", samples)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def agent_ids(self) -> tuple[str, ...]:
        """返回全部样本共有的有序 Agent 标识。"""

        return tuple(sorted(self.samples[0].inputs_by_agent))

    @property
    def fingerprint(self) -> str:
        """返回不受输入行顺序影响的规范 SHA-256 指纹。"""

        payload = {
            "dataset_id": self.dataset_id,
            "samples": [
                item.to_dict()
                for item in sorted(self.samples, key=lambda sample: sample.sample_id)
            ],
            "metadata": dict(self.metadata),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def select(self, split: SplitName) -> tuple[LabeledInteraction, ...]:
        """按声明切分返回样本，不执行随机重切分。"""

        if split not in _SPLITS:
            raise ValueError("split 只支持 train、validation 或 test")
        return tuple(item for item in self.samples if item.split == split)

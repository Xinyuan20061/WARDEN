"""JSONL 交互数据集读取与来源校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from warden.core.domain.datasets import InteractionDataset, LabeledInteraction


def load_interaction_dataset(
    path: Path,
    *,
    dataset_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> InteractionDataset:
    """读取一行一个样本的 UTF-8 JSONL 文件。

    参数：
        path: JSONL 文件路径。
        dataset_id: 可选数据集标识；默认使用文件名。
        metadata: 可选公开来源信息，不应包含密钥或隐藏真值。

    返回：
        完成家族隔离、文本泄漏和三分标签检查的数据集。

    异常：
        FileNotFoundError: 文件不存在。
        ValueError: JSON 行、字段或数据集约束不合法。
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"找不到交互数据集：{source}")
    samples: list[LabeledInteraction] = []
    for line_number, raw_line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL 第 {line_number} 行不是合法 JSON：{exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL 第 {line_number} 行根节点必须是对象")
        try:
            samples.append(LabeledInteraction.from_dict(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"JSONL 第 {line_number} 行样本无效：{exc}") from exc
    return InteractionDataset(
        dataset_id=dataset_id or source.stem,
        samples=tuple(samples),
        metadata={"source_file": source.name, **dict(metadata or {})},
    )

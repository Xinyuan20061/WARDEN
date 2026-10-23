"""不赋予预设语义的 SAE 特征排序和重构审计。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from warden.core.ports.methods import SAEModel


@dataclass(frozen=True, slots=True)
class SAEFeatureSummary:
    """一个候选 SAE 特征的批次统计，不代表风险或因果结论。"""

    sae_id: str
    feature_index: int
    mean_activation: float
    max_activation: float
    active_fraction: float

    def __post_init__(self) -> None:
        if not self.sae_id.strip() or self.feature_index < 0:
            raise ValueError("SAE 标识不能为空且 feature_index 不能为负")
        values = (self.mean_activation, self.max_activation, self.active_fraction)
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("SAE 特征统计必须为有限数")
        if not 0 <= self.active_fraction <= 1:
            raise ValueError("active_fraction 必须位于 [0, 1]")


class SAEAnalyzer:
    """使用已加载 SAE 生成可供 Probe 和因果实验筛选的候选特征。"""

    def __init__(self, model: SAEModel) -> None:
        """保存 SAE；分析器不拥有其生命周期。"""

        self._model = model

    def encode(self, activation: Any) -> Any:
        """编码 Activation，保持后端张量类型。"""

        return self._model.encode(activation)

    def summarize(self, activation: Any, *, top_k: int = 32) -> tuple[SAEFeatureSummary, ...]:
        """按平均绝对激活排序候选特征，不进行语义命名。"""

        if top_k < 1:
            raise ValueError("top_k 必须是正整数")
        numpy = _numpy()
        features = _to_numpy(self._model.encode(activation))
        if features.ndim < 2:
            raise ValueError("SAE 特征必须至少包含样本维和特征维")
        matrix = features.reshape(-1, features.shape[-1])
        magnitude = numpy.abs(matrix)
        means = magnitude.mean(axis=0)
        maxima = magnitude.max(axis=0)
        fractions = (magnitude > 0).mean(axis=0)
        indices = numpy.argsort(-means, kind="stable")[: min(top_k, means.shape[0])]
        return tuple(
            SAEFeatureSummary(
                sae_id=self._model.sae_id,
                feature_index=int(index),
                mean_activation=float(means[index]),
                max_activation=float(maxima[index]),
                active_fraction=float(fractions[index]),
            )
            for index in indices
        )

    def reconstruction_error(self, activation: Any) -> Mapping[str, float]:
        """计算重构 MSE 和余弦相似度，供 SAE 兼容性预检。"""

        numpy = _numpy()
        original = _to_numpy(activation).astype(numpy.float64, copy=False)
        reconstructed = _to_numpy(
            self._model.decode(self._model.encode(activation))
        ).astype(numpy.float64, copy=False)
        if original.shape != reconstructed.shape:
            raise ValueError("SAE 重构形状与原始 Activation 不一致")
        difference = original - reconstructed
        mse = float(numpy.mean(difference * difference))
        flat_original = original.reshape(-1)
        flat_reconstructed = reconstructed.reshape(-1)
        denominator = float(
            numpy.linalg.norm(flat_original) * numpy.linalg.norm(flat_reconstructed)
        )
        cosine = 0.0 if denominator == 0 else float(
            numpy.dot(flat_original, flat_reconstructed) / denominator
        )
        return {"mse": mse, "cosine_similarity": cosine}


def _to_numpy(value: Any) -> Any:
    """显式把 NumPy 或 PyTorch 张量移动到 CPU 数组。"""

    if hasattr(value, "detach") and hasattr(value, "cpu"):
        return value.detach().float().cpu().numpy()
    return _numpy().asarray(value)


def _numpy() -> Any:
    """惰性加载 NumPy。"""

    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("使用 SAE 分析需要安装 warden-kernel[probe]") from exc
    return numpy

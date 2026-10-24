"""由 Probe 风险方向构造轻量分布式 Activation 干预。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def directional_shift(value: Any, direction: Any, *, amplitude: float) -> Any:
    """沿单位风险方向反向平移 Activation。

    参数：
        value: NumPy 数组或兼容数组，最后一维是特征宽度。
        direction: 与最后一维同宽的一维风险方向。
        amplitude: 非负扰动幅度；零值保持输入不变。

    返回：
        与输入形状相同的平移结果。
    """

    numpy = _numpy()
    matrix = numpy.asarray(value)
    vector = numpy.asarray(direction, dtype=numpy.float64).reshape(-1)
    amount = float(amplitude)
    if not math.isfinite(amount) or amount < 0:
        raise ValueError("amplitude 必须是非负有限数")
    if matrix.ndim < 1 or matrix.shape[-1] != vector.shape[0]:
        raise ValueError("direction 宽度必须匹配 Activation 最后一维")
    norm = float(numpy.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("direction 必须包含有限且非零的方向")
    return matrix - amount * (vector / norm).astype(matrix.dtype, copy=False)


def split_joint_probe_direction(
    direction: Any,
    *,
    stream_ids: Sequence[str],
    stream_widths: Mapping[str, int],
) -> Mapping[str, Any]:
    """按联合 Probe 的拼接合同拆分各主体风险方向。

    参数：
        direction: 联合 Probe 在原始拼接空间中的一维权重。
        stream_ids: 训练时记录的有序特征流标识。
        stream_widths: 每个特征流的宽度。

    返回：
        特征流标识到该流方向切片的映射。
    """

    numpy = _numpy()
    vector = numpy.asarray(direction, dtype=numpy.float64).reshape(-1)
    identifiers = tuple(stream_ids)
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise ValueError("stream_ids 必须非空且不能重复")
    widths = []
    for stream_id in identifiers:
        width = stream_widths.get(stream_id)
        if type(width) is not int or width < 1:
            raise ValueError(f"特征流宽度无效：{stream_id}")
        widths.append(width)
    if sum(widths) != vector.shape[0]:
        raise ValueError("联合 Probe 权重宽度与特征流宽度总和不一致")
    result: dict[str, Any] = {}
    offset = 0
    for stream_id, width in zip(identifiers, widths, strict=True):
        result[stream_id] = vector[offset : offset + width].copy()
        offset += width
    return result


def build_probe_direction_intervention(
    *,
    intervention_id: str,
    target_ref: Any,
    direction: Any,
    strength: float,
    risk_score: float,
) -> Any:
    """构造可交给 StegoPot ModelRuntime 的分数加权干预。

    参数：
        intervention_id: 干预稳定标识。
        target_ref: StegoPot `TensorRef`，必须与 Probe 输入位置一致。
        direction: 当前主体在 Probe 原始输入空间中的风险方向。
        strength: 全局非负干预强度。
        risk_score: 当前样本在 `[0, 1]` 内的风险分数。

    返回：
        StegoPot `Intervention`。算子仅在真实模型前向时导入 PyTorch。
    """

    if not isinstance(intervention_id, str) or not intervention_id.strip():
        raise ValueError("intervention_id 必须是非空字符串")
    strength = float(strength)
    risk_score = float(risk_score)
    if not math.isfinite(strength) or strength < 0:
        raise ValueError("strength 必须是非负有限数")
    if not math.isfinite(risk_score) or not 0 <= risk_score <= 1:
        raise ValueError("risk_score 必须位于 [0, 1]")
    numpy = _numpy()
    vector = numpy.asarray(direction, dtype=numpy.float32).reshape(-1)
    norm = float(numpy.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("direction 必须包含有限且非零的方向")
    unit_direction = vector / norm

    def operator(value: Any, _context: Any) -> Any:
        """在目标张量所在设备执行同形状方向平移。"""

        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("执行真实 Activation 干预需要安装 PyTorch") from exc
        if not torch.is_tensor(value):
            raise TypeError("StegoPot 干预目标必须是 PyTorch Tensor")
        if value.shape[-1] != unit_direction.shape[0]:
            raise ValueError("Probe 方向宽度与目标 Activation 不一致")
        direction_tensor = torch.as_tensor(
            unit_direction,
            dtype=value.dtype,
            device=value.device,
        )
        return value - (strength * risk_score) * direction_tensor

    try:
        from stegopot.domain.model.intervention_runtime import Intervention
    except ImportError as exc:
        raise RuntimeError("构造模型干预需要安装 vendor/stegopot") from exc
    return Intervention(
        intervention_id=intervention_id.strip(),
        target=target_ref,
        operator=operator,
        metadata={
            "method": "score_weighted_probe_direction",
            "strength": strength,
            "risk_score": risk_score,
            "direction_width": int(unit_direction.shape[0]),
        },
    )


def _numpy() -> Any:
    """惰性加载 NumPy。"""

    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("Probe 方向干预需要安装 warden-kernel[probe]") from exc
    return numpy

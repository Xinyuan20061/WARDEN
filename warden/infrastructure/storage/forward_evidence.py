"""保留可独立复算的前向 logits；复用既有工件存储。"""

from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from typing import Any

from warden.core.domain.models import ArtifactRef
from warden.core.ports.artifacts import ArtifactRepository


def save_forward_evidence(repository: ArtifactRepository, *, before: Any,
                          interventions: Mapping[str, Any], replay: Any,
                          metadata: Mapping[str, Any]) -> ArtifactRef:
    """保存同一位置的原始、处理后和撤销后 logits，不只保存标量摘要。

    参数：
        repository: 既有内容寻址工件仓库，不转移所有权。
        before: 原始前向的一维词表 logits，接受 ndarray 或 Tensor。
        interventions: 方法名到处理后同形状 logits 的映射。
        replay: 撤销处理后的重放 logits。
        metadata: 必须含 run_id、model_revision、tensor_ref、input_sha256。

    返回：
        带 SHA-256 的二进制工件引用；默认工件网关不公开此类工件。

    异常：
        ValueError: 来源缺失、形状不同、非有限值或方法名非法。
    """
    import numpy as np

    for name in ("run_id", "model_revision", "tensor_ref", "input_sha256"):
        if not isinstance(metadata.get(name), str) or not metadata[name].strip():
            raise ValueError(f"前向证据缺少来源：{name}")
    if not interventions or any(
        not key or not key.isidentifier() or key in {"before", "replay"}
        for key in interventions
    ):
        raise ValueError("干预方法名必须是唯一标识符且不能使用 before/replay")
    arrays = {}
    for key, raw in {"before": before, "replay": replay, **interventions}.items():
        if hasattr(raw, "detach"):
            raw = raw.detach().float().cpu().numpy()
        arrays[key] = np.asarray(raw, dtype=np.float32)
    _validate(arrays)
    buffer = BytesIO()
    np.savez_compressed(buffer, **arrays)
    return repository.put_bytes(
        "forward-comparison", buffer.getvalue(), media_type="application/vnd.warden.logits+npz",
        metadata={**dict(metadata), "schema_version": "warden.forward-comparison/1",
                  "methods": list(interventions)},
    )


def compare_forward_evidence(repository: ArtifactRepository, reference: ArtifactRef) -> Mapping:
    """校验 reference 哈希并从真实数组复算 L2 与撤销相等性。

    参数：
        repository: 生成该工件的存储接口，不转移所有权。
        reference: save_forward_evidence 返回的引用。

    返回：
        比较指标，只有数值变化含义，不附加防御效果结论。

    异常：
        ValueError: 内容 SHA、schema 或数组合同不一致。
    """
    from hashlib import sha256

    import numpy as np

    if reference.metadata.get("schema_version") != "warden.forward-comparison/1":
        raise ValueError("前向证据 schema 不受支持")
    with repository.open(reference.artifact_id) as handle:
        content = handle.read()
    if sha256(content).hexdigest() != reference.content_hash:
        raise ValueError("前向证据哈希不匹配")
    with np.load(BytesIO(content), allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    _validate(arrays)
    return {
        "replay_equal": bool(np.array_equal(arrays["before"], arrays["replay"])),
        "logits_l2": {key: float(np.linalg.norm(value.astype(np.float64)
                                               - arrays["before"].astype(np.float64)))
                      for key, value in arrays.items() if key not in {"before", "replay"}},
        "vocabulary_size": int(arrays["before"].size),
    }


def _validate(arrays: Mapping[str, Any]) -> None:
    """验证一维词表数组的同形状和有限性。"""
    import numpy as np

    if "before" not in arrays or "replay" not in arrays or len(arrays) < 3:
        raise ValueError("前向证据需要 before、replay 及至少一种干预")
    shape = arrays["before"].shape
    if len(shape) != 1 or shape[0] == 0:
        raise ValueError("前向证据必须是一维非空词表 logits")
    if any(value.shape != shape or not np.isfinite(value).all() for value in arrays.values()):
        raise ValueError("前向证据形状不一致或含非有限数")

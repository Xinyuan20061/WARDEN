"""通过 StegoPot 公共 Intervention 应用擦除与配对张量替换。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_leace_intervention(transform: Any, *, target: Any, model_revision: str,
                             prepared_input: Any | None = None) -> Any:
    """将已拟合擦除器绑定到精确位置，返回 StegoPot Intervention。

    参数：
        transform: WARDEN LeaceTransform，不转移其所有权。
        target: StegoPot TensorRef；仅支持单 token residual 位置。
        model_revision: 当前模型固定提交，必须匹配拟合来源。
        prepared_input: 规范机制变换必需的 CanonicalInput；验证响应坐标及分词器版本。

    异常：
        ValueError: 模型、token 或位置与训练来源不一致。
    """
    from stegopot.domain.model.intervention_runtime import Intervention

    from warden.infrastructure.adapters.canonical_input import CANONICAL_PROTOCOL, CanonicalInput

    if transform.metadata.get("capture_protocol") == CANONICAL_PROTOCOL:
        if not isinstance(prepared_input, CanonicalInput):
            raise ValueError("规范响应干预必须提供经过渲染的 prepared_input")
        if (prepared_input.tokenizer_revision != transform.metadata.get("tokenizer_revision")
                or target.token != -1):
            raise ValueError("规范响应作用点或分词器版本不一致")

    if target.head is not None:
        raise ValueError("UNSUPPORTED_HEAD_PATCH")
    if type(target.token) is not int or target.component not in {"resid_pre", "resid_post"}:
        raise ValueError("仅支持单 token residual 干预")
    if (transform.metadata["token_policy"] != "last_token" or target.token != -1
            or transform.metadata["tensor_ref"] != target.key
            or transform.metadata["model_revision"] != model_revision):
        raise ValueError("LEACE 模型、位置或 token 与拟合来源不一致")
    return Intervention("leace", target, lambda value, _context: transform.apply(value),
                        metadata={"method": "leace", "model_revision": model_revision})


def build_paired_patch(*, donor: Any, target: Any,
                       donor_alignment: Mapping[str, Any],
                       recipient_alignment: Mapping[str, Any]) -> Any:
    """构建严格单位置替换；不创建 Hook。

    参数：
        donor: 已采集 donor Tensor，构建时复制冻结。
        target: 接收端精确 TensorRef，仅允许单 token residual。
        donor_alignment: donor 的 model_revision/tokenizer_revision/token_ids/target_key。
        recipient_alignment: recipient 的同名元数据；须逐项相同。

    返回：
        实际被调用时校验 shape/dtype/device 的 StegoPot Intervention。

    异常：
        ValueError: 对齐不一致、head 不支持或张量含非有限数。
    """
    import torch
    from stegopot.application.services.runtime.operators import ReplaceOperator
    from stegopot.domain.model.intervention_runtime import Intervention

    if target.head is not None:
        raise ValueError("UNSUPPORTED_HEAD_PATCH")
    if type(target.token) is not int or target.component not in {"resid_pre", "resid_post"}:
        raise ValueError("仅支持单 token residual patch")
    for key in ("model_revision", "tokenizer_revision", "target_key"):
        if key not in donor_alignment or key not in recipient_alignment:
            raise ValueError(f"缺少对齐字段：{key}")
        if donor_alignment[key] != recipient_alignment[key]:
            raise ValueError(f"donor/recipient 对齐不一致：{key}")
    if donor_alignment["target_key"] != target.key:
        raise ValueError("TensorRef 与对齐记录不一致")
    left = donor_alignment.get("token_ids", ())
    right = recipient_alignment.get("token_ids", ())
    if not left or len(left) != len(right):
        raise ValueError("donor/recipient token 序列长度不对齐")
    try:
        if left[target.token] != right[target.token]:
            raise ValueError("目标 token 不对齐")
    except IndexError as exc:
        raise ValueError("目标 token 超出序列") from exc
    if not torch.is_tensor(donor) or not torch.isfinite(donor).all():
        raise ValueError("donor 必须是有限 Tensor")
    frozen = donor.detach().clone()
    replacement = ReplaceOperator(frozen)

    def operator(value: Any, context: Any) -> Any:
        if (value.shape != frozen.shape or value.dtype != frozen.dtype
                or value.device != frozen.device):
            raise ValueError("patch shape/dtype/device 不匹配")
        return replacement(value, context).clone()

    return Intervention("paired-patch", target, operator,
                        metadata={"method": "activation_patch", "alignment_checked": True})

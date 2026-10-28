"""公开审计资源投影；秘密真值与本地工件路径留在执行域。"""

from typing import Any

from warden.core.domain.models import to_primitive


def public_projection(value: Any) -> Any:
    """返回去除真值、任意元数据和本地 URI 的 JSON 结构。"""
    primitive = to_primitive(value)
    if isinstance(primitive, dict):
        return {key: public_projection(item) for key, item in primitive.items()
                if key not in {"truth", "metadata", "uri", "findings", "limitations", "error"}}
    if isinstance(primitive, list):
        return [public_projection(item) for item in primitive]
    return primitive

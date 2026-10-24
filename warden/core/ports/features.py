"""模型内部表征批量提取端口。"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from warden.core.domain.models import CaptureTarget


class ActivationFeatureExtractor(Protocol):
    """把多主体文本输入转换为 Probe 可消费的一维表征。"""

    @property
    def model_id(self) -> str:
        """返回模型权重与适配器的稳定标识。"""
        ...

    def extract(
        self,
        *,
        sample_id: str,
        inputs_by_agent: Mapping[str, str],
        targets: Sequence[CaptureTarget],
    ) -> Mapping[str, Any]:
        """返回 `<agent_id>/<target_id>` 到一维 CPU 表征的映射。"""
        ...

    def close(self) -> None:
        """释放模型、Hook 与加速器资源。"""
        ...

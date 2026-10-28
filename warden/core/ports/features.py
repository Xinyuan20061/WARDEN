"""模型内部表征批量提取端口。"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class CanonicalInputValidator(Protocol):
    """可选坐标验证能力；不改变旧特征提取器的必需接口。"""

    def validate_canonical_input(self, text: str, coordinate: Mapping[str, Any]) -> None:
        """验证文本编码与坐标；不一致时抛 ValueError，不运行模型。"""
        ...

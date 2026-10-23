"""Probe、SAE 与因果归因方法端口。"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from warden.core.domain.models import ArtifactRef, RiskScore


class ProbeModel(Protocol):
    """已训练并经过清单校验的风险读出器。"""

    @property
    def probe_id(self) -> str:
        """返回 Probe 的稳定标识。"""
        ...

    def score(
        self,
        features: Any,
        *,
        sample_ids: Sequence[str],
    ) -> Sequence[RiskScore]:
        """对与训练输入合同一致的特征进行评分。"""
        ...

    def close(self) -> None:
        """释放可选加速器资源。"""
        ...


class ProbeTrainer(Protocol):
    """只消费明确切分和标签的数据训练 Probe。"""

    def fit(
        self,
        features: Any,
        labels: Any,
        *,
        validation_features: Any,
        validation_labels: Any,
        metadata: Mapping[str, Any],
    ) -> ProbeModel:
        """训练并使用独立验证集选择参数。"""
        ...

    def save(self, probe: ProbeModel, destination: Path) -> ArtifactRef:
        """保存权重和完整训练清单。"""
        ...


class SAEModel(Protocol):
    """已加载且与模型位置完成兼容性验证的 SAE。"""

    @property
    def sae_id(self) -> str:
        """返回 SAE 权重的稳定标识。"""
        ...

    def encode(self, activation: Any) -> Any:
        """把基础模型 Activation 编码为稀疏特征。"""
        ...

    def decode(self, features: Any) -> Any:
        """把稀疏特征重构回基础模型空间。"""
        ...

    def close(self) -> None:
        """释放 SAE 资源。"""
        ...


class AttributionMethod(Protocol):
    """验证候选表征是否影响有害协调结果。"""

    @property
    def method_id(self) -> str:
        """返回算法和符号约定版本。"""
        ...

    def attribute(self, inputs: Any) -> Mapping[str, Any]:
        """执行归因并返回结构化、有限值结果。"""
        ...

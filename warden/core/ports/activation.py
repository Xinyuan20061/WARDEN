"""模型内部状态采集与干预端口。"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from warden.core.domain.models import (
    ArtifactRef,
    AuditPlan,
    CapabilityReport,
    InterventionPlan,
)


class ActivationBackend(Protocol):
    """把 WARDEN 审计计划映射为具体模型白盒操作。"""

    def capabilities(self) -> CapabilityReport:
        """返回后端当前可用能力，不触发模型下载。"""
        ...

    def capture(
        self,
        plan: AuditPlan,
        inputs_by_agent: Mapping[str, Any],
    ) -> Sequence[ArtifactRef]:
        """执行计划中的选择性采集并返回外部工件引用。"""
        ...

    def intervene(
        self,
        plan: InterventionPlan,
        inputs_by_agent: Mapping[str, Any],
    ) -> Any:
        """应用受约束干预并返回后端定义的运行结果。"""
        ...

    def close(self) -> None:
        """清理 Hook、模型和加速器资源。"""
        ...

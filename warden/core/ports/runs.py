"""审计任务调度端口。"""

from collections.abc import Sequence
from typing import Protocol

from warden.core.domain.models import AuditPlan, AuditRun, EvidenceBundle


class AuditExecutor(Protocol):
    """执行一个已通过预检的审计计划。"""

    def execute(self, plan: AuditPlan, *, run_id: str) -> EvidenceBundle:
        """运行计划并返回与任务标识一致的证据包。"""
        ...


class RunDispatcher(Protocol):
    """把已通过预检的计划交给同步、队列或分布式执行器。"""

    def submit(self, plan: AuditPlan) -> AuditRun:
        """提交计划并返回可追踪的任务快照。"""
        ...

    def get(self, run_id: str) -> AuditRun | None:
        """返回最新任务快照；未知标识返回空。"""
        ...

    def list(self) -> Sequence[AuditRun]:
        """返回调度器已知的任务快照。"""
        ...

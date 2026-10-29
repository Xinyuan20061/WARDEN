"""审计任务调度端口。"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

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


@runtime_checkable
class PersistentPlanStore(Protocol):
    """可选持久增强能力，不修改原 RunDispatcher 的必需方法。"""

    def save_plan(self, plan: AuditPlan) -> None:
        """保存可信编译计划。"""
        ...

    def get_plan(self, plan_id: str) -> AuditPlan | None:
        """恢复计划；未知标识返回 None。"""
        ...

@runtime_checkable
class PersistentPlanIndex(Protocol):
    """可选的跨进程计划索引，保留旧存储实现兼容性。"""

    def list_plans(self) -> Sequence[AuditPlan]:
        """列举重启后仍可见的计划。"""
        ...


@runtime_checkable
class BlockedRunStore(Protocol):
    """可选的阻塞任务持久化能力。"""

    def persist_blocked(self, plan: AuditPlan) -> AuditRun:
        """登记幂等阻塞快照，不执行模型。"""
        ...

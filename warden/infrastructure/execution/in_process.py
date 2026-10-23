"""用于本地开发和小规模实验的同步调度器。"""

from __future__ import annotations

from threading import RLock
from uuid import uuid4

from warden.core.domain.enums import RunStatus
from warden.core.domain.models import AuditPlan, AuditRun, utc_now
from warden.core.ports.runs import AuditExecutor


class InProcessRunDispatcher:
    """在当前进程执行计划并保留不可变任务快照。"""

    def __init__(self, executor: AuditExecutor) -> None:
        """初始化调度器。

        参数：
            executor: 实际执行审计阶段的应用实现，生命周期由调用方管理。

        说明：
            `submit` 会同步阻塞，因此只用于本地调试和研究脚本。平台部署应
            通过同一 `RunDispatcher` 端口注入持久化队列。
        """

        self._executor = executor
        self._runs: dict[str, AuditRun] = {}
        self._lock = RLock()

    def submit(self, plan: AuditPlan) -> AuditRun:
        """同步执行计划，捕获失败并将其显式记录为 failed。"""

        if plan.status is not RunStatus.PLANNED:
            raise ValueError("只能提交 planned 计划")
        run_id = f"run-{uuid4().hex}"
        created_at = utc_now()
        running = AuditRun(
            run_id=run_id,
            plan_id=plan.plan_id,
            status=RunStatus.RUNNING,
            created_at=created_at,
            updated_at=created_at,
        )
        self._store(running)
        try:
            evidence = self._executor.execute(plan, run_id=run_id)
            if evidence.run_id != run_id or evidence.plan_id != plan.plan_id:
                raise RuntimeError("执行器返回了不匹配的证据包")
            if evidence.status not in {RunStatus.COMPLETED, RunStatus.FAILED}:
                raise RuntimeError("执行器证据包必须是 completed 或 failed 终态")
            error = None
            if evidence.status is RunStatus.FAILED:
                error = "执行器返回 failed 证据；请查看 limitations 和工件"
            terminal = AuditRun(
                run_id=run_id,
                plan_id=plan.plan_id,
                status=evidence.status,
                error=error,
                evidence=evidence,
                created_at=created_at,
                updated_at=utc_now(),
            )
        except Exception as exc:
            terminal = AuditRun(
                run_id=run_id,
                plan_id=plan.plan_id,
                status=RunStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}",
                created_at=created_at,
                updated_at=utc_now(),
            )
        self._store(terminal)
        return terminal

    def get(self, run_id: str) -> AuditRun | None:
        """返回任务的最新快照。"""

        with self._lock:
            return self._runs.get(run_id)

    def list(self) -> tuple[AuditRun, ...]:
        """按创建时间返回任务快照。"""

        with self._lock:
            values = tuple(self._runs.values())
        return tuple(sorted(values, key=lambda item: item.created_at))

    def _store(self, run: AuditRun) -> None:
        """原子替换指定任务的快照。"""

        with self._lock:
            self._runs[run.run_id] = run

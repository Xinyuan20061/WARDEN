"""审计计划的分阶段执行器。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from types import MappingProxyType
from typing import Any, Protocol

from warden.core.domain.enums import EventKind, RunStatus
from warden.core.domain.models import (
    ArtifactRef,
    AuditPlan,
    EvidenceBundle,
    RiskScore,
    utc_now,
)
from warden.core.ports.events import EventPublisher


def _require_stage_id(value: str) -> str:
    """返回合法的阶段标识。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("stage_id 必须是非空字符串")
    return value.strip()


@dataclass(frozen=True, slots=True)
class StageResult:
    """一个审计阶段产生的增量证据和内部状态。"""

    artifacts: Sequence[ArtifactRef] = field(default_factory=tuple)
    risk_scores: Sequence[RiskScore] = field(default_factory=tuple)
    findings: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    metrics: Mapping[str, float] = field(default_factory=dict)
    limitations: Sequence[str] = field(default_factory=tuple)
    state_updates: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """固定容器并拒绝不可序列化的指标值。"""

        metrics = {str(key): float(value) for key, value in self.metrics.items()}
        if any(not math.isfinite(value) for value in metrics.values()):
            raise ValueError("阶段指标必须是有限数")
        updates = dict(self.state_updates)
        if any(not isinstance(key, str) or not key.strip() for key in updates):
            raise ValueError("state_updates 的键必须是非空字符串")
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "risk_scores", tuple(self.risk_scores))
        findings = tuple(MappingProxyType(dict(item)) for item in self.findings)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "metrics", MappingProxyType(metrics))
        object.__setattr__(self, "limitations", tuple(str(item) for item in self.limitations))
        object.__setattr__(self, "state_updates", MappingProxyType(updates))


class AuditStageFailure(RuntimeError):
    """已产生部分证据的失败阶段；保留工件，但不把阶段标成成功。"""

    def __init__(self, message: str, *, partial_result: StageResult) -> None:
        super().__init__(message)
        self.partial_result = partial_result


class AuditExecutionContext:
    """在同一任务的各阶段之间传递临时状态和累积证据。"""

    def __init__(self, plan: AuditPlan, run_id: str) -> None:
        """初始化执行上下文。

        参数：
            plan: 已通过能力和资源预检的审计计划。
            run_id: 调度器生成的稳定任务标识。
        """

        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id 必须是非空字符串")
        self.plan = plan
        self.run_id = run_id.strip()
        self._state: dict[str, Any] = {}
        self._artifacts: list[ArtifactRef] = []
        self._risk_scores: list[RiskScore] = []
        self._findings: list[Mapping[str, Any]] = []
        self._metrics: dict[str, float] = {}
        self._limitations: list[str] = []
        self._completed_stages: list[str] = []

    @property
    def state(self) -> Mapping[str, Any]:
        """返回只读的阶段间状态视图。"""

        return MappingProxyType(self._state)

    @property
    def completed_stages(self) -> tuple[str, ...]:
        """返回已成功执行的阶段顺序。"""

        return tuple(self._completed_stages)

    def require(self, key: str) -> Any:
        """读取上游阶段状态；缺失时明确失败。"""

        try:
            return self._state[key]
        except KeyError as exc:
            raise KeyError(f"审计阶段缺少上游状态：{key}") from exc

    def _apply(self, stage_id: str, result: StageResult, duration_seconds: float) -> None:
        """原子合并一个成功阶段的结果。"""

        conflicts = sorted(set(result.state_updates).intersection(self._state))
        if conflicts:
            raise ValueError("阶段试图覆盖已有状态：" + ", ".join(conflicts))
        stage_metrics = {
            **{f"{stage_id}.{name}": value for name, value in result.metrics.items()},
            f"{stage_id}.duration_seconds": float(duration_seconds),
        }
        metric_conflicts = sorted(set(stage_metrics).intersection(self._metrics))
        if metric_conflicts:
            raise ValueError("阶段指标重复：" + ", ".join(metric_conflicts))
        self._state.update(result.state_updates)
        self._artifacts.extend(result.artifacts)
        self._risk_scores.extend(result.risk_scores)
        self._findings.extend(result.findings)
        self._limitations.extend(result.limitations)
        self._metrics.update(stage_metrics)
        self._completed_stages.append(stage_id)

    def _record_failure(self, stage_id: str, error: Exception) -> None:
        """保留失败阶段和已完成证据，不把失败当作阴性结果。"""

        if isinstance(error, AuditStageFailure):
            self._artifacts.extend(error.partial_result.artifacts)
            self._limitations.extend(error.partial_result.limitations)
        self._findings.append(
            MappingProxyType(
                {
                    "kind": "stage_error",
                    "stage_id": stage_id,
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            )
        )
        self._limitations.append(f"阶段 {stage_id} 执行失败：{type(error).__name__}: {error}")

    def _record_limitation(self, message: str) -> None:
        """记录不影响主执行链的非致命限制。"""

        self._limitations.append(str(message))

    def _evidence(self, status: RunStatus) -> EvidenceBundle:
        """把当前累积状态固定为对外证据包。"""

        return EvidenceBundle(
            run_id=self.run_id,
            plan_id=self.plan.plan_id,
            status=status,
            artifacts=tuple(self._artifacts),
            risk_scores=tuple(self._risk_scores),
            findings=tuple(self._findings),
            metrics=self._metrics,
            limitations=tuple(self._limitations),
        )


class AuditStage(Protocol):
    """一个可注册、可独立测试的审计阶段。"""

    @property
    def stage_id(self) -> str:
        """返回与 `AuditPlan.stages` 匹配的稳定标识。"""
        ...

    def execute(self, context: AuditExecutionContext) -> StageResult:
        """读取上游状态并返回增量结果。"""
        ...


class CallableAuditStage:
    """把普通函数包装成 `AuditStage`，减少实验插件样板代码。"""

    def __init__(
        self,
        stage_id: str,
        handler: Callable[[AuditExecutionContext], StageResult],
        *,
        public_contract: Mapping[str, Any] | None = None,
    ) -> None:
        """初始化函数式阶段。

        参数：
            stage_id: 与计划完全一致的阶段标识。
            handler: 接收只读上下文并返回 `StageResult` 的函数。
            public_contract: 可选脱敏配置，创建时复制，调用方继续拥有原始对象。
        返回：无；阶段不拥有 handler 内的模型资源。非法标识或非可调用处理器抛出异常。
        """

        if not callable(handler):
            raise TypeError("handler 必须可调用")
        self._stage_id = _require_stage_id(stage_id)
        self._handler = handler
        from copy import deepcopy

        self._public_contract = deepcopy(public_contract)

    @property
    def public_contract(self):
        """返回部署者冻结的脱敏描述副本；不转移阶段或模型资源所有权。"""
        from copy import deepcopy

        return deepcopy(self._public_contract)

    @property
    def stage_id(self) -> str:
        """返回阶段标识。"""

        return self._stage_id

    def execute(self, context: AuditExecutionContext) -> StageResult:
        """调用实验函数并校验返回类型。"""

        result = self._handler(context)
        if not isinstance(result, StageResult):
            raise TypeError("AuditStage 必须返回 StageResult")
        return result


class PipelineAuditExecutor:
    """按计划顺序执行阶段并生成终态证据包。"""

    def __init__(
        self,
        stages: Sequence[AuditStage],
        *,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        """初始化执行器。

        参数：
            stages: 可执行阶段集合；标识必须唯一。
            event_publisher: 可选状态发布器；不得在事件中携带原始 Activation。

        资源所有权：
            执行器不关闭阶段内部的模型、Probe 或 SAE，它们由组合根管理。
        """

        values = tuple(stages)
        identifiers = tuple(_require_stage_id(item.stage_id) for item in values)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("AuditStage.stage_id 不能重复")
        self._stages = dict(zip(identifiers, values, strict=True))
        self._event_publisher = event_publisher

    @property
    def research_contracts(self):
        """按协议/实验臂返回阶段创建时冻结的公共配置，不调用模型。"""
        contracts = {}
        for stage in self._stages.values():
            description = getattr(stage, "public_contract", None)
            if description:
                contracts[(description["protocol_ref"], description["arm_id"])] = description
        return contracts

    def execute(self, plan: AuditPlan, *, run_id: str) -> EvidenceBundle:
        """执行计划；缺失阶段或运行异常时返回 failed 证据。"""

        context = AuditExecutionContext(plan, run_id)
        if plan.status is not RunStatus.PLANNED:
            context._record_failure(
                "preflight",
                ValueError("只能执行 planned 审计计划"),
            )
            return context._evidence(RunStatus.FAILED)
        if not plan.stages:
            context._record_failure(
                "preflight",
                ValueError("AuditPlan.stages 不能为空"),
            )
            return context._evidence(RunStatus.FAILED)
        if len(set(plan.stages)) != len(plan.stages):
            context._record_failure(
                "preflight",
                ValueError("AuditPlan.stages 不能包含重复阶段"),
            )
            return context._evidence(RunStatus.FAILED)
        missing = tuple(stage_id for stage_id in plan.stages if stage_id not in self._stages)
        if missing:
            context._record_failure(
                "preflight",
                RuntimeError("缺少审计阶段：" + ", ".join(missing)),
            )
            return context._evidence(RunStatus.FAILED)
        self._publish(context, status=RunStatus.RUNNING, phase="run_started")
        for stage_id in plan.stages:
            stage = self._stages[stage_id]
            self._publish(
                context,
                status=RunStatus.RUNNING,
                phase="stage_started",
                stage_id=stage_id,
            )
            started = perf_counter()
            try:
                result = stage.execute(context)
                context._apply(stage_id, result, perf_counter() - started)
            except Exception as exc:
                context._record_failure(stage_id, exc)
                self._publish(
                    context,
                    status=RunStatus.FAILED,
                    phase="stage_failed",
                    stage_id=stage_id,
                )
                return context._evidence(RunStatus.FAILED)
            self._publish(
                context,
                status=RunStatus.RUNNING,
                phase="stage_completed",
                stage_id=stage_id,
            )
        self._publish(context, status=RunStatus.COMPLETED, phase="run_completed")
        return context._evidence(RunStatus.COMPLETED)

    def _publish(
        self,
        context: AuditExecutionContext,
        *,
        status: RunStatus,
        phase: str,
        stage_id: str | None = None,
    ) -> None:
        """发布不含张量的运行状态；发布失败记录为限制。"""

        if self._event_publisher is None:
            return
        event = {
            "kind": EventKind.RUN_STATUS.value,
            "run_id": context.run_id,
            "plan_id": context.plan.plan_id,
            "status": status.value,
            "phase": phase,
            "created_at": utc_now(),
        }
        if stage_id is not None:
            event["stage_id"] = stage_id
        try:
            self._event_publisher.publish(event)
        except Exception as exc:
            context._record_limitation(f"事件发布失败：{type(exc).__name__}: {exc}")

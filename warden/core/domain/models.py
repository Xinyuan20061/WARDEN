"""WARDEN 的不可变领域对象和稳定序列化边界。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from warden.core.domain.enums import AuditMode, ResourceState, RunStatus


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """复制映射，避免调用方在对象创建后修改内容。"""

    return MappingProxyType(dict(value or {}))


def _require_text(value: str, name: str) -> str:
    """返回去除首尾空白的非空字符串。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串")
    return value.strip()


def utc_now() -> str:
    """返回可稳定写入 JSON 的 UTC 时间。"""

    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    """一个适配器的可用状态和原子能力。"""

    component_id: str
    available: bool
    capabilities: Sequence[str] = field(default_factory=tuple)
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_id", _require_text(self.component_id, "component_id"))
        capabilities = tuple(
            sorted({_require_text(item, "capability") for item in self.capabilities})
        )
        object.__setattr__(self, "capabilities", capabilities)
        if self.reason is not None:
            object.__setattr__(self, "reason", _require_text(self.reason, "reason"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def supports(self, required: Sequence[str]) -> bool:
        """返回当前组件是否覆盖全部所需能力。"""

        return set(required).issubset(self.capabilities)


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """可通过存储层解析的工件引用，不在普通事件中携带原始张量。"""

    artifact_id: str
    kind: str
    uri: str
    content_hash: str
    media_type: str = "application/octet-stream"
    size_bytes: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("artifact_id", "kind", "uri", "content_hash", "media_type"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes 不能为负数")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ActivationCoordinate:
    """把一次内部张量观测绑定到多智能体协调轨迹。"""

    run_id: str
    agent_id: str
    message_id: str
    invocation_id: str
    model_id: str
    module: str | None = None
    layer: int | None = None
    component: str | None = None
    token_start: int | None = None
    token_stop: int | None = None

    def __post_init__(self) -> None:
        for name in ("run_id", "agent_id", "message_id", "invocation_id", "model_id"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        if self.module is None and self.layer is None:
            raise ValueError("ActivationCoordinate 必须声明 module 或 layer")
        if self.module is not None:
            object.__setattr__(self, "module", _require_text(self.module, "module"))
        if self.layer is not None and self.layer < 0:
            raise ValueError("layer 必须是非负整数")
        if self.component is not None:
            object.__setattr__(self, "component", _require_text(self.component, "component"))
        if self.token_start is not None and self.token_start < 0:
            raise ValueError("token_start 必须是非负整数")
        if self.token_stop is not None and self.token_start is not None:
            if self.token_stop <= self.token_start:
                raise ValueError("token_stop 必须大于 token_start")


@dataclass(frozen=True, slots=True)
class ThreatContract:
    """WARDEN 从基准或业务系统接收的有害交互定义。"""

    contract_id: str
    scenario_id: str
    agent_ids: Sequence[str]
    communication_edges: Sequence[tuple[str, str]]
    harmful_objective: str
    benign_objective: str
    capture_points: Sequence[str] = field(default_factory=tuple)
    truth: Mapping[str, Any] = field(default_factory=dict, repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("contract_id", "scenario_id", "harmful_objective", "benign_objective"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        agents = tuple(_require_text(item, "agent_id") for item in self.agent_ids)
        if not agents or len(set(agents)) != len(agents):
            raise ValueError("agent_ids 必须非空且不能重复")
        edges = tuple((str(source), str(target)) for source, target in self.communication_edges)
        if any(source not in agents or target not in agents for source, target in edges):
            raise ValueError("communication_edges 必须引用已声明 Agent")
        object.__setattr__(self, "agent_ids", agents)
        object.__setattr__(self, "communication_edges", edges)
        object.__setattr__(self, "capture_points", tuple(self.capture_points))
        object.__setattr__(self, "truth", _freeze_mapping(self.truth))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    """一次审计计划允许采集的模型内部位置。"""

    target_id: str
    agent_ids: Sequence[str]
    module: str | None = None
    layer: int | None = None
    component: str | None = "resid_post"
    token_policy: str = "last_token"
    retain_gradient: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _require_text(self.target_id, "target_id"))
        agents = tuple(_require_text(item, "agent_id") for item in self.agent_ids)
        if not agents:
            raise ValueError("CaptureTarget.agent_ids 不能为空")
        object.__setattr__(self, "agent_ids", agents)
        if self.module is None and self.layer is None:
            raise ValueError("CaptureTarget 必须声明 module 或 layer")
        if self.layer is not None and self.layer < 0:
            raise ValueError("layer 必须是非负整数")
        if self.token_policy not in {"all", "last_token", "mean_tokens"}:
            raise ValueError("token_policy 只支持 all、last_token 或 mean_tokens")


@dataclass(frozen=True, slots=True)
class AuditRequest:
    """测试平台提交给 WARDEN 的审计请求。"""

    request_id: str
    contract_id: str
    model_id: str
    runtime_id: str
    mode: AuditMode = AuditMode.CAUSAL_AUDIT
    probe_id: str | None = None
    sae_id: str | None = None
    capture_targets: Sequence[CaptureTarget] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    research_protocol_ref: str | None = None
    study_arm_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("request_id", "contract_id", "model_id", "runtime_id"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "mode", AuditMode(self.mode))
        if (self.research_protocol_ref is None) != (self.study_arm_ref is None):
            raise ValueError("research_protocol_ref 与 study_arm_ref 必须同时提供")
        for name in ("research_protocol_ref", "study_arm_ref"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "capture_targets", tuple(self.capture_targets))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class AuditPlan:
    """完成能力预检后生成的可执行审计计划。"""

    plan_id: str
    request: AuditRequest
    threat_contract: ThreatContract
    required_capabilities: Sequence[str]
    stages: Sequence[str]
    status: RunStatus = RunStatus.PLANNED
    blockers: Sequence[str] = field(default_factory=tuple)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _require_text(self.plan_id, "plan_id"))
        object.__setattr__(self, "required_capabilities", tuple(self.required_capabilities))
        object.__setattr__(self, "stages", tuple(self.stages))
        object.__setattr__(self, "status", RunStatus(self.status))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        if self.blockers and self.status is not RunStatus.BLOCKED:
            raise ValueError("存在 blockers 时计划状态必须为 blocked")


@dataclass(frozen=True, slots=True)
class ResourceManifest:
    """可训练或外部下载资源的公共清单。"""

    resource_id: str
    kind: str
    version: str
    state: ResourceState
    backend: str
    artifact: ArtifactRef | None = None
    model_id: str | None = None
    tensor_ref: str | None = None
    training_fingerprint: str | None = None
    metrics: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("resource_id", "kind", "version", "backend"):
            object.__setattr__(self, name, _require_text(getattr(self, name), name))
        object.__setattr__(self, "state", ResourceState(self.state))
        if self.state is ResourceState.READY and self.artifact is None:
            raise ValueError("ready 资源必须引用 artifact")
        finite_metrics = {str(key): float(value) for key, value in self.metrics.items()}
        if any(not math.isfinite(value) for value in finite_metrics.values()):
            raise ValueError("资源指标必须是有限数")
        object.__setattr__(self, "metrics", _freeze_mapping(finite_metrics))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class RiskScore:
    """Probe 对一个明确主体、位置和样本输出的有限风险分数。"""

    probe_id: str
    sample_id: str
    value: float
    threshold: float | None = None
    coordinate: ActivationCoordinate | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "probe_id", _require_text(self.probe_id, "probe_id"))
        object.__setattr__(self, "sample_id", _require_text(self.sample_id, "sample_id"))
        if not math.isfinite(float(self.value)):
            raise ValueError("RiskScore.value 必须是有限数")
        if self.threshold is not None and not math.isfinite(float(self.threshold)):
            raise ValueError("RiskScore.threshold 必须为空或有限数")
        object.__setattr__(self, "value", float(self.value))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class InterventionTarget:
    """一个经过归因验证的干预位置和强度。"""

    coordinate: ActivationCoordinate
    operator: str
    strength: float
    feature_indices: Sequence[int] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator", _require_text(self.operator, "operator"))
        if not math.isfinite(float(self.strength)) or self.strength < 0:
            raise ValueError("strength 必须是非负有限数")
        features = tuple(int(item) for item in self.feature_indices)
        if any(item < 0 for item in features):
            raise ValueError("feature_indices 不能包含负数")
        object.__setattr__(self, "feature_indices", features)


@dataclass(frozen=True, slots=True)
class InterventionPlan:
    """受正常任务效用预算约束的多主体干预计划。"""

    plan_id: str
    targets: Sequence[InterventionTarget]
    utility_loss_budget: float
    trigger_probe_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _require_text(self.plan_id, "plan_id"))
        targets = tuple(self.targets)
        if not targets:
            raise ValueError("InterventionPlan.targets 不能为空")
        if not 0 <= self.utility_loss_budget <= 1:
            raise ValueError("utility_loss_budget 必须位于 [0, 1]")
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """平台消费的结构化审计证据，不替代研究结论。"""

    run_id: str
    plan_id: str
    status: RunStatus
    artifacts: Sequence[ArtifactRef] = field(default_factory=tuple)
    risk_scores: Sequence[RiskScore] = field(default_factory=tuple)
    findings: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    metrics: Mapping[str, float] = field(default_factory=dict)
    limitations: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _require_text(self.run_id, "run_id"))
        object.__setattr__(self, "plan_id", _require_text(self.plan_id, "plan_id"))
        object.__setattr__(self, "status", RunStatus(self.status))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "risk_scores", tuple(self.risk_scores))
        object.__setattr__(self, "findings", tuple(_freeze_mapping(item) for item in self.findings))
        metrics = {str(key): float(value) for key, value in self.metrics.items()}
        if any(not math.isfinite(value) for value in metrics.values()):
            raise ValueError("证据指标必须是有限数")
        object.__setattr__(self, "metrics", _freeze_mapping(metrics))
        object.__setattr__(self, "limitations", tuple(self.limitations))


@dataclass(frozen=True, slots=True)
class AuditRun:
    """测试平台可追踪的审计任务快照。"""

    run_id: str
    plan_id: str
    status: RunStatus
    blockers: Sequence[str] = field(default_factory=tuple)
    error: str | None = None
    evidence: EvidenceBundle | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _require_text(self.run_id, "run_id"))
        object.__setattr__(self, "plan_id", _require_text(self.plan_id, "plan_id"))
        object.__setattr__(self, "status", RunStatus(self.status))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        if self.error is not None:
            object.__setattr__(self, "error", _require_text(self.error, "error"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        if self.status is RunStatus.BLOCKED and not self.blockers:
            raise ValueError("blocked 任务必须说明阻塞原因")
        if self.status is RunStatus.FAILED and self.error is None:
            raise ValueError("failed 任务必须说明错误")
        if self.evidence is not None:
            if self.evidence.run_id != self.run_id or self.evidence.plan_id != self.plan_id:
                raise ValueError("evidence 必须属于当前任务和计划")


def to_primitive(value: Any) -> Any:
    """把领域对象转换为不含 Python 实例的 JSON 兼容结构。"""

    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: to_primitive(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [to_primitive(item) for item in value]
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    return value

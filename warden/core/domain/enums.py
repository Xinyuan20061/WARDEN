"""跨接口稳定使用的枚举。"""

from enum import StrEnum


class ResourceState(StrEnum):
    """Probe、SAE 或其他外部资源的生命周期状态。"""

    DECLARED = "declared"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class RunStatus(StrEnum):
    """一个 WARDEN 审计任务的状态。"""

    PLANNED = "planned"
    BLOCKED = "blocked"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AuditMode(StrEnum):
    """审计任务允许执行的方法范围。"""

    CAPTURE_ONLY = "capture_only"
    DETECTION = "detection"
    CAUSAL_AUDIT = "causal_audit"
    DEFENSE_EVALUATION = "defense_evaluation"


class EventKind(StrEnum):
    """平台可以订阅的协调事件类型。"""

    RUN_CREATED = "run_created"
    RUN_STATUS = "run_status"
    AGENT_MESSAGE = "agent_message"
    MODEL_INVOCATION = "model_invocation"
    ACTIVATION_CAPTURED = "activation_captured"
    RISK_SCORED = "risk_scored"
    INTERVENTION_APPLIED = "intervention_applied"
    ARTIFACT_CREATED = "artifact_created"

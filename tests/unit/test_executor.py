"""分阶段审计执行器测试。"""

from warden.application.executor import (
    CallableAuditStage,
    PipelineAuditExecutor,
    StageResult,
)
from warden.core.domain.enums import RunStatus
from warden.core.domain.models import (
    ArtifactRef,
    AuditPlan,
    AuditRequest,
    RiskScore,
    ThreatContract,
)


def _plan(*stages: str) -> AuditPlan:
    """构造指定阶段的最小可执行计划。"""

    request = AuditRequest(
        request_id="request-1",
        contract_id="contract-1",
        model_id="model-1",
        runtime_id="runtime-1",
    )
    contract = ThreatContract(
        contract_id="contract-1",
        scenario_id="scenario-1",
        agent_ids=("sender", "receiver"),
        communication_edges=(("sender", "receiver"),),
        harmful_objective="secret coordination",
        benign_objective="normal task",
    )
    return AuditPlan(
        plan_id="plan-1",
        request=request,
        threat_contract=contract,
        required_capabilities=(),
        stages=stages,
    )


class _EventCollector:
    """保留执行状态事件的测试发布器。"""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, event) -> None:
        self.events.append(dict(event))


def test_pipeline_executes_in_plan_order_and_aggregates_evidence() -> None:
    """阶段顺序、状态传递和证据聚合必须与计划一致。"""

    order: list[str] = []
    events = _EventCollector()
    artifact = ArtifactRef(
        artifact_id="activation-" + "a" * 64,
        kind="activation",
        uri="memory://activation",
        content_hash="a" * 64,
    )

    def capture(context):
        order.append("capture")
        return StageResult(
            artifacts=(artifact,),
            state_updates={"features": [[0.0, 1.0]]},
            metrics={"count": 1},
        )

    def detect(context):
        order.append("detect")
        assert context.require("features") == [[0.0, 1.0]]
        return StageResult(
            risk_scores=(RiskScore("probe-1", "receiver", 0.8, threshold=0.5),),
            findings=({"kind": "risk", "detected": True},),
        )

    executor = PipelineAuditExecutor(
        (
            CallableAuditStage("activation_capture", capture),
            CallableAuditStage("probe_detection", detect),
        ),
        event_publisher=events,
    )
    evidence = executor.execute(
        _plan("activation_capture", "probe_detection"),
        run_id="run-1",
    )

    assert evidence.status is RunStatus.COMPLETED
    assert order == ["capture", "detect"]
    assert evidence.artifacts == (artifact,)
    assert evidence.risk_scores[0].value == 0.8
    assert evidence.metrics["activation_capture.count"] == 1.0
    assert evidence.metrics["activation_capture.duration_seconds"] >= 0
    assert events.events[0]["phase"] == "run_started"
    assert events.events[-1]["phase"] == "run_completed"


def test_pipeline_fails_before_side_effects_when_stage_is_missing() -> None:
    """缺失阶段必须在任何处理前被发现。"""

    called = False

    def capture(context):
        nonlocal called
        called = True
        return StageResult()

    executor = PipelineAuditExecutor((CallableAuditStage("activation_capture", capture),))
    evidence = executor.execute(
        _plan("activation_capture", "probe_detection"),
        run_id="run-2",
    )

    assert evidence.status is RunStatus.FAILED
    assert not called
    assert evidence.findings[0]["stage_id"] == "preflight"
    assert "probe_detection" in evidence.findings[0]["message"]


def test_pipeline_preserves_partial_evidence_on_stage_failure() -> None:
    """下游失败不得丢失上游已生成的证据。"""

    def capture(context):
        return StageResult(findings=({"kind": "capture", "ok": True},))

    def detect(context):
        raise RuntimeError("probe incompatible")

    executor = PipelineAuditExecutor(
        (
            CallableAuditStage("activation_capture", capture),
            CallableAuditStage("probe_detection", detect),
        )
    )
    evidence = executor.execute(
        _plan("activation_capture", "probe_detection"),
        run_id="run-3",
    )

    assert evidence.status is RunStatus.FAILED
    assert evidence.findings[0]["kind"] == "capture"
    assert evidence.findings[1]["kind"] == "stage_error"
    assert evidence.findings[1]["stage_id"] == "probe_detection"
    assert "probe incompatible" in evidence.limitations[0]


def test_pipeline_rejects_duplicate_plan_stages_before_execution() -> None:
    """重复阶段会破坏指标和状态唯一性，必须在执行前拒绝。"""

    called = False

    def capture(context):
        nonlocal called
        called = True
        return StageResult()

    executor = PipelineAuditExecutor((CallableAuditStage("activation_capture", capture),))
    evidence = executor.execute(
        _plan("activation_capture", "activation_capture"),
        run_id="run-4",
    )

    assert evidence.status is RunStatus.FAILED
    assert not called
    assert "重复阶段" in evidence.findings[0]["message"]

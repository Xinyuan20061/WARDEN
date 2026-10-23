"""审计计划能力和资源预检测试。"""

from warden.application.catalog import ResourceCatalog
from warden.application.compiler import AuditPlanCompiler
from warden.core.domain.enums import AuditMode, RunStatus
from warden.core.domain.models import (
    AuditRequest,
    CapabilityReport,
    CaptureTarget,
    ThreatContract,
)


def _contract() -> ThreatContract:
    return ThreatContract(
        contract_id="case-1",
        scenario_id="demo",
        agent_ids=("sender", "receiver"),
        communication_edges=(("sender", "receiver"),),
        harmful_objective="选择未授权目标",
        benign_objective="选择合规目标",
    )


def test_capture_only_plan_can_be_planned_without_probe() -> None:
    """只采集模式不要求未训练 Probe。"""

    request = AuditRequest(
        request_id="request-1",
        contract_id="case-1",
        model_id="model",
        runtime_id="runtime",
        mode=AuditMode.CAPTURE_ONLY,
        capture_targets=(
            CaptureTarget(target_id="receiver-l1", agent_ids=("receiver",), layer=1),
        ),
    )
    components = (
        CapabilityReport(
            component_id="runtime",
            available=True,
            capabilities=(
                "agent_message_hook",
                "model_invocation_hook",
                "activation_read",
            ),
        ),
        CapabilityReport(
            component_id="optional-benchmark",
            available=False,
            reason="当前请求不依赖该可选组件",
        ),
    )
    plan = AuditPlanCompiler(ResourceCatalog()).compile(
        request,
        _contract(),
        components=components,
    )
    assert plan.status is RunStatus.PLANNED
    assert not plan.blockers


def test_causal_plan_blocks_missing_resources_and_capabilities() -> None:
    """因果审计不能在 Probe 和写入能力缺失时继续。"""

    request = AuditRequest(
        request_id="request-2",
        contract_id="case-1",
        model_id="model",
        runtime_id="runtime",
        mode=AuditMode.CAUSAL_AUDIT,
        capture_targets=(
            CaptureTarget(target_id="receiver-l1", agent_ids=("receiver",), layer=1),
        ),
    )
    components = (
        CapabilityReport(
            component_id="runtime",
            available=True,
            capabilities=("agent_message_hook", "model_invocation_hook", "activation_read"),
        ),
    )
    plan = AuditPlanCompiler(ResourceCatalog()).compile(
        request,
        _contract(),
        components=components,
    )
    assert plan.status is RunStatus.BLOCKED
    assert any("activation_write" in item for item in plan.blockers)
    assert any("未指定 probe" in item for item in plan.blockers)

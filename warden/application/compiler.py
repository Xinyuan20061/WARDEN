"""把威胁契约和方法资源编译为可执行审计计划。"""

from collections.abc import Sequence
from uuid import uuid4

from warden.application.catalog import ResourceCatalog
from warden.core.domain.enums import AuditMode, ResourceState, RunStatus
from warden.core.domain.models import (
    AuditPlan,
    AuditRequest,
    CapabilityReport,
    ThreatContract,
)


class AuditPlanCompiler:
    """在任何模型运行前完成能力、资源和位置预检。"""

    def __init__(self, resources: ResourceCatalog) -> None:
        """保存资源目录；编译器不拥有其中的模型资源。"""

        self._resources = resources

    def compile(
        self,
        request: AuditRequest,
        contract: ThreatContract,
        *,
        components: Sequence[CapabilityReport],
        research_stages: Sequence[str] | None = None,
    ) -> AuditPlan:
        """生成计划；缺失项写入 blockers，不以假数据继续执行。"""

        blockers: list[str] = []
        if request.research_protocol_ref is not None and research_stages is None:
            blockers.append("研究协议与实验臂未在服务端 allowlist 注册")
        required = self._required_capabilities(request.mode)
        available = {
            capability
            for report in components
            if report.available
            for capability in report.capabilities
        }
        missing = sorted(set(required) - available)
        if missing:
            blockers.append("缺少运行能力：" + ", ".join(missing))
        if not request.capture_targets:
            blockers.append("未声明模型相关 capture_targets；WARDEN 不猜测层级映射")
        if request.mode is not AuditMode.CAPTURE_ONLY:
            self._check_resource(request.probe_id, "probe", blockers)
        if request.sae_id is not None:
            self._check_resource(request.sae_id, "sae", blockers)
        stages = ["trace_alignment", "activation_capture"]
        if request.mode is not AuditMode.CAPTURE_ONLY:
            stages.append("probe_detection")
        if request.sae_id is not None:
            stages.append("sae_decomposition")
        if request.mode in {AuditMode.CAUSAL_AUDIT, AuditMode.DEFENSE_EVALUATION}:
            stages.append("causal_attribution")
        if request.mode is AuditMode.DEFENSE_EVALUATION:
            stages.extend(("controlled_intervention", "utility_evaluation"))
        return AuditPlan(
            plan_id=f"plan-{uuid4().hex}",
            request=request,
            threat_contract=contract,
            required_capabilities=required,
            stages=tuple(research_stages) if research_stages is not None else tuple(stages),
            status=RunStatus.BLOCKED if blockers else RunStatus.PLANNED,
            blockers=tuple(blockers),
        )

    def _check_resource(
        self,
        resource_id: str | None,
        kind: str,
        blockers: list[str],
    ) -> None:
        """验证任务所需资源存在、类型正确且已经就绪。"""

        if resource_id is None:
            blockers.append(f"未指定 {kind} 资源")
            return
        resource = self._resources.get(resource_id)
        if resource is None:
            blockers.append(f"找不到 {kind} 资源：{resource_id}")
            return
        if resource.kind != kind:
            blockers.append(f"资源 {resource_id} 类型应为 {kind}，实际为 {resource.kind}")
        elif resource.state is not ResourceState.READY:
            blockers.append(f"资源 {resource_id} 尚未就绪：{resource.state.value}")

    @staticmethod
    def _required_capabilities(mode: AuditMode) -> tuple[str, ...]:
        """返回每种审计模式的最小能力集合。"""

        values = {"agent_message_hook", "model_invocation_hook", "activation_read"}
        if mode in {AuditMode.CAUSAL_AUDIT, AuditMode.DEFENSE_EVALUATION}:
            values.update({"gradient_read", "activation_write", "deterministic_replay"})
        return tuple(sorted(values))

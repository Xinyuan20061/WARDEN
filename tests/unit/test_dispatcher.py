"""参考同步调度器测试。"""

from warden.core.domain.enums import RunStatus
from warden.core.domain.models import AuditPlan, AuditRequest, EvidenceBundle, ThreatContract
from warden.infrastructure.execution import InProcessRunDispatcher


class _SuccessfulExecutor:
    """返回最小合法证据包的测试执行器。"""

    def execute(self, plan: AuditPlan, *, run_id: str) -> EvidenceBundle:
        return EvidenceBundle(
            run_id=run_id,
            plan_id=plan.plan_id,
            status=RunStatus.COMPLETED,
        )


def _plan() -> AuditPlan:
    """构造无阻塞的最小计划。"""

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
        stages=("trace_alignment",),
    )


def test_in_process_dispatcher_preserves_evidence_identity() -> None:
    """调度器不得替换执行器生成的任务与计划标识。"""

    dispatcher = InProcessRunDispatcher(_SuccessfulExecutor())
    run = dispatcher.submit(_plan())
    assert run.status is RunStatus.COMPLETED
    assert run.evidence is not None
    assert run.evidence.run_id == run.run_id
    assert dispatcher.get(run.run_id) == run


def test_in_process_dispatcher_records_executor_failure() -> None:
    """执行异常必须成为可查询的 failed 任务。"""

    class _FailingExecutor:
        def execute(self, plan: AuditPlan, *, run_id: str) -> EvidenceBundle:
            del plan, run_id
            raise RuntimeError("boom")

    run = InProcessRunDispatcher(_FailingExecutor()).submit(_plan())
    assert run.status is RunStatus.FAILED
    assert run.error == "RuntimeError: boom"

"""应用服务的失败关闭运行契约。"""

from warden.application.service import WardenService
from warden.core.domain.enums import RunStatus
from warden.core.domain.models import AuditPlan, AuditRequest, ThreatContract


def test_blocked_plan_creates_traceable_blocked_run() -> None:
    """平台启动阻塞计划时应获得任务记录，而非虚假结果。"""

    service = WardenService()
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
    plan = service.create_plan(request, contract=contract)

    run = service.start_run(plan.plan_id)

    assert isinstance(plan, AuditPlan)
    assert run.status is RunStatus.BLOCKED
    assert run.blockers == plan.blockers
    assert service.get_run(run.run_id) == run
    assert service.list_runs() == (run,)

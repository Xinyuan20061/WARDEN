"""供 CLI、REST API 和 Python SDK 共同调用的应用门面。"""

from collections.abc import Mapping, Sequence
from threading import RLock
from uuid import uuid4

from warden.application.catalog import ResourceCatalog
from warden.application.compiler import AuditPlanCompiler
from warden.core.domain.enums import RunStatus
from warden.core.domain.models import (
    AuditPlan,
    AuditRequest,
    AuditRun,
    CapabilityReport,
    ResourceManifest,
    ThreatContract,
)
from warden.core.ports.runs import (
    BlockedRunStore,
    PersistentPlanIndex,
    PersistentPlanStore,
    RunDispatcher,
)
from warden.core.ports.threat import ThreatContractSource


class WardenService:
    """管理能力发现、资源目录和审计计划，不隐藏执行失败。"""

    def __init__(
        self,
        *,
        resources: ResourceCatalog | None = None,
        threat_source: ThreatContractSource | None = None,
        components: Sequence[CapabilityReport] = (),
        dispatcher: RunDispatcher | None = None,
        research_stages: Mapping[tuple[str, str], Sequence[str]] | None = None,
        research_contracts: Mapping[tuple[str, str], Mapping] | None = None,
    ) -> None:
        """初始化应用服务。

        参数：
            resources: 已发现 Probe、SAE 等资源的目录。
            threat_source: 可选威胁契约来源，例如 FRACTAL-Bench 数据集。
            components: Runtime、Activation Backend 等组件能力报告。
            dispatcher: 可选运行调度器，由部署层决定同步、队列或分布式执行。
            research_stages: 服务端冻结的 (协议引用, 实验臂引用) 到阶段标识白名单。
            research_contracts: 与白名单中阶段绑定的脱敏描述；复制后供只读查询。
        """

        self.resources = resources or ResourceCatalog()
        self.threat_source = threat_source
        self.dispatcher = dispatcher
        self._research_stages = {
            key: tuple(value) for key, value in (research_stages or {}).items()
        }
        for key, stages in self._research_stages.items():
            if (
                len(key) != 2
                or any(not isinstance(x, str) or not x.strip() for x in key)
                or not stages
                or len(set(stages)) != len(stages)
                or any(not isinstance(x, str) or not x.strip() for x in stages)
            ):
                raise ValueError("研究协议/实验臂映射必须包含唯一非空阶段")
        self._components = {item.component_id: item for item in components}
        self._compiler = AuditPlanCompiler(self.resources)
        self._plans: dict[str, AuditPlan] = {}
        self._local_runs: dict[str, AuditRun] = {}
        self._lock = RLock()
        from copy import deepcopy

        self._research_contracts = deepcopy(dict(research_contracts or {}))
        if any(
            key not in self._research_stages
            or description["stage_id"] not in self._research_stages[key]
            for key, description in self._research_contracts.items()
        ):
            raise ValueError("公共执行配置必须绑定真实阶段")

    def research_contract(self, protocol_ref, arm_id):
        """读取冻结目标副本；未知协议返回 None，不执行模型、不改变计划。"""
        from copy import deepcopy

        return deepcopy(self._research_contracts.get((protocol_ref, arm_id)))

    def capabilities(self) -> tuple[CapabilityReport, ...]:
        """按组件标识返回启动时完成的能力发现结果。"""

        return tuple(self._components[key] for key in sorted(self._components))

    def list_resources(self, *, kind: str | None = None) -> tuple[ResourceManifest, ...]:
        """返回平台可以展示的资源清单。"""

        return self.resources.list(kind=kind)

    def list_contracts(self) -> tuple[str, ...]:
        """返回当前威胁来源中的契约标识。"""

        if self.threat_source is None:
            return ()
        return tuple(self.threat_source.list_contracts())

    def create_plan(
        self,
        request: AuditRequest,
        *,
        contract: ThreatContract | None = None,
    ) -> AuditPlan:
        """编译并登记审计计划；返回 blocked 计划以解释缺失资源。"""

        resolved = contract or self._load_contract(request.contract_id)
        plan = self._compiler.compile(
            request,
            resolved,
            components=self.capabilities(),
            research_stages=self._research_stages.get(
                (request.research_protocol_ref, request.study_arm_ref)
            ),
        )
        with self._lock:
            self._plans[plan.plan_id] = plan
        if isinstance(self.dispatcher, PersistentPlanStore):
            self.dispatcher.save_plan(plan)
        return plan

    def get_plan(self, plan_id: str) -> AuditPlan | None:
        """返回已登记计划；未知标识返回空。"""

        with self._lock:
            plan = self._plans.get(plan_id)
        if plan is None and isinstance(self.dispatcher, PersistentPlanStore):
            return self.dispatcher.get_plan(plan_id)
        return plan

    def list_plans(self) -> tuple[AuditPlan, ...]:
        """按创建时间返回计划快照。"""

        with self._lock:
            values = dict(self._plans)
        if isinstance(self.dispatcher, PersistentPlanIndex):
            values.update({item.plan_id: item for item in self.dispatcher.list_plans()})
        return tuple(sorted(values.values(), key=lambda item: item.created_at))

    def start_run(self, plan_id: str) -> AuditRun:
        """提交已登记计划；不满足执行条件时返回 blocked 快照。"""

        plan = self.get_plan(plan_id)
        if plan is None:
            raise KeyError(f"找不到审计计划：{plan_id}")
        if plan.status is RunStatus.BLOCKED:
            if isinstance(self.dispatcher, BlockedRunStore):
                return self.dispatcher.persist_blocked(plan)
            return self._record_blocked_run(plan_id, plan.blockers)
        if self.dispatcher is None:
            return self._record_blocked_run(
                plan_id,
                ("未配置 RunDispatcher；计划已通过预检但尚无法执行",),
            )
        run = self.dispatcher.submit(plan)
        if run.plan_id != plan_id:
            original = self.get_plan(run.plan_id)
            if original is None or original.request != plan.request:
                raise RuntimeError("RunDispatcher 返回了不属于该请求的任务")
        return run

    def get_run(self, run_id: str) -> AuditRun | None:
        """返回本地阻塞记录或调度器中的最新快照。"""

        with self._lock:
            local = self._local_runs.get(run_id)
        if local is not None or self.dispatcher is None:
            return local
        return self.dispatcher.get(run_id)

    def list_runs(self) -> tuple[AuditRun, ...]:
        """合并本地阻塞记录与调度器任务。"""

        with self._lock:
            values = list(self._local_runs.values())
        if self.dispatcher is not None:
            values.extend(self.dispatcher.list())
        unique = {item.run_id: item for item in values}
        return tuple(sorted(unique.values(), key=lambda item: item.created_at))

    def _record_blocked_run(self, plan_id: str, blockers: Sequence[str]) -> AuditRun:
        """登记一条可被平台查询的失败关闭记录。"""

        run = AuditRun(
            run_id=f"run-{uuid4().hex}",
            plan_id=plan_id,
            status=RunStatus.BLOCKED,
            blockers=tuple(blockers),
        )
        with self._lock:
            self._local_runs[run.run_id] = run
        return run

    def _load_contract(self, contract_id: str) -> ThreatContract:
        """从已配置来源加载契约，并明确报告缺失来源。"""

        if self.threat_source is None:
            raise RuntimeError("尚未配置 ThreatContractSource")
        return self.threat_source.load(contract_id)

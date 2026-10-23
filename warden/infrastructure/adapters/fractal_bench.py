"""把 FRACTAL-Bench 数据集映射为 WARDEN 威胁契约。"""

from __future__ import annotations

from pathlib import Path

from warden.core.domain.models import CapabilityReport, ThreatContract
from warden.infrastructure.adapters.dependencies import dependency_report


class FractalDatasetThreatSource:
    """从一个冻结的 FRACTAL-Bench JSON 数据集提供威胁契约。"""

    def __init__(self, dataset_path: Path) -> None:
        """初始化来源。

        参数：
            dataset_path: `dataset.json` 文件或包含该文件的目录。

        说明：
            构造器只保存路径；首次查询时才导入 FRACTAL-Bench 并读取数据。
        """

        self.dataset_path = Path(dataset_path)
        self._instances: dict[str, object] | None = None

    def capabilities(self) -> CapabilityReport:
        """返回 FRACTAL-Bench 依赖和数据集可用状态。"""

        report = dependency_report(
            component_id="fractal-bench",
            package_name="fractal-bench",
            import_name="fractal_bench",
            capabilities=("threat_contract", "paired_counterfactual", "structural_truth"),
        )
        if not report.available:
            return report
        source = (
            self.dataset_path
            if self.dataset_path.is_file()
            else self.dataset_path / "dataset.json"
        )
        if not source.is_file():
            return CapabilityReport(
                component_id="fractal-bench",
                available=False,
                reason=f"找不到数据集：{source}",
                metadata=report.metadata,
            )
        return report

    def list_contracts(self) -> tuple[str, ...]:
        """返回数据集中全部实例标识。"""

        self._ensure_loaded()
        assert self._instances is not None
        return tuple(sorted(self._instances))

    def load(self, contract_id: str) -> ThreatContract:
        """把一个 BenchmarkInstance 转换为稳定威胁契约。"""

        self._ensure_loaded()
        assert self._instances is not None
        try:
            instance = self._instances[contract_id]
        except KeyError as exc:
            raise KeyError(f"FRACTAL-Bench 中不存在契约：{contract_id}") from exc
        threat = instance.threat
        return ThreatContract(
            contract_id=instance.instance_id,
            scenario_id=instance.scenario_name,
            agent_ids=instance.agent_ids,
            communication_edges=tuple((edge.source, edge.target) for edge in instance.edges),
            harmful_objective=f"选择协调目标 {instance.coordinated_target_id}",
            benign_objective=f"选择正常最优目标 {instance.benign_optimum_id}",
            capture_points=instance.capture_points,
            truth={
                "arm": instance.arm.value,
                "case_family": instance.case_family,
                "coordinated_target_id": instance.coordinated_target_id,
                "benign_optimum_id": instance.benign_optimum_id,
                "counterfactual": instance.counterfactual.to_dict(),
            },
            metadata={
                "schema_version": instance.schema_version,
                "secret_mode": threat.secret_mode.value,
                "objective_mode": threat.objective_mode.value,
                "secret_access": threat.secret_access.to_dict(),
                "objective_access": threat.objective_access.to_dict(),
                "awareness_semantics": threat.awareness_semantics,
            },
        )

    def _ensure_loaded(self) -> None:
        """惰性读取数据集并建立实例索引。"""

        if self._instances is not None:
            return
        status = self.capabilities()
        if not status.available:
            raise RuntimeError(status.reason or "FRACTAL-Bench 不可用")
        from fractal_bench.storage import JsonDatasetStore

        dataset = JsonDatasetStore().read(self.dataset_path)
        self._instances = {item.instance_id: item for item in dataset.instances}


def build_stegopot_experiment_plan(
    *,
    scenario_id: str,
    families: int,
    seed: int,
    policy_type: str,
    policy_config: dict,
    max_rounds: int = 4,
):
    """使用 FRACTAL-Bench 官方适配器生成 StegoPot ExperimentPlan。"""

    try:
        from fractal_bench.adapters.stegopot.provider import (
            FractalScenarioConfig,
            FractalScenarioProvider,
        )
    except ImportError as exc:
        raise RuntimeError("需要先安装 vendor/fractal-bench 与 vendor/stegopot") from exc
    config = FractalScenarioConfig(
        scenario_id=scenario_id,
        families=families,
        policy_type=policy_type,
        policy_config=dict(policy_config),
        max_rounds=max_rounds,
    )
    return FractalScenarioProvider(config).plan(seed)

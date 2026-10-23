"""FRACTAL-Bench 威胁契约适配测试。"""

import pytest

pytest.importorskip("fractal_bench")

from fractal_bench.scenarios.catalog import get_scenario_entry  # noqa: E402
from fractal_bench.storage import JsonDatasetStore  # noqa: E402

from warden.infrastructure.adapters.fractal_bench import (  # noqa: E402
    FractalDatasetThreatSource,
)


def test_fractal_dataset_maps_to_warden_contract(tmp_path) -> None:
    """基准结构真值必须保留到 WARDEN 契约。"""

    dataset = get_scenario_entry("release_review").generator_factory().generate(
        families=1,
        seed=17,
    )
    path = JsonDatasetStore().write(dataset, tmp_path / "fractal")
    source = FractalDatasetThreatSource(path)
    contract_ids = source.list_contracts()
    contract = source.load(contract_ids[0])
    assert len(contract_ids) == 8
    assert contract.agent_ids
    assert contract.communication_edges
    assert contract.metadata["secret_mode"] in {"centered", "distributed"}

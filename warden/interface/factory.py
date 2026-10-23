"""本地开发和 API 服务使用的默认组合入口。"""

from __future__ import annotations

import os
from pathlib import Path

from warden.application.catalog import ResourceCatalog
from warden.application.service import WardenService
from warden.core.domain.models import CapabilityReport
from warden.infrastructure.adapters.dependencies import dependency_report
from warden.infrastructure.adapters.fractal_bench import FractalDatasetThreatSource
from warden.infrastructure.storage.resources import discover_resource_manifests


def build_default_service(project_root: Path | None = None) -> WardenService:
    """构建不加载模型、不下载资源的默认服务。"""

    root = Path(project_root or Path.cwd()).resolve()
    probe_root = Path(os.getenv("WARDEN_PROBE_ROOT", root / "artifacts" / "probes"))
    sae_root = Path(os.getenv("WARDEN_SAE_ROOT", root / "artifacts" / "sae"))
    resources = ResourceCatalog(discover_resource_manifests(probe_root, sae_root))
    components = [
        dependency_report(
            component_id="stegopot.package",
            package_name="stegopot",
            import_name="stegopot",
            capabilities=("stegopot_integration",),
        ),
        dependency_report(
            component_id="fractal-bench.package",
            package_name="fractal-bench",
            import_name="fractal_bench",
            capabilities=("fractal_integration",),
        ),
        CapabilityReport(
            component_id="agent.runtime",
            available=False,
            reason="尚未通过 RuntimeAdapter 注入多智能体运行时",
        ),
        CapabilityReport(
            component_id="activation.backend",
            available=False,
            reason="尚未加载白盒模型和 StegoPot ModelRuntime",
        ),
    ]
    dataset_path = os.getenv("WARDEN_FRACTAL_DATASET")
    threat_source = None
    if dataset_path:
        threat_source = FractalDatasetThreatSource(Path(dataset_path))
        components.append(threat_source.capabilities())
    return WardenService(
        resources=resources,
        threat_source=threat_source,
        components=components,
    )

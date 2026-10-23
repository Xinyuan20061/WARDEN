"""测试平台依赖的 `/v1` 接口契约。"""

from warden.application.service import WardenService
from warden.interface.api.app import create_app


def test_public_paths_are_versioned_and_documented() -> None:
    """平台使用的端点必须出现在生成的 OpenAPI 合同中。"""

    schema = create_app(WardenService()).openapi()
    paths = set(schema["paths"])
    assert "/v1/health" in paths
    assert "/v1/capabilities" in paths
    assert "/v1/resources" in paths
    assert "/v1/contracts" in paths
    assert "/v1/audit-plans" in paths
    assert "/v1/audit-plans/{plan_id}" in paths
    assert "/v1/runs" in paths
    assert "/v1/runs/{run_id}" in paths


def test_openapi_uses_project_version() -> None:
    """API 文档版本与 Python 包版本保持一致。"""

    from warden import __version__

    schema = create_app(WardenService()).openapi()
    assert schema["info"]["version"] == __version__

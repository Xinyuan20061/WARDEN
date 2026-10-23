"""不触发资源加载的上游依赖发现。"""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

from warden.core.domain.models import CapabilityReport


def dependency_report(
    *,
    component_id: str,
    package_name: str,
    import_name: str,
    capabilities: tuple[str, ...],
) -> CapabilityReport:
    """检查包是否可导入并返回版本，不下载模型或访问网络。"""

    try:
        import_module(import_name)
        try:
            installed_version = version(package_name)
        except PackageNotFoundError:
            installed_version = "source-checkout"
    except Exception as exc:
        return CapabilityReport(
            component_id=component_id,
            available=False,
            reason=f"{type(exc).__name__}: {exc}",
            metadata={"package": package_name},
        )
    return CapabilityReport(
        component_id=component_id,
        available=True,
        capabilities=capabilities,
        metadata={"package": package_name, "version": installed_version},
    )

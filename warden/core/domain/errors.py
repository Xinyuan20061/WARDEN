"""WARDEN 可由接口层稳定映射的领域异常。"""


class WardenError(RuntimeError):
    """全部可预期 WARDEN 错误的基类。"""


class ConfigurationError(WardenError):
    """配置或公开契约不合法。"""


class CapabilityError(WardenError):
    """运行时不具备审计计划需要的能力。"""


class ResourceUnavailableError(WardenError):
    """Probe、SAE 或其他声明资源尚未就绪。"""


class ArtifactIntegrityError(WardenError):
    """工件内容与清单中的完整性信息不一致。"""

"""Probe、SAE 和其他版本化资源的内存目录。"""

from collections.abc import Sequence
from threading import RLock

from warden.core.domain.models import ResourceManifest


class ResourceCatalog:
    """提供线程安全、拒绝覆盖的资源清单索引。"""

    def __init__(self, resources: Sequence[ResourceManifest] = ()) -> None:
        """初始化目录。

        参数：
            resources: 启动时已发现并验证的资源清单。
        """

        self._resources: dict[str, ResourceManifest] = {}
        self._lock = RLock()
        for resource in resources:
            self.register(resource)

    def register(self, resource: ResourceManifest) -> None:
        """登记资源；同一标识只能登记完全相同的清单。"""

        with self._lock:
            current = self._resources.get(resource.resource_id)
            if current is not None and current != resource:
                raise ValueError(f"资源 ID 已被不同清单占用：{resource.resource_id}")
            self._resources[resource.resource_id] = resource

    def get(self, resource_id: str) -> ResourceManifest | None:
        """返回资源清单；未知标识返回空。"""

        with self._lock:
            return self._resources.get(resource_id)

    def list(self, *, kind: str | None = None) -> tuple[ResourceManifest, ...]:
        """按稳定顺序返回全部资源或指定类型资源。"""

        with self._lock:
            values = tuple(self._resources.values())
        if kind is not None:
            values = tuple(item for item in values if item.kind == kind)
        return tuple(sorted(values, key=lambda item: item.resource_id))

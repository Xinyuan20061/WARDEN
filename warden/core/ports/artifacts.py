"""审计工件存储端口。"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from warden.core.domain.models import ArtifactRef


class ArtifactRepository(Protocol):
    """保存不可变工件并通过内容哈希寻址。"""

    def put_bytes(
        self,
        kind: str,
        content: bytes,
        *,
        media_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        """写入字节工件并返回引用。"""
        ...

    def put_file(
        self,
        kind: str,
        source: Path,
        *,
        media_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        """复制文件并返回引用。"""
        ...

    def open(self, artifact_id: str) -> BinaryIO:
        """以二进制只读方式打开已登记工件。"""
        ...


class ManifestRepository(Protocol):
    """读写不含权重的 JSON 资源清单。"""

    def write_manifest(self, name: str, payload: Mapping[str, Any]) -> Path:
        """原子写入清单并返回路径。"""
        ...

    def read_manifest(self, name: str) -> Mapping[str, Any]:
        """读取并校验清单根节点。"""
        ...

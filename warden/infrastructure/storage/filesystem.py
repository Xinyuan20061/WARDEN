"""内容寻址、原子写入的本地文件工件仓库。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, BinaryIO

from warden.core.domain.models import ArtifactRef


class FileArtifactRepository:
    """把审计工件保存在调用方指定目录并生成不可变引用。"""

    def __init__(self, root: Path) -> None:
        """初始化仓库。

        参数：
            root: WARDEN 独占的工件根目录；写入时自动创建。
        """

        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        kind: str,
        content: bytes,
        *,
        media_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        """按 SHA-256 写入字节工件；相同内容复用已有文件。"""

        digest = sha256(content).hexdigest()
        artifact_id = f"{_safe_kind(kind)}-{digest}"
        directory = self.root / _safe_kind(kind) / digest[:2]
        directory.mkdir(parents=True, exist_ok=True)
        payload_path = directory / f"{digest}.bin"
        if not payload_path.exists():
            _write_bytes_atomic(content, payload_path)
        manifest_path = directory / f"{digest}.json"
        manifest = {
            "artifact_id": artifact_id,
            "kind": kind,
            "uri": payload_path.resolve().as_uri(),
            "content_hash": digest,
            "media_type": media_type,
            "size_bytes": len(content),
            "metadata": dict(metadata or {}),
        }
        if not manifest_path.exists():
            _write_json_atomic(manifest, manifest_path)
        return ArtifactRef(**manifest)

    def put_file(
        self,
        kind: str,
        source: Path,
        *,
        media_type: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        """读取文件并按内容保存；目录必须由更高层先打包。"""

        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(f"工件源文件不存在：{source}")
        return self.put_bytes(
            kind,
            source.read_bytes(),
            media_type=media_type,
            metadata=metadata,
        )

    def open(self, artifact_id: str) -> BinaryIO:
        """通过工件标识打开已登记内容。"""

        kind, separator, prefix = artifact_id.rpartition("-")
        if not separator or len(prefix) != 64:
            raise ValueError("artifact_id 格式无效")
        payload = self.root / kind / prefix[:2] / f"{prefix}.bin"
        if not payload.is_file():
            raise FileNotFoundError(f"找不到工件：{artifact_id}")
        return payload.open("rb")


def _safe_kind(value: str) -> str:
    """限制工件类型为安全目录名。"""

    normalized = value.strip().lower().replace("_", "-")
    if not normalized or any(not (char.isalnum() or char == "-") for char in normalized):
        raise ValueError("kind 只能包含字母、数字、连字符或下划线")
    return normalized


def _write_bytes_atomic(content: bytes, destination: Path) -> None:
    """在目标目录写临时文件后原子替换。"""

    with NamedTemporaryFile(
        "wb",
        dir=destination.parent,
        prefix=destination.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(destination)


def _write_json_atomic(payload: Mapping[str, Any], destination: Path) -> None:
    """原子写入规范 JSON。"""

    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    _write_bytes_atomic((content + "\n").encode("utf-8"), destination)

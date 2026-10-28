"""只下载部署者明确公开的工件，拒绝任意 URI 转发。"""

from collections.abc import Mapping
from hashlib import sha256

from warden.core.domain.models import ArtifactRef
from warden.core.ports.artifacts import ArtifactRepository


class ArtifactGateway:
    """受控下载适配器。

    参数：
        repository: 原工件仓库，不转移所有权。
        references: 部署者审批的 ID 到引用映射；不得包含 activation/训练真值。
        max_bytes: 单次下载字节上限。
    """

    def __init__(self, repository: ArtifactRepository, references: Mapping[str, ArtifactRef],
                 *, max_bytes: int = 1024 * 1024) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes 必须为正数")
        if any(ref.kind != "public-summary" or key != ref.artifact_id
               for key, ref in references.items()):
            raise ValueError("网关只允许已审批的 public-summary 工件")
        self._repository = repository
        self._references = dict(references)
        self._max_bytes = max_bytes

    def read(self, artifact_id: str) -> bytes:
        """读取白名单 artifact_id；验证大小和哈希，越权或损坏明确失败。"""
        if artifact_id not in self._references:
            raise KeyError("工件未授权")
        with self._repository.open(artifact_id) as handle:
            content = handle.read(self._max_bytes + 1)
        if len(content) > self._max_bytes:
            raise ValueError("工件超过下载上限")
        if sha256(content).hexdigest() != self._references[artifact_id].content_hash:
            raise ValueError("工件哈希不匹配")
        return content

"""工件路径、哈希和公开下载白名单边界。"""

import pytest

from warden.infrastructure.storage.filesystem import FileArtifactRepository
from warden.infrastructure.storage.gateway import ArtifactGateway


def test_gateway_only_exposes_approved_summary_and_verifies_hash(tmp_path):
    store = FileArtifactRepository(tmp_path)
    ref = store.put_bytes("public-summary", b"{}", media_type="application/json")
    gateway = ArtifactGateway(store, {ref.artifact_id: ref})
    assert gateway.read(ref.artifact_id) == b"{}"
    with pytest.raises(KeyError):
        gateway.read("file:///private")
    with pytest.raises(ValueError):
        store.open("../" + ref.artifact_id)
    path = next((tmp_path / "public-summary").rglob("*.bin"))
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="哈希"):
        gateway.read(ref.artifact_id)

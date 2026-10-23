"""内容寻址工件存储测试。"""

from warden.infrastructure.storage.filesystem import FileArtifactRepository


def test_identical_content_reuses_artifact_identity(tmp_path) -> None:
    """同类相同内容必须得到相同工件标识。"""

    repository = FileArtifactRepository(tmp_path)
    first = repository.put_bytes("activation", b"value", media_type="application/octet-stream")
    second = repository.put_bytes("activation", b"value", media_type="application/octet-stream")
    assert first.artifact_id == second.artifact_id
    with repository.open(first.artifact_id) as handle:
        assert handle.read() == b"value"

"""核心领域对象测试。"""

import pytest

from warden.core.domain.enums import ResourceState
from warden.core.domain.models import (
    ActivationCoordinate,
    ArtifactRef,
    ResourceManifest,
    ThreatContract,
)


def test_threat_contract_rejects_unknown_edge_agent() -> None:
    """通信边不能引用契约外的 Agent。"""

    with pytest.raises(ValueError, match="已声明 Agent"):
        ThreatContract(
            contract_id="case-1",
            scenario_id="demo",
            agent_ids=("a", "b"),
            communication_edges=(("a", "c"),),
            harmful_objective="执行未授权目标",
            benign_objective="完成公开任务",
        )


def test_ready_resource_requires_artifact() -> None:
    """没有权重引用的资源不能标记为 ready。"""

    with pytest.raises(ValueError, match="必须引用 artifact"):
        ResourceManifest(
            resource_id="probe-v1",
            kind="probe",
            version="1",
            state=ResourceState.READY,
            backend="linear",
        )


def test_activation_coordinate_requires_location() -> None:
    """WARDEN 不允许无模型位置的 Activation 证据。"""

    with pytest.raises(ValueError, match="module 或 layer"):
        ActivationCoordinate(
            run_id="run",
            agent_id="agent",
            message_id="message",
            invocation_id="invocation",
            model_id="model",
        )


def test_artifact_ref_accepts_content_address() -> None:
    """工件引用保存完整性和媒体类型。"""

    artifact = ArtifactRef(
        artifact_id="probe-1234",
        kind="probe",
        uri="file:///tmp/probe",
        content_hash="a" * 64,
    )
    assert artifact.kind == "probe"

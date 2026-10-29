"""研究写操作授权、公开投影与旧接口兼容。"""

from fastapi.testclient import TestClient

from warden.application.service import WardenService
from warden.core.domain.models import CapabilityReport, ThreatContract
from warden.infrastructure.execution.sqlite import SQLiteRunDispatcher
from warden.interface.api.app import create_app


class _Source:
    def list_contracts(self):
        return ("c",)

    def load(self, _key):
        return ThreatContract("c", "s", ("receiver",), (), "h", "b",
                              truth={"secret": "PRIVATE-CANARY"},
                              metadata={"private": "METADATA-CANARY"})


def test_research_requires_token_and_never_returns_truth():
    service = WardenService(threat_source=_Source())
    client = TestClient(create_app(service, research_token="test-only-token"))
    body = {"request_id": "r", "contract_id": "c", "model_id": "m", "runtime_id": "rt",
            "research_protocol_ref": "p", "study_arm_ref": "baseline"}
    assert client.post("/v1/audit-plans", json=body).status_code == 401
    response = client.post("/v1/audit-plans", json=body,
                           headers={"Authorization": "Bearer test-only-token"})
    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert "PRIVATE-CANARY" not in response.text
    assert "METADATA-CANARY" not in response.text
    assert client.post("/v1/runs", json={"plan_id": response.json()["plan_id"]}).status_code == 401
    body.pop("research_protocol_ref")
    body.pop("study_arm_ref")
    assert client.post("/v1/audit-plans", json=body).status_code == 200


def test_artifact_download_disabled_without_authorized_gateway():
    client = TestClient(create_app(WardenService()))
    assert client.get("/v1/artifacts/example/content").status_code == 403


def test_binary_artifact_contract_matches_http_response():
    client = TestClient(create_app(WardenService(), research_token="token",
                                  artifact_reader=lambda _: b"verified-summary"))
    operation = client.get("/openapi.json").json()["paths"][
        "/v1/artifacts/{artifact_id}/content"]["get"]
    assert set(operation["responses"]["200"]["content"]) == {"application/octet-stream"}
    response = client.get("/v1/artifacts/example/content",
                          headers={"Authorization": "Bearer token"})
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.content == b"verified-summary"


def test_research_run_replay_and_conflict_http_status(tmp_path):
    queue = SQLiteRunDispatcher(tmp_path / "queue.sqlite", None)
    service = WardenService(
        threat_source=_Source(), dispatcher=queue,
        components=(CapabilityReport("rt", True, ("agent_message_hook", "model_invocation_hook",
                                                  "activation_read")),),
        research_stages={("protocol", "baseline"): ("whitebox_collect",)},
    )
    client = TestClient(create_app(service, research_token="token"))
    headers = {"Authorization": "Bearer token"}
    body = {"request_id": "r", "contract_id": "c", "model_id": "m", "runtime_id": "rt",
            "mode": "capture_only", "research_protocol_ref": "protocol",
            "study_arm_ref": "baseline", "capture_targets": [
                {"target_id": "x", "agent_ids": ["receiver"], "layer": 1}]}

    def submit(payload):
        plan = client.post("/v1/audit-plans", json=payload, headers=headers).json()
        return client.post("/v1/runs", json={"plan_id": plan["plan_id"]}, headers=headers)

    first = submit(body)
    replay = submit(body)
    assert first.status_code == replay.status_code == 200
    assert first.json()["run_id"] == replay.json()["run_id"]
    assert submit({**body, "model_id": "changed"}).status_code == 409

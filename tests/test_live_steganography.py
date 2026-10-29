"""公开事件与冻结配置的合约测试；合成单测数据不充当模型实测结果。"""

import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from warden.infrastructure.adapters.live_steganography import PublicEventLog, load_live_config
from warden.interface.live_research import configure_live_entry


def test_public_events_namespace_messages_and_hide_secret_and_content():
    sink = PublicEventLog("run", "study", "message_block", "a" * 64)
    sink.case_id = "family-1"
    message = {
        "sender": "sender",
        "recipient": "receiver",
        "message_id": "m1",
        "content": "PRIVATE-SECRET-TEXT",
        "round_index": 0,
    }
    sink.emit({"kind": "runtime.observation", "actor": "sender", "data": {"secret_bits": "1"}})
    sink.emit({"kind": "runtime.routed", "data": {"message": message}})
    sink.emit(
        {
            "kind": "channel.transformed",
            "data": {"input": message, "output": None, "component": "block"},
        }
    )
    sink.case_id = "family-2"
    sink.emit({"kind": "runtime.routed", "data": {"message": message}})
    assert [e["seq"] for e in sink.events] == [1, 2, 3, 4]
    assert sink.events[1]["message_id"] != sink.events[3]["message_id"]
    assert sink.events[2]["type"] == "message_blocked"
    assert not any(e["type"] == "message_delivered" for e in sink.events)
    public = json.dumps(sink.events)
    assert "PRIVATE-SECRET-TEXT" not in public and "secret_bits" not in public
    assert sha256(message["content"].encode()).hexdigest() in public


def test_literal_replace_without_match_is_not_a_replacement_fact():
    sink = PublicEventLog("run", "study", "message_replace", "a" * 64)
    msg = {"content": "same"}
    sink.emit({"kind": "channel.transformed", "data": {"input": msg, "output": msg}})
    assert sink.events[0]["type"] == "intervention_applied"
    assert sink.events[0]["data"]["mode"] == "literal_match_no_change"


def test_multi_agent_channel_identity_comes_from_actual_endpoints():
    sink = PublicEventLog("run", "study", "baseline", "a" * 64)
    message = {
        "sender": "planner",
        "recipient": "data_agent",
        "message_id": "m1",
        "content": "READY",
        "round_index": 0,
    }
    sink.emit({"kind": "runtime.routed", "data": {"message": message}})
    assert sink.events[0]["channel_id"] == "planner-data_agent"
    assert sink.events[0]["source_agent_id"] == "planner"
    assert sink.events[0]["target_agent_id"] == "data_agent"


def config_fixture(tmp_path):
    cases = [
        {
            "family_id": f"family-{i}",
            "secret_bit": str(i % 2),
            "public_task": "2+3?",
            "expected_answer": "5",
        }
        for i in range(6)
    ]
    data = tmp_path / "cases.json"
    data.write_text(
        json.dumps({"schema_version": "warden.synthetic-secret-cases/1", "cases": cases})
    )
    split = {
        "dataset_sha256": sha256(data.read_bytes()).hexdigest(),
        "assignments": {
            f"family-{i}": ["train", "train", "validation", "validation", "test", "test"][i]
            for i in range(6)
        },
    }
    (tmp_path / "split.json").write_text(json.dumps(split))
    config = {
        "schema_version": "warden.live-stego-config/1",
        "model_id": "local-small",
        "model": {
            "model_path": "model",
            "revision": "fixed-revision",
            "local_files_only": True,
            "trust_remote_code": False,
        },
        "dataset_path": "cases.json",
        "split_path": "split.json",
        "seed": 7,
        "layer": 12,
        "max_new_tokens": 8,
    }
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(config))
    return path, config


def test_frozen_configuration_rejects_split_tamper_and_unregistered_options(tmp_path):
    path, config = config_fixture(tmp_path)
    _, _, cases, splits = load_live_config(path)
    assert len(cases) == 6 and len(splits["assignments"]) == 6
    config["arbitrary_model_url"] = "https://untrusted.invalid"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="配置字段"):
        load_live_config(path)
    del config["arbitrary_model_url"]
    path.write_text(json.dumps(config))
    (tmp_path / "cases.json").write_text("{}")
    with pytest.raises(ValueError, match="哈希"):
        load_live_config(path)


def test_registered_stage_rejects_wrong_activation_component_before_model_execution(tmp_path):
    path, _ = config_fixture(tmp_path)
    stage, _, _, contract = configure_live_entry(
        {"config": path.name, "arm_ref": "baseline", "protocol_ref": "frozen"},
        tmp_path / "registry.json",
        tmp_path / "artifacts",
    )
    target = SimpleNamespace(
        layer=12, component="resid_pre", agent_ids=["receiver"], token_policy="last_token"
    )
    request = SimpleNamespace(
        model_id="local-small",
        study_arm_ref="baseline",
        research_protocol_ref="frozen",
        mode=SimpleNamespace(value="capture_only"),
        capture_targets=[target],
    )
    context = SimpleNamespace(plan=SimpleNamespace(request=request, threat_contract=contract))
    with pytest.raises(ValueError, match="坐标"):
        stage.execute(context)


def test_frozen_target_api_is_bound_to_registered_stage_and_contains_no_local_paths(tmp_path):
    from fastapi.testclient import TestClient

    from warden.application.executor import PipelineAuditExecutor
    from warden.application.service import WardenService
    from warden.interface.api.app import create_app

    path, _ = config_fixture(tmp_path)
    stage, key, _, _ = configure_live_entry(
        {"config": path.name, "arm_ref": "leace", "protocol_ref": "frozen"},
        tmp_path / "registry.json",
        tmp_path / "artifacts",
    )
    executor = PipelineAuditExecutor([stage])
    service = WardenService(
        research_stages={key: (stage.stage_id,)}, research_contracts=executor.research_contracts
    )
    with TestClient(create_app(service)) as client:
        response = client.get("/v1/research-protocols/frozen/arms/leace")
        assert response.status_code == 200
        data = response.json()
        assert data["target_ref"] == "activation:receiver:L12:resid_post:token=-1"
        assert data["stage_id"] == stage.stage_id and data["available"] is False
        assert str(tmp_path) not in response.text and "model_path" not in response.text
        assert client.get("/v1/research-protocols/unknown/arms/leace").status_code == 404
    changed = service.research_contract(*key)
    changed["target"]["layer"] = 0
    assert service.research_contract(*key)["target"]["layer"] == 12

"""S 轨道注册组合根：只把服务端冻结引用接入既有 PipelineAuditExecutor。"""

from __future__ import annotations

import json
from functools import lru_cache
from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path

from warden.application.executor import AuditStageFailure, CallableAuditStage, StageResult
from warden.core.domain.models import CapabilityReport, ThreatContract, utc_now
from warden.infrastructure.adapters.live_steganography import (
    METHODS,
    digest_file,
    load_live_config,
    run_live_experiment,
)
from warden.infrastructure.storage.filesystem import FileArtifactRepository
from warden.infrastructure.storage.gateway import ArtifactGateway


@lru_cache(maxsize=64)
def _frozen_model_digest(path, size, modified_ns):
    """缓存按文件状态区分；模型变化会改变阶段标识，不能复用旧计划。"""
    return digest_file(Path(path))


def _model_hashes(model):
    root = Path(model.model_path)
    files = [root / "model.safetensors", root / "config.json"]
    tokenizer = Path(model.tokenizer_path or model.model_path)
    files.extend(tokenizer / name for name in ("tokenizer.json", "tokenizer_config.json"))
    return {
        p.name: _frozen_model_digest(str(p), p.stat().st_size, p.stat().st_mtime_ns)
        for p in files
        if p.is_file()
    }


def configure_live_entry(entry, source, artifact_root):
    """返回阶段、映射、能力和 S 契约；配置错误失败关闭，不加载模型。

    参数来自本地部署注册表，不接受用户路径。返回阶段只在独立 Worker 消费时执行。
    """
    path = (source.parent / entry["config"]).resolve()
    config, model, _, _ = load_live_config(path)
    arm = entry["arm_ref"]
    if arm not in METHODS:
        raise ValueError("S 注册表包含未支持实验臂")
    config_hash = digest_file(path)
    data_hash = digest_file(config["dataset_path"])
    split_hash = digest_file(config["split_path"])
    code_hash = digest_file(Path(__file__))
    from warden.infrastructure.adapters import live_steganography

    adapter_hash = digest_file(Path(live_steganography.__file__))
    model_hashes = _model_hashes(model)
    stage_id = (
        "live-stego-"
        + sha256(
            (
                config_hash
                + data_hash
                + split_hash
                + code_hash
                + adapter_hash
                + arm
                + json.dumps(model_hashes, sort_keys=True)
            ).encode()
        ).hexdigest()
    )
    contract_id = "live-stego-" + data_hash
    ready = Path(model.model_path, "model.safetensors").is_file() and all(
        find_spec(name) is not None
        for name in ("torch", "transformers", "numpy", "sklearn", "concept_erasure", "stegopot")
    )
    repository = FileArtifactRepository(artifact_root)

    def execute(context):
        request = context.plan.request
        if (
            request.model_id != config["model_id"]
            or request.study_arm_ref != arm
            or request.research_protocol_ref != entry["protocol_ref"]
            or context.plan.threat_contract.contract_id != contract_id
            or request.mode.value != "capture_only"
        ):
            raise ValueError("S 请求与冻结模型、协议、契约或实验臂不一致")
        if (
            len(request.capture_targets) != 1
            or request.capture_targets[0].layer != config["layer"]
            or request.capture_targets[0].component != "resid_post"
            or tuple(request.capture_targets[0].agent_ids) != ("receiver",)
            or request.capture_targets[0].token_policy != "last_token"
        ):
            raise ValueError("S 采集坐标与冻结协议不一致")
        if (
            digest_file(path) != config_hash
            or digest_file(config["dataset_path"]) != data_hash
            or digest_file(config["split_path"]) != split_hash
        ):
            raise ValueError("S 冻结配置、数据或切分被修改")
        if _model_hashes(model) != model_hashes:
            raise ValueError("S 冻结模型或 tokenizer 被修改")
        started = utc_now()
        output = artifact_root / "restricted" / context.run_id
        result = run_live_experiment(
            path,
            method=arm,
            context=context,
            output=output,
            training_root=artifact_root / "restricted" / "training",
        )
        event_payload = {
            "schema_version": "stego.events/1",
            "run_id": context.run_id,
            "study_id": request.metadata.get("study_id"),
            "arm_id": arm,
            "events": result["events"],
        }
        event_ref = repository.put_bytes(
            "public-summary",
            json.dumps(event_payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode(),
            media_type="application/json",
        )
        from warden.core.domain.models import to_primitive

        manifest = {
            "schema_version": "warden.research-run/2",
            "run_id": context.run_id,
            "plan_id": context.plan.plan_id,
            "study_id": request.metadata.get("study_id"),
            "arm_id": arm,
            "protocol_ref": request.research_protocol_ref,
            "contract_id": contract_id,
            "config_sha256": config_hash,
            "executor_sha256": adapter_hash,
            "dataset_sha256": data_hash,
            "split_sha256": split_hash,
            "model_id": config["model_id"],
            "model_revision": model.revision,
            "model_files_sha256": model_hashes,
            "tokenizer_revision": model.revision,
            "seed": config["seed"],
            "started_at": started,
            "finished_at": utc_now(),
            "status": result["status"],
            "provenance": "real_sender_receiver",
            "communication_mode": "instrumented_llm_codebook",
            "track": "live_steganography",
            "metrics": result["metrics"],
            "missing_metrics": result["missing_metrics"],
            "outcomes": result["outcomes"],
            "events_artifact": to_primitive(event_ref),
            "model_calls": result["model_calls"],
            "training_sha256": result["training_sha256"],
            "limitations": result["limitations"],
            "files_sha256": {p.name: digest_file(p) for p in output.iterdir() if p.is_file()},
        }
        # 本地 URI 属于受限实现细节，不放入公共清单。
        manifest["events_artifact"].pop("uri", None)
        manifest_ref = repository.put_bytes(
            "public-summary",
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, allow_nan=False).encode(),
            media_type="application/json",
        )
        gateway = ArtifactGateway(
            repository, {ref.artifact_id: ref for ref in (event_ref, manifest_ref)}
        )
        gateway.read(event_ref.artifact_id)
        gateway.read(manifest_ref.artifact_id)
        if result["status"] != "completed":
            raise AuditStageFailure(
                "S 实际实验失败；公共工件包含失败及 ITT 分母",
                partial_result=StageResult(
                    artifacts=(manifest_ref, event_ref), limitations=result["limitations"]
                ),
            )
        return StageResult(artifacts=(manifest_ref, event_ref), limitations=result["limitations"])

    caps = [
        CapabilityReport(
            "research." + stage_id,
            ready,
            (
                "research_stage_allowlist",
                "live_stego_frozen_protocol_v1",
                "sender_receiver_baseline",
                "probe_training",
                arm,
                *(("leace_fit_apply",) if arm == "leace" else ()),
            )
            if ready
            else (),
            reason=None if ready else "S 本地模型权重或可选依赖未配置",
        )
    ]
    contract = ThreatContract(
        contract_id,
        "controlled-llm-codebook",
        ("sender", "receiver"),
        (("sender", "receiver"),),
        "synthetic_secret_recovery",
        "public_arithmetic",
    )
    return CallableAuditStage(stage_id, execute), (entry["protocol_ref"], arm), caps, contract

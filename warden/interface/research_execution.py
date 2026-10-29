"""部署者冻结白盒协议的组合根；客户端只能提交协议与实验臂引用。"""

from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from warden.application.executor import CallableAuditStage, PipelineAuditExecutor, StageResult
from warden.core.domain.models import CapabilityReport, ThreatContract, utc_now
from warden.infrastructure.storage.filesystem import FileArtifactRepository
from warden.infrastructure.storage.gateway import ArtifactGateway


def configure_research(path: Path, artifact_root: Path):
    """返回执行器、服务端映射、能力；不加载模型、不下载资源。

    path 只能由本地部署环境指定。配置变化产生不同阶段标识，旧计划不被新配置执行。
    工件原始张量留在受限目录，仅摘要通过 ArtifactGateway 发布。
    """
    from warden.infrastructure.workflows.whitebox_probe import (
        load_whitebox_probe_config,
        preflight_whitebox_probe_experiment,
        run_whitebox_probe_experiment,
    )

    source = Path(path).resolve()
    registry = json.loads(source.read_text(encoding="utf-8"))
    if set(registry) != {"schema_version", "protocols"} or registry["schema_version"] != 1:
        raise ValueError("不支持的执行注册表")
    stages, mapping, reports, contracts = [], {}, [], {}
    repository = FileArtifactRepository(artifact_root)
    executor_hash = _file_hash(Path(__file__))
    for entry in registry["protocols"]:
        if set(entry) != {"protocol_ref", "arm_ref", "config", "phase"}:
            raise ValueError("协议注册包含未知或缺失字段")
        if entry["phase"] not in {"collect", "all"}:
            raise ValueError("研究执行只支持 collect 或 all")
        config_path = (source.parent / entry["config"]).resolve()
        config = load_whitebox_probe_config(config_path)
        if config.dataset_format != "fractal_mechanism":
            raise ValueError("当前注册执行器仅支持已验证的 M 轨道机制数据")
        if not config.model.local_files_only or config.model.trust_remote_code:
            raise ValueError("研究模型必须离线加载并关闭 remote code")
        if not config.model.revision:
            raise ValueError("研究模型必须固定 revision")
        digest = sha256(config_path.read_bytes()).hexdigest()
        dataset_hash = (_file_hash(config.dataset_path) if config.dataset_path.is_file() else None)
        split_hash = (_file_hash(config.split_path)
                      if config.split_path and config.split_path.is_file() else None)
        stage_id = "whitebox-" + sha256(
            (digest + str(dataset_hash) + str(split_hash) + entry["phase"] + executor_hash).encode()
        ).hexdigest()
        key = (entry["protocol_ref"], entry["arm_ref"])
        if key in mapping:
            raise ValueError("协议与实验臂引用重复")
        mapping[key] = (stage_id,)
        preflight = preflight_whitebox_probe_experiment(config)
        contract_id = "mechanism-" + str(dataset_hash)
        if preflight["ready"]:
            contracts[contract_id] = ThreatContract(
                contract_id, "codebook_binding", tuple(config.agent_ids), (),
                "SELECT_ALTERNATE", "FOLLOW_PUBLIC",
            )
        reports.append(CapabilityReport(
            "research." + stage_id, preflight["ready"],
            (("research_stage_allowlist", "research_dataset_mechanism")
             if preflight["ready"] else ()),
            reason=None if preflight["ready"] else "; ".join(
                item["message"] for item in preflight["checks"] if item["status"] == "blocked"),
        ))

        def execute(context, config=config, phase=entry["phase"], digest=digest,
                    dataset_hash=dataset_hash, split_hash=split_hash, key=key,
                    contract_id=contract_id, executor_hash=executor_hash):
            request = context.plan.request
            if ((request.research_protocol_ref, request.study_arm_ref) != key
                    or context.plan.threat_contract.contract_id != contract_id
                    or request.model_id != config.model_id
                    or tuple(request.capture_targets) != tuple(config.capture_targets)
                    or request.mode.value != "capture_only"):
                raise ValueError("请求模型、采集坐标或模式与冻结协议不一致")
            if sha256(config.dataset_path.read_bytes()).hexdigest() != dataset_hash:
                raise ValueError("冻结数据内容发生变化")
            if (config.split_path
                    and sha256(config.split_path.read_bytes()).hexdigest() != split_hash):
                raise ValueError("冻结切分内容发生变化")
            started = utc_now()
            model_files = {file.name: _file_hash(file)
                           for file in Path(config.model.model_path).iterdir()
                           if file.is_file() and file.suffix in {".json", ".safetensors", ".txt"}}
            output = artifact_root / "restricted" / context.run_id
            run_whitebox_probe_experiment(
                replace(config, output_directory=output), phase=phase,
            )
            files = {str(file.relative_to(output)).replace("\\", "/"):
                     sha256(file.read_bytes()).hexdigest()
                     for file in output.rglob("*") if file.is_file()}
            corpus = json.loads((output / "activation_corpus" / "manifest.json").read_text(
                encoding="utf-8"))
            sample_count = len(corpus.get("sample_ids", []))
            if not sample_count:
                raise RuntimeError("真实采集没有生成样本")
            manifest = {
                "schema_version": "warden.research-run/1", "run_id": context.run_id,
                "plan_id": context.plan.plan_id, "study_id": request.metadata.get("study_id"),
                "arm_id": request.study_arm_ref, "protocol_ref": request.research_protocol_ref,
                "contract_id": contract_id,
                "config_sha256": digest, "dataset_sha256": dataset_hash,
                "executor_sha256": executor_hash,
                "split_sha256": split_hash, "model_id": config.model_id,
                "model_revision": config.model.revision,
                "tokenizer_revision": config.model.revision,
                "seed": config.random_seed, "started_at": started, "finished_at": utc_now(),
                "status": "completed", "provenance": "local_real_model",
                "track": "mechanism_testbed", "files_sha256": files,
                "model_files_sha256": model_files,
                "metrics": {"capture_count": {"value": sample_count,
                                             "denominator": sample_count}},
                "missing_metrics": {"BER": "未执行实时通信 Receiver 解码"},
                "dependencies": {name: _version(name)
                                 for name in ("torch", "transformers", "stegopot")},
            }
            ref = repository.put_bytes("public-summary", json.dumps(
                manifest, sort_keys=True, ensure_ascii=False, allow_nan=False,
            ).encode("utf-8"), media_type="application/json")
            ArtifactGateway(repository, {ref.artifact_id: ref}).read(ref.artifact_id)
            return StageResult(artifacts=(ref,), limitations=("M 轨道采集，不代表通信或防御效果",))

        stages.append(CallableAuditStage(stage_id, execute))
    if reports and all(report.available for report in reports):
        reports.append(CapabilityReport("activation.backend", True, (
            "agent_message_hook", "model_invocation_hook", "activation_read")))
        reports.append(CapabilityReport("agent.runtime", True,
                                       ("mechanism_replay",)))
    return PipelineAuditExecutor(stages), mapping, reports, contracts


def public_artifact_reader(queue, artifact_root: Path):
    """动态读取已完成队列记录中的公共摘要，重启后保留授权与哈希校验。"""
    repository = FileArtifactRepository(artifact_root)

    def read(artifact_id: str) -> bytes:
        references = {ref.artifact_id: ref for run in queue.list()
                      if run.evidence is not None
                      for ref in run.evidence.artifacts if ref.kind == "public-summary"}
        return ArtifactGateway(repository, references).read(artifact_id)

    return read


def _version(name: str) -> str:
    """记录实际依赖版本，未安装时明确标记。"""
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _file_hash(path: Path) -> str:
    """流式校验模型权重，避免将大文件额外载入内存。"""
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

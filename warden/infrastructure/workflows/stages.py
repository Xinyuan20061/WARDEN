"""把既有白盒函数接入原 PipelineAuditExecutor，不建立第二套执行器。"""

from __future__ import annotations

import json
from typing import Any

from warden.application.executor import CallableAuditStage, StageResult
from warden.core.ports.artifacts import ArtifactRepository
from warden.infrastructure.workflows.whitebox_probe import (
    WhiteBoxProbeExperimentConfig,
    run_whitebox_probe_experiment,
)


def whitebox_stage(config: WhiteBoxProbeExperimentConfig, *, phase: str,
                   artifacts: ArtifactRepository) -> CallableAuditStage:
    """组合服务端冻结配置为原审计阶段。

    参数：
        config: 组合根加载的可信配置，不能来自任意 HTTP JSON。
        phase: collect 或 train；每个阶段分别调度与核验。
        artifacts: 保存运行摘要的现有 ArtifactRepository，不转移所有权。

    返回：
        使用既有白盒工作流的 CallableAuditStage。
    """
    if phase not in {"collect", "train"}:
        raise ValueError("研究阶段仅支持 collect 或 train")

    def handler(_context: Any) -> StageResult:
        summary = run_whitebox_probe_experiment(config, phase=phase)
        artifact = artifacts.put_bytes(
            "whitebox-summary", json.dumps(summary, ensure_ascii=False).encode(),
            media_type="application/json", metadata={"phase": phase},
        )
        return StageResult(artifacts=(artifact,))

    return CallableAuditStage(f"whitebox_{phase}", handler)

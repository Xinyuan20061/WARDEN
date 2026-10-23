"""使用微型双智能体模型验证 WARDEN 完整执行链。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np

from warden.application import CallableAuditStage, PipelineAuditExecutor, StageResult
from warden.core.domain.enums import AuditMode, RunStatus
from warden.core.domain.models import (
    AuditPlan,
    AuditRequest,
    CaptureTarget,
    ThreatContract,
)
from warden.infrastructure.execution import InProcessRunDispatcher
from warden.infrastructure.methods.probe import SklearnLinearProbeTrainer
from warden.infrastructure.storage import FileArtifactRepository


@dataclass(frozen=True, slots=True)
class TinyAgentModel:
    """可显式读写隐状态的微型神经模型。"""

    weights: np.ndarray
    bias: np.ndarray
    readout: np.ndarray

    def hidden(self, model_input: np.ndarray) -> np.ndarray:
        """返回用于 Probe 和干预的隐状态。"""

        return np.tanh(np.asarray(model_input, dtype=np.float64) @ self.weights + self.bias)

    def behavior_score(self, hidden: np.ndarray) -> float:
        """把隐状态映射为有害协调行为的玩具分数。"""

        logit = float(np.asarray(hidden, dtype=np.float64) @ self.readout)
        return 1.0 / (1.0 + math.exp(-logit))


def _build_model() -> TinyAgentModel:
    """创建不需要下载权重的确定性小模型。"""

    return TinyAgentModel(
        weights=np.asarray(
            [
                [1.4, -0.7, 0.5, 0.2],
                [0.8, 0.5, -1.0, 0.9],
            ],
            dtype=np.float64,
        ),
        bias=np.asarray([-0.1, 0.0, 0.1, -0.2], dtype=np.float64),
        readout=np.asarray([1.2, -0.4, 0.4, 0.7], dtype=np.float64),
    )


def _train_probe(model: TinyAgentModel):
    """在与演示场景一致的隐状态上训练线性 Probe。"""

    rng = np.random.default_rng(19)
    model_inputs = rng.normal(size=(320, 2))
    labels = (model_inputs[:, 0] + 0.55 * model_inputs[:, 1] > 0.25).astype(int)
    features = model.hidden(model_inputs)
    permutation = rng.permutation(features.shape[0])
    train_indices = permutation[:240]
    validation_indices = permutation[240:]
    trainer = SklearnLinearProbeTrainer(random_seed=19)
    return trainer.fit(
        features[train_indices],
        labels[train_indices],
        validation_features=features[validation_indices],
        validation_labels=labels[validation_indices],
        metadata={
            "probe_id": "tiny-collusion-probe",
            "version": "1",
            "model_id": "warden/tiny-agent-model",
            "tensor_ref": "layer:0:tiny_hidden",
            "positive_label": "coordinated_harmful_state",
            "training_fingerprint": "local-tiny-audit-seed-19",
            "purpose": "executor_smoke_test",
        },
    )


def _build_plan() -> AuditPlan:
    """创建覆盖检测、归因、干预和效用评价的计划。"""

    contract = ThreatContract(
        contract_id="tiny-two-agent-contract",
        scenario_id="local_tiny_coordination",
        agent_ids=("sender", "receiver"),
        communication_edges=(("sender", "receiver"),),
        harmful_objective="两个智能体共同提高玩具有害行为分数",
        benign_objective="保留低风险输入下的模型输出",
    )
    request = AuditRequest(
        request_id="tiny-audit-request",
        contract_id=contract.contract_id,
        model_id="warden/tiny-agent-model",
        runtime_id="local-numpy-runtime",
        mode=AuditMode.DEFENSE_EVALUATION,
        probe_id="tiny-collusion-probe",
        capture_targets=(
            CaptureTarget(
                target_id="tiny-hidden",
                agent_ids=contract.agent_ids,
                layer=0,
                component="tiny_hidden",
            ),
        ),
        metadata={"seed": 19, "purpose": "executor_smoke_test"},
    )
    return AuditPlan(
        plan_id="tiny-audit-plan",
        request=request,
        threat_contract=contract,
        required_capabilities=(),
        stages=(
            "trace_alignment",
            "activation_capture",
            "probe_detection",
            "causal_attribution",
            "controlled_intervention",
            "utility_evaluation",
        ),
    )


def run_demo() -> dict[str, Any]:
    """运行完整微型审计并返回可序列化摘要。"""

    model = _build_model()
    probe = _train_probe(model)
    plan = _build_plan()
    local_temporary_root = Path(".warden") / "example-tmp"
    local_temporary_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix="tiny-audit-",
        dir=local_temporary_root,
    ) as temporary:
        artifacts = FileArtifactRepository(Path(temporary))

        def trace_alignment(context):
            """声明当前和良性对照的双智能体输入。"""

            del context
            return StageResult(
                state_updates={
                    "model_inputs": {
                        "sender": np.asarray([1.25, 0.75]),
                        "receiver": np.asarray([0.95, 1.05]),
                    },
                    "benign_inputs": {
                        "sender": np.asarray([-0.85, 0.30]),
                        "receiver": np.asarray([-0.70, 0.20]),
                    },
                }
            )

        def activation_capture(context):
            """运行小模型并以内容寻址引用保存 Activation。"""

            model_inputs = context.require("model_inputs")
            benign_inputs = context.require("benign_inputs")
            hidden = {agent: model.hidden(value) for agent, value in model_inputs.items()}
            benign_hidden = {
                agent: model.hidden(value) for agent, value in benign_inputs.items()
            }
            references = tuple(
                artifacts.put_bytes(
                    "activation",
                    value.astype("<f8", copy=False).tobytes(),
                    media_type="application/vnd.warden.numpy-vector",
                    metadata={
                        "agent_id": agent,
                        "model_id": plan.request.model_id,
                        "tensor_ref": "layer:0:tiny_hidden",
                        "shape": list(value.shape),
                        "dtype": "float64",
                    },
                )
                for agent, value in sorted(hidden.items())
            )
            before = float(np.mean([model.behavior_score(value) for value in hidden.values()]))
            return StageResult(
                artifacts=references,
                metrics={"joint_behavior_before": before},
                state_updates={
                    "activations": hidden,
                    "benign_activations": benign_hidden,
                    "joint_behavior_before": before,
                },
            )

        def probe_detection(context):
            """对每个主体的隐状态独立读出风险。"""

            hidden = context.require("activations")
            benign_hidden = context.require("benign_activations")
            agents = tuple(sorted(hidden))
            scores = probe.score(
                np.stack([hidden[agent] for agent in agents]),
                sample_ids=agents,
            )
            benign_scores = probe.score(
                np.stack([benign_hidden[agent] for agent in agents]),
                sample_ids=tuple(f"benign:{agent}" for agent in agents),
            )
            return StageResult(
                risk_scores=scores,
                metrics={"mean_risk": float(np.mean([item.value for item in scores]))},
                state_updates={
                    "agent_risk": dict(zip(agents, (item.value for item in scores), strict=True)),
                    "benign_agent_risk": dict(
                        zip(agents, (item.value for item in benign_scores), strict=True)
                    ),
                },
            )

        def causal_attribution(context):
            """用良性对照 Activation 联合 patch 验证行为效应。"""

            benign_hidden = context.require("benign_activations")
            before = context.require("joint_behavior_before")
            patched = float(
                np.mean([model.behavior_score(value) for value in benign_hidden.values()])
            )
            effect = before - patched
            return StageResult(
                findings=(
                    {
                        "kind": "joint_activation_patch",
                        "patched_agents": sorted(benign_hidden),
                        "behavior_effect": effect,
                        "causal_claim": "toy_example_only",
                    },
                ),
                metrics={"joint_patch_effect": effect},
                state_updates={"joint_patch_effect": effect},
            )

        def controlled_intervention(context):
            """按 Probe 风险分数向线性读出的反方向轻微移动。"""

            hidden = context.require("activations")
            benign_hidden = context.require("benign_activations")
            risk = context.require("agent_risk")
            benign_risk = context.require("benign_agent_risk")
            weights, _ = probe.parameters
            direction = weights / max(float(np.linalg.norm(weights)), 1e-12)
            intervention_scale = 0.55
            intervened = {
                agent: value - intervention_scale * risk[agent] * direction
                for agent, value in hidden.items()
            }
            benign_intervened = {
                agent: value - intervention_scale * benign_risk[agent] * direction
                for agent, value in benign_hidden.items()
            }
            after = float(
                np.mean([model.behavior_score(value) for value in intervened.values()])
            )
            return StageResult(
                findings=(
                    {
                        "kind": "score_weighted_directional_intervention",
                        "scale": intervention_scale,
                        "agents": sorted(intervened),
                    },
                ),
                metrics={"joint_behavior_after": after},
                state_updates={
                    "intervened_activations": intervened,
                    "benign_intervened_activations": benign_intervened,
                    "joint_behavior_after": after,
                },
            )

        def utility_evaluation(context):
            """同时报告有害分数抑制和良性输出偏移。"""

            before = context.require("joint_behavior_before")
            after = context.require("joint_behavior_after")
            benign_hidden = context.require("benign_activations")
            benign_intervened = context.require("benign_intervened_activations")
            benign_before = float(
                np.mean([model.behavior_score(value) for value in benign_hidden.values()])
            )
            benign_after = float(
                np.mean([model.behavior_score(value) for value in benign_intervened.values()])
            )
            return StageResult(
                metrics={
                    "harmful_behavior_reduction": before - after,
                    "benign_behavior_shift": abs(benign_before - benign_after),
                },
                limitations=(
                    "这是确定性合成模型的执行器结构测试，不构成共谋检测或防御效果结论。",
                ),
            )

        executor = PipelineAuditExecutor(
            (
                CallableAuditStage("trace_alignment", trace_alignment),
                CallableAuditStage("activation_capture", activation_capture),
                CallableAuditStage("probe_detection", probe_detection),
                CallableAuditStage("causal_attribution", causal_attribution),
                CallableAuditStage("controlled_intervention", controlled_intervention),
                CallableAuditStage("utility_evaluation", utility_evaluation),
            )
        )
        run = InProcessRunDispatcher(executor).submit(plan)
        if run.status is not RunStatus.COMPLETED or run.evidence is None:
            limitations = () if run.evidence is None else run.evidence.limitations
            detail = "; ".join(limitations) or run.error or "未知错误"
            raise RuntimeError(f"微型审计未完成：{detail}")
        return {
            "status": run.status.value,
            "run_id": run.run_id,
            "probe_validation_balanced_accuracy": (
                probe.manifest.metrics["validation_balanced_accuracy"]
            ),
            "risk_scores": {
                item.sample_id: item.value for item in run.evidence.risk_scores
            },
            "metrics": dict(run.evidence.metrics),
            "finding_kinds": [item["kind"] for item in run.evidence.findings],
            "artifact_count": len(run.evidence.artifacts),
            "limitations": list(run.evidence.limitations),
        }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2, sort_keys=True))

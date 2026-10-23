"""本地微型模型完整执行链测试。"""

from pathlib import Path
from runpy import run_path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("sklearn")

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "local_tiny_audit.py"
run_demo = run_path(str(_EXAMPLE))["run_demo"]


def test_tiny_audit_completes_detection_attribution_and_intervention() -> None:
    """真实训练 Probe 后应完成双主体审计及效用报告。"""

    summary = run_demo()
    metrics = summary["metrics"]
    assert summary["status"] == "completed"
    assert summary["artifact_count"] == 2
    assert set(summary["risk_scores"]) == {"sender", "receiver"}
    assert "joint_activation_patch" in summary["finding_kinds"]
    assert metrics["causal_attribution.joint_patch_effect"] > 0
    assert metrics["utility_evaluation.harmful_behavior_reduction"] > 0
    assert (
        metrics["utility_evaluation.benign_behavior_shift"]
        < metrics["utility_evaluation.harmful_behavior_reduction"]
    )

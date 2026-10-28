"""持久任务显式反序列化；不加载 pickle 或任意 Python 类。"""

from warden.core.domain.models import (
    ActivationCoordinate,
    ArtifactRef,
    AuditPlan,
    AuditRequest,
    AuditRun,
    CaptureTarget,
    EvidenceBundle,
    RiskScore,
    ThreatContract,
)


def restore_plan(value: dict) -> AuditPlan:
    """将可信本地存储字典恢复为 AuditPlan；未知字段由领域构造器拒绝。"""
    payload = dict(value)
    request = dict(payload["request"])
    request["capture_targets"] = tuple(CaptureTarget(**x) for x in request["capture_targets"])
    payload["request"] = AuditRequest(**request)
    payload["threat_contract"] = ThreatContract(**payload["threat_contract"])
    return AuditPlan(**payload)


def restore_run(value: dict) -> AuditRun:
    """恢复任务及嵌套证据包，不执行存储中的代码。"""
    payload = dict(value)
    if payload.get("evidence") is not None:
        evidence = dict(payload["evidence"])
        evidence["artifacts"] = tuple(ArtifactRef(**x) for x in evidence["artifacts"])
        scores = []
        for score in evidence["risk_scores"]:
            item = dict(score)
            if item.get("coordinate"):
                item["coordinate"] = ActivationCoordinate(**item["coordinate"])
            scores.append(RiskScore(**item))
        evidence["risk_scores"] = tuple(scores)
        payload["evidence"] = EvidenceBundle(**evidence)
    return AuditRun(**payload)

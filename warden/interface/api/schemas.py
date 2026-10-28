"""只属于 HTTP 边界的 Pydantic Schema。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from warden.core.domain.enums import AuditMode
from warden.core.domain.models import AuditRequest, CaptureTarget


class CaptureTargetSchema(BaseModel):
    """REST API 中的模型内部采集位置。"""

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(min_length=1)
    agent_ids: list[str] = Field(min_length=1)
    module: str | None = None
    layer: int | None = Field(default=None, ge=0)
    component: str | None = "resid_post"
    token_policy: str = "last_token"
    retain_gradient: bool = False

    def to_domain(self) -> CaptureTarget:
        """转换为不依赖 Pydantic 的核心对象。"""

        return CaptureTarget(**self.model_dump())


class AuditRequestSchema(BaseModel):
    """创建审计计划的版本化请求。"""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    mode: AuditMode = AuditMode.CAUSAL_AUDIT
    probe_id: str | None = None
    sae_id: str | None = None
    capture_targets: list[CaptureTargetSchema] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    research_protocol_ref: str | None = Field(default=None, min_length=1)
    study_arm_ref: str | None = Field(default=None, min_length=1)

    def to_domain(self) -> AuditRequest:
        """转换为核心请求对象。"""

        return AuditRequest(
            request_id=self.request_id,
            contract_id=self.contract_id,
            model_id=self.model_id,
            runtime_id=self.runtime_id,
            mode=self.mode,
            probe_id=self.probe_id,
            sae_id=self.sae_id,
            capture_targets=tuple(item.to_domain() for item in self.capture_targets),
            metadata=self.metadata,
            research_protocol_ref=self.research_protocol_ref,
            study_arm_ref=self.study_arm_ref,
        )


class RunRequestSchema(BaseModel):
    """启动一个已编译审计计划。"""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)

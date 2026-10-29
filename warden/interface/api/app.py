"""供测试平台使用的版本化 FastAPI 应用。"""

from __future__ import annotations

from collections.abc import Callable
from hmac import compare_digest
from typing import Any

from warden import __version__
from warden.application.service import WardenService
from warden.interface.api.projections import public_projection
from warden.interface.api.schemas import AuditRequestSchema, RunRequestSchema


def create_app(
    service: WardenService | None = None,
    *,
    research_token: str | None = None,
    artifact_reader: Callable[[str], bytes] | None = None,
) -> Any:
    """创建 API 应用；导入模块本身不会要求安装 FastAPI。

    参数：
        service: 由组合根注入的审计服务；为空时构造默认无模型服务。
        research_token: 操作者 Bearer 令牌；未配置时拒绝研究写操作。
        artifact_reader: 已审批工件网关的 read 方法；未配置时拒绝下载。

    返回：
        FastAPI 实例。模型、执行器和工件资源的所有权仍由组合根管理。

    异常：
        RuntimeError: 未安装 API 可选依赖。
    """

    try:
        from fastapi import FastAPI, Header, HTTPException, Query, Response
    except ImportError as exc:
        raise RuntimeError("创建 REST API 需要安装 warden-kernel[api]") from exc
    if service is None:
        import os
        from pathlib import Path

        from warden.interface.factory import build_default_service

        service = build_default_service()
        research_token = research_token or os.getenv("WARDEN_RESEARCH_TOKEN")
        if service.dispatcher is not None and os.getenv("WARDEN_EXECUTION_CONFIG"):
            from warden.interface.research_execution import public_artifact_reader

            artifact_reader = artifact_reader or public_artifact_reader(
                service.dispatcher,
                Path(os.getenv("WARDEN_ARTIFACT_ROOT", Path.cwd() / "artifacts" / "research")),
            )
    app = FastAPI(
        title="WARDEN API",
        version=__version__,
        description="多智能体有害交互的因果审计及可控防御内核接口。",
    )

    def authorize_research(authorization: str | None) -> None:
        """研究写操作要求服务端配置并匹配 Bearer 令牌。"""
        if not research_token:
            raise HTTPException(status_code=403, detail="研究写接口未启用")
        if not authorization or not compare_digest(authorization, f"Bearer {research_token}"):
            raise HTTPException(status_code=401, detail="研究操作未授权")

    def project_run(item):
        """公开稳定状态原因，不泄露模型路径、提示词或原始异常。"""
        value = public_projection(item)
        if item.status.value == "failed":
            ambiguous = item.metadata.get("phase") == "ambiguous"
            value["failure"] = {
                "code": "EXECUTION_AMBIGUOUS" if ambiguous else "EXECUTOR_FAILED",
                "message": (
                    "Worker 已中断，副作用未知；需要操作者对账，禁止自动重试"
                    if ambiguous
                    else "执行阶段失败；请按任务 ID 查阅受限 Worker 日志"
                ),
            }
        return value

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        """返回服务状态，不把组件不可用伪装成服务崩溃。"""

        return {"status": "ok", "version": __version__, "api_version": "v1"}

    @app.get("/v1/capabilities")
    def capabilities() -> list[dict[str, Any]]:
        """返回全部 Adapter 的能力与不可用原因。"""

        return [public_projection(item) for item in service.capabilities()]

    @app.get("/v1/resources")
    def resources(kind: str | None = Query(default=None, pattern="^(probe|sae)$")):
        """返回平台可选择的 Probe 与 SAE 清单。"""

        return [public_projection(item) for item in service.list_resources(kind=kind)]

    @app.get("/v1/research-protocols/{protocol_ref}/arms/{arm_id}")
    def execution_contract(protocol_ref: str, arm_id: str):
        """返回服务端实际阶段的冻结目标；不信任前端预览或调用者自报目标。"""
        value = service.research_contract(protocol_ref, arm_id)
        if value is None:
            raise HTTPException(status_code=404, detail="找不到冻结执行配置")
        return value

    @app.get("/v1/contracts")
    def contracts() -> list[str]:
        """返回当前威胁来源中的契约标识。"""

        return list(service.list_contracts())

    @app.post("/v1/audit-plans")
    def create_audit_plan(
        request: AuditRequestSchema, authorization: str | None = Header(default=None)
    ):
        """编译审计计划，缺失训练资源时返回 blocked 状态和原因。"""

        if request.research_protocol_ref is not None:
            authorize_research(authorization)
        try:
            plan = service.create_plan(request.to_domain())
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return public_projection(plan)

    @app.get("/v1/audit-plans")
    def audit_plans():
        """返回当前进程登记的计划。"""

        return [public_projection(item) for item in service.list_plans()]

    @app.get("/v1/audit-plans/{plan_id}")
    def audit_plan(plan_id: str):
        """返回单个计划。"""

        plan = service.get_plan(plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="找不到审计计划")
        return public_projection(plan)

    @app.post("/v1/runs")
    def start_run(request: RunRequestSchema, authorization: str | None = Header(default=None)):
        """提交计划；执行器未就绪时返回可追踪的 blocked 任务。"""

        plan = service.get_plan(request.plan_id)
        if plan is not None and plan.request.research_protocol_ref is not None:
            authorize_research(authorization)
        try:
            run = service.start_run(request.plan_id)
        except (KeyError, ValueError, RuntimeError) as exc:
            from warden.infrastructure.execution.sqlite import IdempotencyConflict

            if isinstance(exc, IdempotencyConflict):
                raise HTTPException(status_code=409, detail="request_id 正文冲突") from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return project_run(run)

    @app.get("/v1/runs")
    def runs():
        """返回当前进程可见的任务快照。"""

        return [project_run(item) for item in service.list_runs()]

    @app.get("/v1/runs/{run_id}")
    def run(run_id: str):
        """返回单个任务的最新快照。"""

        item = service.get_run(run_id)
        if item is None:
            raise HTTPException(status_code=404, detail="找不到审计任务")
        return project_run(item)

    @app.get(
        "/v1/artifacts/{artifact_id}/content",
        response_class=Response,
        responses={
            200: {
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                }
            }
        },
    )
    def artifact_content(artifact_id: str, authorization: str | None = Header(default=None)):
        """经操作者授权读取白名单公共摘要；不接受路径或 URI。"""
        authorize_research(authorization)
        if artifact_reader is None:
            raise HTTPException(status_code=403, detail="工件下载未启用")
        try:
            content = artifact_reader(artifact_id)
        except (KeyError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail="工件不存在或未授权") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="工件完整性检查失败") from exc
        return Response(content, media_type="application/octet-stream")

    return app

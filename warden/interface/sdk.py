"""测试平台可直接使用的无第三方依赖 HTTP 客户端。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class WardenClient:
    """调用 WARDEN `/v1` API 的轻量同步客户端。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8765", *, timeout: float = 30.0) -> None:
        """初始化客户端。

        参数：
            base_url: WARDEN API 根地址，不包含 `/v1`。
            timeout: 单次 HTTP 请求超时秒数。
        """

        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)

    def health(self) -> Mapping[str, Any]:
        """读取服务版本和存活状态。"""

        return self._request("GET", "/v1/health")

    def capabilities(self) -> list[Mapping[str, Any]]:
        """读取 Adapter 能力和缺失原因。"""

        return list(self._request("GET", "/v1/capabilities"))

    def resources(self, kind: str | None = None) -> list[Mapping[str, Any]]:
        """读取 Probe/SAE 资源；kind 可为 probe 或 sae。"""

        suffix = "" if kind is None else f"?kind={kind}"
        return list(self._request("GET", "/v1/resources" + suffix))

    def contracts(self) -> list[str]:
        """读取可用威胁契约标识。"""

        return list(self._request("GET", "/v1/contracts"))

    def create_audit_plan(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """提交审计请求并返回 planned 或 blocked 计划。"""

        return self._request("POST", "/v1/audit-plans", payload)

    def audit_plan(self, plan_id: str) -> Mapping[str, Any]:
        """读取一个已创建计划。"""

        return self._request("GET", f"/v1/audit-plans/{plan_id}")

    def start_run(self, plan_id: str) -> Mapping[str, Any]:
        """提交已编译计划并返回任务快照。"""

        return self._request("POST", "/v1/runs", {"plan_id": plan_id})

    def runs(self) -> list[Mapping[str, Any]]:
        """读取当前可见的任务。"""

        return list(self._request("GET", "/v1/runs"))

    def run(self, run_id: str) -> Mapping[str, Any]:
        """读取一个任务的最新快照。"""

        return self._request("GET", f"/v1/runs/{run_id}")

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        """发送 JSON 请求并把 HTTP 错误转换成包含响应正文的异常。"""

        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"WARDEN API 返回 HTTP {exc.code}: {message}") from exc

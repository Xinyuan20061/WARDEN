"""StegoPot 可控前向与 SAE 运行能力的 WARDEN 适配器。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from io import BytesIO
from typing import Any

from warden.core.domain.models import (
    ArtifactRef,
    AuditPlan,
    CapabilityReport,
    CaptureTarget,
    InterventionPlan,
)
from warden.core.ports.artifacts import ArtifactRepository


class StegoPotActivationBackend:
    """使用按 Agent 注入的 StegoPot ModelRuntime 执行选择性采集。"""

    def __init__(
        self,
        runtimes: Mapping[str, Any],
        artifacts: ArtifactRepository,
        *,
        intervention_factory: Callable[[Any], Any] | None = None,
        own_runtimes: bool = False,
    ) -> None:
        """初始化适配器。

        参数：
            runtimes: Agent ID 到已配置 StegoPot ModelRuntime 的映射。
            artifacts: 保存 Activation 张量的 WARDEN 工件仓库。
            intervention_factory: 把 WARDEN target 转换为 StegoPot Intervention 的函数。
            own_runtimes: close 时是否关闭注入的 ModelRuntime。
        """

        if not runtimes:
            raise ValueError("StegoPotActivationBackend 至少需要一个 Agent runtime")
        self._runtimes = dict(runtimes)
        self._artifacts = artifacts
        self._intervention_factory = intervention_factory
        self._own_runtimes = bool(own_runtimes)
        self._closed = False

    def capabilities(self) -> CapabilityReport:
        """返回全部 Agent runtime 共同具备的白盒能力。"""

        if self._closed:
            return CapabilityReport(
                component_id="stegopot.activation",
                available=False,
                reason="适配器已经关闭",
            )
        values = [
            {getattr(item, "value", str(item)) for item in runtime.capabilities}
            for runtime in self._runtimes.values()
        ]
        common = set.intersection(*values)
        capabilities = set(common)
        if "forward" in common:
            capabilities.add("model_invocation_hook")
        return CapabilityReport(
            component_id="stegopot.activation",
            available=True,
            capabilities=tuple(capabilities),
            metadata={"agent_ids": sorted(self._runtimes)},
        )

    def capture(
        self,
        plan: AuditPlan,
        inputs_by_agent: Mapping[str, Any],
    ) -> Sequence[ArtifactRef]:
        """执行每个 Agent 的一次可控前向并保存选择性 Activation。"""

        self._ensure_open()
        targets_by_agent: dict[str, list[CaptureTarget]] = defaultdict(list)
        for target in plan.request.capture_targets:
            for agent_id in target.agent_ids:
                targets_by_agent[agent_id].append(target)
        artifacts: list[ArtifactRef] = []
        for agent_id, targets in sorted(targets_by_agent.items()):
            if agent_id not in self._runtimes:
                raise KeyError(f"未配置 Agent runtime：{agent_id}")
            if agent_id not in inputs_by_agent:
                raise KeyError(f"未提供 Agent 模型输入：{agent_id}")
            policy = _trace_policy(targets)
            result = self._runtimes[agent_id].forward(
                inputs_by_agent[agent_id],
                policy=policy,
                run_id=f"{plan.plan_id}:{agent_id}",
            )
            for record in result.trace.records:
                artifacts.append(
                    self._store_record(
                        plan=plan,
                        agent_id=agent_id,
                        model_id=result.trace.model_id,
                        record=record,
                    )
                )
        return tuple(artifacts)

    def intervene(
        self,
        plan: InterventionPlan,
        inputs_by_agent: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """把已验证 WARDEN target 转换为 StegoPot 干预并执行前向。"""

        self._ensure_open()
        if self._intervention_factory is None:
            raise RuntimeError("尚未配置模型专用 intervention_factory")
        interventions_by_agent: dict[str, list[Any]] = defaultdict(list)
        for target in plan.targets:
            interventions_by_agent[target.coordinate.agent_id].append(
                self._intervention_factory(target)
            )
        outputs: dict[str, Any] = {}
        for agent_id, interventions in interventions_by_agent.items():
            if agent_id not in self._runtimes or agent_id not in inputs_by_agent:
                raise KeyError(f"Agent {agent_id} 缺少 runtime 或模型输入")
            outputs[agent_id] = self._runtimes[agent_id].forward(
                inputs_by_agent[agent_id],
                interventions=tuple(interventions),
                run_id=f"{plan.plan_id}:{agent_id}:intervention",
            )
        return outputs

    def close(self) -> None:
        """按所有权关闭全部运行时。"""

        if self._closed:
            return
        self._closed = True
        if self._own_runtimes:
            for runtime in self._runtimes.values():
                runtime.close()

    def _store_record(
        self,
        *,
        plan: AuditPlan,
        agent_id: str,
        model_id: str,
        record: Any,
    ) -> ArtifactRef:
        """把内存张量保存为二进制工件，事件层只保留引用。"""

        value = record.value
        if hasattr(value, "to_dict"):
            payload = _json_bytes(value.to_dict())
            media_type = "application/json"
        else:
            torch = _torch()
            if not torch.is_tensor(value):
                raise TypeError("StegoPot ActivationRecord.value 必须是张量或 StoredTensorRef")
            buffer = BytesIO()
            torch.save(value.detach().cpu(), buffer)
            payload = buffer.getvalue()
            media_type = "application/vnd.pytorch.tensor"
        return self._artifacts.put_bytes(
            "activation",
            payload,
            media_type=media_type,
            metadata={
                "plan_id": plan.plan_id,
                "agent_id": agent_id,
                "model_id": model_id,
                "tensor_ref": record.ref.key,
                "shape": list(record.shape),
                "dtype": record.dtype,
                "gradient_ready": record.gradient is not None,
            },
        )

    def _ensure_open(self) -> None:
        """拒绝在资源关闭后执行模型。"""

        if self._closed:
            raise RuntimeError("StegoPotActivationBackend 已关闭")


class StegoPotSAEAdapter:
    """把 StegoPot SAEModel 暴露为 WARDEN SAEModel。"""

    def __init__(self, model: Any) -> None:
        """保存已完成兼容性检查的 StegoPot SAEModel。"""

        self._model = model

    @property
    def sae_id(self) -> str:
        """返回 SAE 稳定标识。"""

        return self._model.sae_id

    def encode(self, activation: Any) -> Any:
        """代理 SAE 编码。"""

        return self._model.encode(activation)

    def decode(self, features: Any) -> Any:
        """代理 SAE 解码。"""

        return self._model.decode(features)

    def close(self) -> None:
        """关闭底层 SAE。"""

        self._model.close()


class StegoPotEAPAttribution:
    """把 StegoPot 基础 EAP 评分器暴露为 WARDEN 归因方法。"""

    def __init__(self, edges: Sequence[Any], *, reduction: str = "sum") -> None:
        """初始化薄适配器。

        参数：
            edges: StegoPot `EAPEdge` 序列，必须由模型图或实验配置显式定义。
            reduction: 归因内积的 `sum` 或 `mean` 归约。
        """

        try:
            from stegopot.infrastructure.integrations.eap import EAPAnalyzer
        except ImportError as exc:
            raise RuntimeError("需要先安装 vendor/stegopot 的白盒依赖") from exc
        self._analyzer = EAPAnalyzer(tuple(edges), reduction=reduction)

    @property
    def method_id(self) -> str:
        """返回 StegoPot 公开算法和符号约定版本。"""

        return self._analyzer.attribution_id

    def attribute(self, inputs: Any) -> Mapping[str, Any]:
        """对 StegoPot `EAPObservation` 评分并返回不含张量的清单。"""

        return self._analyzer.score(inputs).to_manifest()


def _trace_policy(targets: Sequence[CaptureTarget]) -> Any:
    """把 WARDEN CaptureTarget 转换为 StegoPot TracePolicy。"""

    try:
        from stegopot.domain.model.reference import TensorRef, TracePolicy
    except ImportError as exc:
        raise RuntimeError("需要先安装 vendor/stegopot") from exc
    refs = []
    retain_gradients = any(item.retain_gradient for item in targets)
    for target in targets:
        token = -1 if target.token_policy == "last_token" else None
        refs.append(
            TensorRef(
                module=target.module,
                layer=target.layer,
                component=target.component,
                token=token,
            )
        )
    return TracePolicy(
        refs=tuple(refs),
        profile="selected",
        store="memory" if retain_gradients else "cpu",
        detach=not retain_gradients,
        retain_graph=retain_gradients,
        retain_gradients=retain_gradients,
    )


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    """编码不含张量的 JSON 引用。"""

    import json

    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _torch() -> Any:
    """惰性加载 PyTorch。"""

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("保存 Activation 需要安装 PyTorch") from exc
    return torch

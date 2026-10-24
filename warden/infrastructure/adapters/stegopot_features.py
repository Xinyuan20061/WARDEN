"""从 StegoPot ModelRuntime 提取 Probe 特征。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from warden.core.domain.models import CaptureTarget


class StegoPotActivationFeatureExtractor:
    """顺序复用一个或多个 StegoPot Runtime 提取多主体表征。"""

    def __init__(
        self,
        runtimes: Mapping[str, Any],
        *,
        model_id: str | None = None,
        own_runtimes: bool = False,
    ) -> None:
        """初始化提取器。

        参数：
            runtimes: Agent ID 到 StegoPot ModelRuntime 的映射。多个 Agent 可以
                指向同一个 Runtime，以便在单卡上顺序复用一份模型权重。
            model_id: 可选逻辑模型标识。用于避免把机器相关绝对缓存路径写入工件。
            own_runtimes: `close` 时是否关闭去重后的 Runtime。
        """

        if not runtimes:
            raise ValueError("runtimes 不能为空")
        self._runtimes = dict(runtimes)
        self._own_runtimes = bool(own_runtimes)
        self._closed = False
        model_ids = {self._runtime_model_id(runtime) for runtime in self._runtimes.values()}
        if len(model_ids) != 1:
            raise ValueError("同一 Activation Corpus 的 Agent 必须使用相同模型权重")
        if model_id is not None and (not isinstance(model_id, str) or not model_id.strip()):
            raise ValueError("model_id 必须为空或非空字符串")
        self._model_id = model_id.strip() if model_id is not None else next(iter(model_ids))

    @property
    def model_id(self) -> str:
        """返回共享模型标识。"""

        return self._model_id

    def extract(
        self,
        *,
        sample_id: str,
        inputs_by_agent: Mapping[str, str],
        targets: Sequence[CaptureTarget],
    ) -> Mapping[str, Any]:
        """执行每个主体一次选择性前向并返回一维 CPU 表征。"""

        self._ensure_open()
        try:
            from stegopot.domain.model.reference import TensorRef, TracePolicy
            from stegopot.domain.model.runtime import ModelInput
        except ImportError as exc:
            raise RuntimeError("需要先安装 vendor/stegopot") from exc
        targets_by_agent: dict[str, list[CaptureTarget]] = defaultdict(list)
        for target in targets:
            for agent_id in target.agent_ids:
                targets_by_agent[agent_id].append(target)
        output: dict[str, Any] = {}
        for agent_id, agent_targets in sorted(targets_by_agent.items()):
            if agent_id not in self._runtimes:
                raise KeyError(f"未配置 Agent runtime：{agent_id}")
            if agent_id not in inputs_by_agent:
                raise KeyError(f"样本 {sample_id} 缺少 Agent 输入：{agent_id}")
            refs_by_key: dict[str, Any] = {}
            target_refs: dict[str, Any] = {}
            for target in agent_targets:
                token = -1 if target.token_policy == "last_token" else None
                ref = TensorRef(
                    module=target.module,
                    layer=target.layer,
                    component=target.component,
                    token=token,
                )
                refs_by_key.setdefault(ref.key, ref)
                target_refs[target.target_id] = ref
            result = self._runtimes[agent_id].forward(
                ModelInput(
                    inputs_by_agent[agent_id],
                    format="text",
                    metadata={"sample_id": sample_id, "agent_id": agent_id},
                ),
                policy=TracePolicy(
                    refs=tuple(refs_by_key.values()),
                    profile="selected",
                    store="cpu",
                    detach=True,
                    precision="float32",
                ),
                run_id=f"corpus:{sample_id}:{agent_id}",
            )
            for target in agent_targets:
                record = result.trace.get(target_refs[target.target_id])
                output[f"{agent_id}/{target.target_id}"] = _to_feature_vector(
                    record.value,
                    token_policy=target.token_policy,
                )
        return output

    def close(self) -> None:
        """按所有权关闭去重后的 Runtime。"""

        if self._closed:
            return
        self._closed = True
        if self._own_runtimes:
            seen: set[int] = set()
            for runtime in self._runtimes.values():
                identity = id(runtime)
                if identity not in seen:
                    runtime.close()
                    seen.add(identity)

    @staticmethod
    def _runtime_model_id(runtime: Any) -> str:
        """从公开 Adapter 属性读取模型标识。"""

        adapter = getattr(runtime, "adapter", None)
        model_id = getattr(adapter, "model_id", None)
        if not isinstance(model_id, str) or not model_id.strip():
            raise TypeError("StegoPot ModelRuntime.adapter 必须提供非空 model_id")
        return model_id.strip()

    def _ensure_open(self) -> None:
        """拒绝在关闭后继续执行模型。"""

        if self._closed:
            raise RuntimeError("StegoPotActivationFeatureExtractor 已关闭")


def _to_feature_vector(value: Any, *, token_policy: str) -> Any:
    """把 Hook 张量归约为 CPU float32 一维 NumPy 向量。"""

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("提取真实 Activation 需要安装 PyTorch") from exc
    if not torch.is_tensor(value):
        raise TypeError("ActivationFeatureExtractor 只接受内存或 CPU PyTorch Tensor")
    tensor = value.detach().to(device="cpu", dtype=torch.float32)
    if token_policy == "mean_tokens":
        if tensor.ndim < 2:
            raise ValueError("mean_tokens 要求 Activation 至少包含 token 和 feature 维度")
        tensor = tensor.mean(dim=-2)
    elif token_policy not in {"last_token", "all"}:
        raise ValueError("未知 token_policy")
    return tensor.contiguous().numpy().reshape(-1)

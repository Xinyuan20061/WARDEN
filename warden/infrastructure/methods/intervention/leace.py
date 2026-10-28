"""固定官方实现的 LEACE 适配；不实现概念擦除数学内核。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Any


class LeaceTransform:
    """已拟合的概念擦除器。

    参数：
        eraser: concept-erasure 0.2.4 的 LeaceEraser。
        metadata: 模型 revision、位置、训练指纹与标签语义。

    资源所有权：
        仅拥有擦除参数，不拥有模型或 Runtime。
    """

    def __init__(self, eraser: Any, metadata: Mapping[str, Any]) -> None:
        self.eraser = eraser
        self.metadata = dict(metadata)

    @classmethod
    def fit(cls, features: Any, labels: Any, *, split: str,
            metadata: Mapping[str, Any]) -> LeaceTransform:
        """只在训练集拟合官方 LEACE。

        参数：
            features: [样本, 特征] 浮点 Tensor。
            labels: [样本] 二元标签 Tensor；不接受验证或测试拟合。
            split: 必须明确为 train。
            metadata: model_id、model_revision、tensor_ref、split_sha256、
                label_semantics、token_policy 必须齐全。

        返回：
            在 CPU float64 拟合的变换，应用时保持输入 dtype/device。

        异常：
            ValueError: 输入无效、标签不完整或试图拟合非训练集。
        """
        import torch
        from concept_erasure import LeaceEraser

        if version("concept-erasure") != "0.2.4":
            raise RuntimeError("LEACE 要求 concept-erasure==0.2.4")
        required = {"model_id", "model_revision", "tensor_ref", "split_sha256",
                    "label_semantics", "token_policy"}
        if required - metadata.keys() or any(not metadata[key] for key in required):
            raise ValueError("LEACE 缺少拟合来源元数据")
        if split != "train":
            raise ValueError("LEACE 只能在 train 切分拟合")
        x = torch.as_tensor(features).detach().to(device="cpu", dtype=torch.float64)
        y = torch.as_tensor(labels).detach().to(device="cpu", dtype=torch.float64)
        if x.ndim != 2 or y.ndim != 1 or x.shape[0] != y.shape[0] or x.shape[0] < 2:
            raise ValueError("LEACE 要求对齐的二维特征与一维标签")
        if not torch.isfinite(x).all() or not torch.isfinite(y).all():
            raise ValueError("LEACE 输入必须为有限数")
        if set(y.tolist()) != {0.0, 1.0}:
            raise ValueError("LEACE 训练标签必须同时包含 0 和 1")
        eraser = LeaceEraser.fit(x, y[:, None])
        return cls(eraser, {**dict(metadata), "implementation": "concept-erasure/0.2.4",
                            "feature_width": x.shape[1], "fit_split": "train"})

    def apply(self, value: Any) -> Any:
        """擦除最后一维概念；value 为有限浮点 Tensor，返回同形状/设备/精度。"""
        import torch

        if not torch.is_tensor(value) or not value.is_floating_point():
            raise TypeError("LEACE 仅接受浮点 Tensor")
        if value.ndim < 1 or value.shape[-1] != self.metadata["feature_width"]:
            raise ValueError("LEACE 特征宽度不匹配")
        if not torch.isfinite(value).all():
            raise ValueError("LEACE 输入包含非有限数")
        result = self.eraser(value.to(device="cpu", dtype=torch.float64))
        result = result.to(device=value.device, dtype=value.dtype)
        if not torch.isfinite(result).all():
            raise ValueError("LEACE 输出包含非有限数")
        return result

    def save(self, destination: Path) -> Path:
        """保存非 pickle 权重和哈希清单；destination 必须为空目录，返回该目录。"""
        import numpy as np

        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise FileExistsError("LEACE 输出目录必须为空")
        arrays = {name: getattr(self.eraser, name).detach().cpu().numpy()
                  for name in ("proj_left", "proj_right")}
        bias = self.eraser.bias
        if bias is not None:
            arrays["bias"] = bias.detach().cpu().numpy()
        np.savez_compressed(root / "weights.npz", **arrays)
        manifest = {"schema_version": "warden.leace/1", **self.metadata,
                    "weights_sha256": sha256((root / "weights.npz").read_bytes()).hexdigest()}
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        return root

    @classmethod
    def load(cls, path: Path) -> LeaceTransform:
        """校验 path 中的权重哈希后加载；禁止 pickle，损坏时抛 ValueError。"""
        import numpy as np
        import torch
        from concept_erasure import LeaceEraser

        root = Path(path)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "warden.leace/1":
            raise ValueError("LEACE 工件版本不受支持")
        if sha256((root / "weights.npz").read_bytes()).hexdigest() != manifest["weights_sha256"]:
            raise ValueError("LEACE 权重哈希不匹配")
        with np.load(root / "weights.npz", allow_pickle=False) as arrays:
            eraser = LeaceEraser(
                torch.from_numpy(arrays["proj_left"].copy()),
                torch.from_numpy(arrays["proj_right"].copy()),
                torch.from_numpy(arrays["bias"].copy()) if "bias" in arrays else None,
            )
        return cls(eraser, manifest)

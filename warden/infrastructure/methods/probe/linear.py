"""可复现的二分类线性 Probe 参考实现。"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType
from typing import Any

from warden.core.domain.models import ArtifactRef, RiskScore


@dataclass(frozen=True, slots=True)
class LinearProbeManifest:
    """描述线性 Probe 的输入合同、训练来源和验证结果。"""

    probe_id: str
    version: str
    model_id: str
    tensor_ref: str
    feature_width: int
    positive_label: str
    threshold: float
    training_fingerprint: str
    train_size: int
    validation_size: int
    random_seed: int
    metrics: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    weights_sha256: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "probe_id",
            "version",
            "model_id",
            "tensor_ref",
            "positive_label",
            "training_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 必须是非空字符串")
            object.__setattr__(self, name, value.strip())
        if self.feature_width < 1:
            raise ValueError("feature_width 必须是正整数")
        if not 0 <= self.threshold <= 1:
            raise ValueError("threshold 必须位于 [0, 1]")
        if self.train_size < 2 or self.validation_size < 2:
            raise ValueError("训练集和验证集都必须至少包含两个样本")
        metrics = {str(key): float(value) for key, value in self.metrics.items()}
        if any(not math.isfinite(value) for value in metrics.values()):
            raise ValueError("Probe 指标必须是有限数")
        object.__setattr__(self, "metrics", MappingProxyType(metrics))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        """返回可写入 JSON 的普通字典。"""

        return {
            "probe_id": self.probe_id,
            "version": self.version,
            "model_id": self.model_id,
            "tensor_ref": self.tensor_ref,
            "feature_width": self.feature_width,
            "positive_label": self.positive_label,
            "threshold": self.threshold,
            "training_fingerprint": self.training_fingerprint,
            "train_size": self.train_size,
            "validation_size": self.validation_size,
            "random_seed": self.random_seed,
            "metrics": dict(self.metrics),
            "metadata": dict(self.metadata),
            "weights_sha256": self.weights_sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LinearProbeManifest:
        """从清单字典恢复对象，未知字段会由构造器拒绝。"""

        return cls(**dict(value))


class LinearProbe:
    """使用已训练权重进行二分类风险读出的轻量 Probe。"""

    def __init__(self, weights: Any, bias: float, manifest: LinearProbeManifest) -> None:
        """初始化已训练 Probe。

        参数：
            weights: 一维 NumPy 权重，宽度必须等于清单 feature_width。
            bias: 线性读出的截距。
            manifest: 训练来源、输入位置和阈值清单。
        """

        numpy = _numpy()
        array = numpy.asarray(weights, dtype=numpy.float64)
        if array.ndim != 1 or array.shape[0] != manifest.feature_width:
            raise ValueError("Probe 权重必须是一维且匹配 feature_width")
        if not numpy.isfinite(array).all() or not math.isfinite(float(bias)):
            raise ValueError("Probe 参数必须全部为有限数")
        self._weights = array.copy()
        self._bias = float(bias)
        self.manifest = manifest

    @property
    def probe_id(self) -> str:
        """返回清单中的稳定 Probe 标识。"""

        return self.manifest.probe_id

    def score(self, features: Any, *, sample_ids: Sequence[str]) -> tuple[RiskScore, ...]:
        """对二维特征矩阵输出校准前的 sigmoid 风险分数。"""

        numpy = _numpy()
        matrix = numpy.asarray(features, dtype=numpy.float64)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.ndim != 2 or matrix.shape[1] != self.manifest.feature_width:
            raise ValueError("Probe 输入必须是 [sample, feature_width] 矩阵")
        identifiers = tuple(str(item) for item in sample_ids)
        if len(identifiers) != matrix.shape[0]:
            raise ValueError("sample_ids 数量必须与特征样本数一致")
        logits = matrix @ self._weights + self._bias
        probabilities = numpy.where(
            logits >= 0,
            1 / (1 + numpy.exp(-logits)),
            numpy.exp(logits) / (1 + numpy.exp(logits)),
        )
        return tuple(
            RiskScore(
                probe_id=self.probe_id,
                sample_id=sample_id,
                value=float(value),
                threshold=self.manifest.threshold,
                metadata={
                    "positive_label": self.manifest.positive_label,
                    "model_id": self.manifest.model_id,
                    "tensor_ref": self.manifest.tensor_ref,
                },
            )
            for sample_id, value in zip(identifiers, probabilities, strict=True)
        )

    def close(self) -> None:
        """线性 Probe 不持有外部资源，此方法用于统一生命周期。"""

    @property
    def parameters(self) -> tuple[Any, float]:
        """返回权重副本和截距，供受控保存使用。"""

        return self._weights.copy(), self._bias


class SklearnLinearProbeTrainer:
    """基于 scikit-learn LogisticRegression 的离线训练器。"""

    def __init__(self, *, c: float = 1.0, max_iter: int = 2000, random_seed: int = 0) -> None:
        """保存训练超参数。

        参数：
            c: L2 正则倒数，必须为正数。
            max_iter: 优化最大迭代次数。
            random_seed: 可复现随机种子。
        """

        if c <= 0 or max_iter < 1:
            raise ValueError("c 必须为正数且 max_iter 必须为正整数")
        self.c = float(c)
        self.max_iter = int(max_iter)
        self.random_seed = int(random_seed)

    def fit(
        self,
        features: Any,
        labels: Any,
        *,
        validation_features: Any,
        validation_labels: Any,
        metadata: Mapping[str, Any],
    ) -> LinearProbe:
        """训练 Probe，并只使用验证集选择决策阈值。"""

        numpy = _numpy()
        LogisticRegression = _logistic_regression()
        x_train = numpy.asarray(features, dtype=numpy.float64)
        y_train = numpy.asarray(labels)
        x_validation = numpy.asarray(validation_features, dtype=numpy.float64)
        y_validation = numpy.asarray(validation_labels)
        _validate_split(x_train, y_train, "训练")
        _validate_split(x_validation, y_validation, "验证")
        if x_train.shape[1] != x_validation.shape[1]:
            raise ValueError("训练集与验证集 feature_width 不一致")
        if set(numpy.unique(y_train)) != {0, 1}:
            raise ValueError("线性 Probe 训练标签必须同时包含 0 和 1")
        required_metadata = (
            "probe_id",
            "version",
            "model_id",
            "tensor_ref",
            "positive_label",
            "training_fingerprint",
        )
        missing = [name for name in required_metadata if not metadata.get(name)]
        if missing:
            raise ValueError("Probe 训练元数据缺失：" + ", ".join(missing))
        estimator = LogisticRegression(
            C=self.c,
            max_iter=self.max_iter,
            random_state=self.random_seed,
            class_weight="balanced",
        )
        estimator.fit(x_train, y_train)
        validation_scores = estimator.predict_proba(x_validation)[:, 1]
        threshold, balanced_accuracy = _select_threshold(validation_scores, y_validation)
        manifest = LinearProbeManifest(
            probe_id=str(metadata["probe_id"]),
            version=str(metadata["version"]),
            model_id=str(metadata["model_id"]),
            tensor_ref=str(metadata["tensor_ref"]),
            feature_width=int(x_train.shape[1]),
            positive_label=str(metadata["positive_label"]),
            threshold=threshold,
            training_fingerprint=str(metadata["training_fingerprint"]),
            train_size=int(x_train.shape[0]),
            validation_size=int(x_validation.shape[0]),
            random_seed=self.random_seed,
            metrics={"validation_balanced_accuracy": balanced_accuracy},
            metadata={
                key: value
                for key, value in metadata.items()
                if key not in required_metadata
            },
        )
        return LinearProbe(estimator.coef_[0], float(estimator.intercept_[0]), manifest)

    def save(self, probe: LinearProbe, destination: Path) -> ArtifactRef:
        """原子保存权重与清单，并返回目录级内容哈希引用。"""

        numpy = _numpy()
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            raise FileExistsError(f"Probe 目标目录必须为空：{destination}")
        weights, bias = probe.parameters
        weights_path = destination / "weights.npz"
        numpy.savez_compressed(weights_path, weights=weights, bias=numpy.asarray([bias]))
        weights_hash = sha256(weights_path.read_bytes()).hexdigest()
        manifest = LinearProbeManifest(
            **{
                **probe.manifest.to_dict(),
                "weights_sha256": weights_hash,
            }
        )
        manifest_path = destination / "manifest.json"
        _write_json_atomic(manifest.to_dict(), manifest_path)
        combined_hash = sha256(
            manifest_path.read_bytes() + weights_path.read_bytes()
        ).hexdigest()
        return ArtifactRef(
            artifact_id=f"probe-{combined_hash}",
            kind="probe",
            uri=destination.resolve().as_uri(),
            content_hash=combined_hash,
            media_type="application/vnd.warden.probe+directory",
            size_bytes=manifest_path.stat().st_size + weights_path.stat().st_size,
            metadata={"probe_id": manifest.probe_id, "version": manifest.version},
        )


def load_linear_probe(path: Path) -> LinearProbe:
    """校验清单与权重哈希后加载线性 Probe。"""

    numpy = _numpy()
    root = Path(path)
    manifest_data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest = LinearProbeManifest.from_dict(manifest_data)
    weights_path = root / "weights.npz"
    actual_hash = sha256(weights_path.read_bytes()).hexdigest()
    if manifest.weights_sha256 != actual_hash:
        raise ValueError("Probe 权重哈希与清单不一致")
    with numpy.load(weights_path, allow_pickle=False) as values:
        weights = values["weights"]
        bias = float(values["bias"][0])
    return LinearProbe(weights, bias, manifest)


def _validate_split(features: Any, labels: Any, name: str) -> None:
    """验证特征矩阵与标签向量的基本形状和数值。"""

    numpy = _numpy()
    if features.ndim != 2 or labels.ndim != 1:
        raise ValueError(f"{name}特征必须为二维，标签必须为一维")
    if features.shape[0] != labels.shape[0] or features.shape[0] < 2:
        raise ValueError(f"{name}特征和标签样本数必须一致且至少为 2")
    if not numpy.isfinite(features).all():
        raise ValueError(f"{name}特征包含非有限数")


def _select_threshold(scores: Any, labels: Any) -> tuple[float, float]:
    """在验证集上选择平衡准确率最高的阈值。"""

    numpy = _numpy()
    candidates = numpy.unique(numpy.concatenate(([0.0, 0.5, 1.0], scores)))
    best = (0.5, -1.0)
    for threshold in candidates:
        predictions = scores >= threshold
        positives = labels == 1
        negatives = labels == 0
        true_positive_rate = float((predictions & positives).sum() / max(positives.sum(), 1))
        true_negative_rate = float(((~predictions) & negatives).sum() / max(negatives.sum(), 1))
        balanced_accuracy = (true_positive_rate + true_negative_rate) / 2
        candidate = (float(threshold), balanced_accuracy)
        if candidate[1] > best[1] or (candidate[1] == best[1] and candidate[0] < best[0]):
            best = candidate
    return best


def _write_json_atomic(payload: Mapping[str, Any], path: Path) -> None:
    """在目标目录内原子写入规范 JSON。"""

    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _numpy() -> Any:
    """惰性加载 NumPy，保持基础安装轻量。"""

    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("使用 Probe 需要安装 warden-kernel[probe]") from exc
    return numpy


def _logistic_regression() -> Any:
    """惰性加载 scikit-learn 训练器。"""

    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:
        raise RuntimeError("训练 Probe 需要安装 warden-kernel[probe]") from exc
    return LogisticRegression

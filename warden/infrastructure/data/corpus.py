"""可复现的多主体 Activation Corpus 构建与存储。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType
from typing import Any

from warden.core.domain.datasets import InteractionDataset
from warden.core.domain.models import CaptureTarget, to_primitive
from warden.core.ports.features import ActivationFeatureExtractor


@dataclass(frozen=True, slots=True)
class ActivationCorpus:
    """与原始样本、模型和采集位置绑定的二维表征矩阵集合。

    属性：
        corpus_id: 由数据、模型、采集位置和实际特征内容得到的稳定标识。
        model_id: 生成表征的逻辑模型标识。
        dataset_id: 输入数据集的稳定标识。
        dataset_fingerprint: 输入数据集的规范 SHA-256 指纹。
        sample_ids: 特征矩阵每一行对应的样本标识。
        family_ids: 每一行所属的反事实案例家族。
        splits: 每一行声明的训练、验证或测试切分。
        labels: 每一行的二分类条件标签。
        stream_features: 特征流标识到 ``[sample, feature]`` 矩阵的映射。
        stream_metadata: 特征流的 Agent、层级和组件等公开描述。
    """

    corpus_id: str
    model_id: str
    dataset_id: str
    dataset_fingerprint: str
    sample_ids: Sequence[str]
    family_ids: Sequence[str]
    splits: Sequence[str]
    labels: Sequence[int]
    stream_features: Mapping[str, Any] = field(repr=False)
    stream_metadata: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """固定元数据并校验所有特征流的形状和有限性。"""

        numpy = _numpy()
        for name in ("corpus_id", "model_id", "dataset_id", "dataset_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 必须是非空字符串")
        sample_ids = tuple(str(item) for item in self.sample_ids)
        family_ids = tuple(str(item) for item in self.family_ids)
        splits = tuple(str(item) for item in self.splits)
        labels = tuple(int(item) for item in self.labels)
        count = len(sample_ids)
        if count == 0 or any(len(values) != count for values in (family_ids, splits, labels)):
            raise ValueError("Corpus 样本元数据必须非空且长度一致")
        if len(set(sample_ids)) != count:
            raise ValueError("Corpus sample_ids 不能重复")
        if set(splits) != {"train", "validation", "test"}:
            raise ValueError("Corpus 必须同时包含 train、validation 和 test")
        if set(labels) != {0, 1}:
            raise ValueError("Corpus 必须同时包含标签 0 和 1")
        features: dict[str, Any] = {}
        for key, raw_value in self.stream_features.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("特征流标识必须是非空字符串")
            matrix = numpy.asarray(raw_value, dtype=numpy.float32)
            if matrix.ndim != 2 or matrix.shape[0] != count or matrix.shape[1] < 1:
                raise ValueError(f"特征流 {key} 必须是 [sample, feature] 二维矩阵")
            if not numpy.isfinite(matrix).all():
                raise ValueError(f"特征流 {key} 包含非有限数")
            features[key] = matrix
        if not features:
            raise ValueError("ActivationCorpus 至少需要一个特征流")
        unknown_metadata = set(self.stream_metadata) - set(features)
        if unknown_metadata:
            raise ValueError("stream_metadata 引用了未知特征流")
        object.__setattr__(self, "sample_ids", sample_ids)
        object.__setattr__(self, "family_ids", family_ids)
        object.__setattr__(self, "splits", splits)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "stream_features", MappingProxyType(features))
        object.__setattr__(
            self,
            "stream_metadata",
            MappingProxyType({
                key: MappingProxyType(dict(value))
                for key, value in self.stream_metadata.items()
            }),
        )

    def indices(self, split: str) -> tuple[int, ...]:
        """返回指定切分的稳定样本下标。"""

        if split not in {"train", "validation", "test"}:
            raise ValueError("split 只支持 train、validation 或 test")
        return tuple(index for index, value in enumerate(self.splits) if value == split)


class ActivationCorpusBuilder:
    """使用注入的模型表征提取器构建多主体 Corpus。"""

    def __init__(self, extractor: ActivationFeatureExtractor) -> None:
        """保存提取器；构建器不拥有提取器生命周期。"""

        self._extractor = extractor

    def build(
        self,
        dataset: InteractionDataset,
        targets: Sequence[CaptureTarget],
    ) -> ActivationCorpus:
        """按样本 ID 稳定排序后执行选择性模型前向。

        参数：
            dataset: 已完成家族级三分检查的数据集。
            targets: 显式采集位置；每个位置声明适用 Agent。

        返回：
            所有特征流均按同一行顺序对齐的 Activation Corpus。
        """

        numpy = _numpy()
        resolved_targets = tuple(targets)
        if not resolved_targets:
            raise ValueError("构建 Activation Corpus 至少需要一个 CaptureTarget")
        target_ids = [item.target_id for item in resolved_targets]
        if len(set(target_ids)) != len(target_ids):
            raise ValueError("CaptureTarget.target_id 不能重复")
        dataset_agents = set(dataset.agent_ids)
        for target in resolved_targets:
            unknown = set(target.agent_ids) - dataset_agents
            if unknown:
                raise ValueError(
                    f"CaptureTarget {target.target_id} 引用了未知 Agent：{sorted(unknown)}"
                )
        expected_streams = tuple(
            sorted(
                f"{agent_id}/{target.target_id}"
                for target in resolved_targets
                for agent_id in target.agent_ids
            )
        )
        rows = {key: [] for key in expected_streams}
        samples = tuple(sorted(dataset.samples, key=lambda item: item.sample_id))
        for sample in samples:
            extracted = self._extractor.extract(
                sample_id=sample.sample_id,
                inputs_by_agent=sample.inputs_by_agent,
                targets=resolved_targets,
            )
            missing = sorted(set(expected_streams) - set(extracted))
            extra = sorted(set(extracted) - set(expected_streams))
            if missing or extra:
                raise RuntimeError(
                    f"样本 {sample.sample_id} 的特征流不匹配；缺失={missing}，额外={extra}"
                )
            for key in expected_streams:
                vector = numpy.asarray(extracted[key], dtype=numpy.float32).reshape(-1)
                if vector.size == 0 or not numpy.isfinite(vector).all():
                    raise ValueError(f"样本 {sample.sample_id} 的特征流 {key} 无效")
                rows[key].append(vector)
        matrices: dict[str, Any] = {}
        for key, values in rows.items():
            widths = {int(item.shape[0]) for item in values}
            if len(widths) != 1:
                raise ValueError(f"特征流 {key} 的宽度不一致：{sorted(widths)}")
            matrices[key] = numpy.stack(values)
        target_payload = [to_primitive(item) for item in resolved_targets]
        identity = {
            "dataset_fingerprint": dataset.fingerprint,
            "model_id": self._extractor.model_id,
            "targets": target_payload,
        }
        identity_bytes = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        corpus_hasher = sha256(identity_bytes)
        for key in sorted(matrices):
            matrix = numpy.asarray(matrices[key], dtype="<f4")
            corpus_hasher.update(key.encode("utf-8"))
            corpus_hasher.update(str(matrix.shape).encode("ascii"))
            corpus_hasher.update(matrix.tobytes(order="C"))
        corpus_hash = corpus_hasher.hexdigest()
        metadata = {
            f"{agent_id}/{target.target_id}": {
                "agent_id": agent_id,
                "target_id": target.target_id,
                "module": target.module,
                "layer": target.layer,
                "component": target.component,
                "token_policy": target.token_policy,
            }
            for target in resolved_targets
            for agent_id in target.agent_ids
        }
        return ActivationCorpus(
            corpus_id=f"activation-corpus-{corpus_hash}",
            model_id=self._extractor.model_id,
            dataset_id=dataset.dataset_id,
            dataset_fingerprint=dataset.fingerprint,
            sample_ids=tuple(item.sample_id for item in samples),
            family_ids=tuple(item.family_id for item in samples),
            splits=tuple(item.split for item in samples),
            labels=tuple(item.label for item in samples),
            stream_features=matrices,
            stream_metadata=metadata,
        )


def save_activation_corpus(corpus: ActivationCorpus, destination: Path) -> Path:
    """原子保存矩阵与清单，并返回 Corpus 目录。"""

    numpy = _numpy()
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise FileExistsError(f"Activation Corpus 目标目录必须为空：{root}")
    stream_names = sorted(corpus.stream_features)
    array_names = {stream: f"stream_{index:04d}" for index, stream in enumerate(stream_names)}
    arrays_path = root / "features.npz"
    numpy.savez_compressed(
        arrays_path,
        **{array_names[key]: corpus.stream_features[key] for key in stream_names},
    )
    arrays_hash = sha256(arrays_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "warden.activation-corpus/1",
        "corpus_id": corpus.corpus_id,
        "model_id": corpus.model_id,
        "dataset_id": corpus.dataset_id,
        "dataset_fingerprint": corpus.dataset_fingerprint,
        "sample_ids": list(corpus.sample_ids),
        "family_ids": list(corpus.family_ids),
        "splits": list(corpus.splits),
        "labels": list(corpus.labels),
        "streams": {
            key: {
                "array_name": array_names[key],
                "shape": list(corpus.stream_features[key].shape),
                "dtype": str(corpus.stream_features[key].dtype),
                "metadata": dict(corpus.stream_metadata.get(key, {})),
            }
            for key in stream_names
        },
        "features_sha256": arrays_hash,
    }
    _write_json_atomic(manifest, root / "manifest.json")
    return root


def load_activation_corpus(path: Path) -> ActivationCorpus:
    """校验矩阵哈希和清单后加载 Activation Corpus。"""

    numpy = _numpy()
    root = Path(path)
    manifest_path = root / "manifest.json"
    arrays_path = root / "features.npz"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "warden.activation-corpus/1":
        raise ValueError("Activation Corpus schema_version 不受支持")
    actual_hash = sha256(arrays_path.read_bytes()).hexdigest()
    if manifest.get("features_sha256") != actual_hash:
        raise ValueError("Activation Corpus 特征文件哈希不匹配")
    streams = manifest.get("streams")
    if not isinstance(streams, dict) or not streams:
        raise ValueError("Activation Corpus 清单缺少 streams")
    with numpy.load(arrays_path, allow_pickle=False) as values:
        features = {
            stream: values[entry["array_name"]].copy()
            for stream, entry in streams.items()
        }
    return ActivationCorpus(
        corpus_id=manifest["corpus_id"],
        model_id=manifest["model_id"],
        dataset_id=manifest["dataset_id"],
        dataset_fingerprint=manifest["dataset_fingerprint"],
        sample_ids=tuple(manifest["sample_ids"]),
        family_ids=tuple(manifest["family_ids"]),
        splits=tuple(manifest["splits"]),
        labels=tuple(manifest["labels"]),
        stream_features=features,
        stream_metadata={
            stream: entry.get("metadata", {}) for stream, entry in streams.items()
        },
    )


def _write_json_atomic(payload: Mapping[str, Any], destination: Path) -> None:
    """原子写入不允许 NaN 的规范 JSON。"""

    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=destination.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(destination)


def _numpy() -> Any:
    """惰性加载 NumPy，保持基础安装轻量。"""

    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("Activation Corpus 需要安装 warden-kernel[probe]") from exc
    return numpy

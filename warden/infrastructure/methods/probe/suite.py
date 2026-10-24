"""多主体、逐层 Probe 套件训练与独立测试。"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType
from typing import Any

from warden.infrastructure.data.corpus import ActivationCorpus
from warden.infrastructure.methods.probe.linear import SklearnLinearProbeTrainer


@dataclass(frozen=True, slots=True)
class ProbeSuiteEntry:
    """一个主体范围和采集位置上的 Probe 评价记录。

    属性：
        probe_id: Probe 的稳定标识。
        scope_id: 单主体或联合主体读出范围。
        target_id: 表征采集位置标识。
        stream_ids: 按实际拼接顺序排列的特征流标识。
        validation_balanced_accuracy: 用于层级选择的验证集平衡准确率。
        test_balanced_accuracy: 固定选择后得到的测试集平衡准确率。
        test_family_accuracy: 先按案例家族计算再等权平均的测试准确率。
        test_roc_auc: 独立测试集 ROC-AUC。
        threshold: 仅在验证集上选择的决策阈值。
        artifact_uri: 已训练 Probe 工件目录 URI。
    """

    probe_id: str
    scope_id: str
    target_id: str
    stream_ids: Sequence[str]
    validation_balanced_accuracy: float
    test_balanced_accuracy: float
    test_family_accuracy: float
    test_roc_auc: float
    threshold: float
    artifact_uri: str

    def __post_init__(self) -> None:
        """拒绝缺失标识和越界指标，并固定特征流顺序。"""

        for name in ("probe_id", "scope_id", "target_id", "artifact_uri"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 必须是非空字符串")
        streams = tuple(str(item).strip() for item in self.stream_ids)
        if not streams or any(not item for item in streams) or len(set(streams)) != len(streams):
            raise ValueError("stream_ids 必须非空且不能重复")
        for name in (
            "validation_balanced_accuracy",
            "test_balanced_accuracy",
            "test_family_accuracy",
            "test_roc_auc",
            "threshold",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} 必须是 [0, 1] 内的有限数")
        object.__setattr__(self, "stream_ids", streams)

    def to_dict(self) -> dict[str, Any]:
        """返回 JSON 兼容字典。"""

        return {
            "probe_id": self.probe_id,
            "scope_id": self.scope_id,
            "target_id": self.target_id,
            "stream_ids": list(self.stream_ids),
            "validation_balanced_accuracy": self.validation_balanced_accuracy,
            "test_balanced_accuracy": self.test_balanced_accuracy,
            "test_family_accuracy": self.test_family_accuracy,
            "test_roc_auc": self.test_roc_auc,
            "threshold": self.threshold,
            "artifact_uri": self.artifact_uri,
        }


@dataclass(frozen=True, slots=True)
class ProbeSuiteReport:
    """按验证集选层、仅用测试集报告最终性能的 Probe 套件报告。

    属性：
        schema_version: 报告契约版本。
        corpus_id: 训练和评价所用 Activation Corpus 标识。
        entries: 全部主体范围与采集位置的候选评价记录。
        selected_by_scope: 每个主体范围在验证集上选出的 Probe 标识。
        metadata: 选择规则、随机种子和其他可复现信息。
    """

    schema_version: str
    corpus_id: str
    entries: Sequence[ProbeSuiteEntry]
    selected_by_scope: Mapping[str, str]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """校验选择结果引用并固定条目和选择映射。"""

        if self.schema_version != "warden.probe-suite/1":
            raise ValueError("Probe Suite schema_version 不受支持")
        if not isinstance(self.corpus_id, str) or not self.corpus_id.strip():
            raise ValueError("corpus_id 必须是非空字符串")
        entries = tuple(self.entries)
        if not entries:
            raise ValueError("Probe Suite entries 不能为空")
        probe_ids = {item.probe_id for item in entries}
        if len(probe_ids) != len(entries):
            raise ValueError("Probe Suite probe_id 不能重复")
        selected = dict(self.selected_by_scope)
        if not selected or set(selected.values()) - probe_ids:
            raise ValueError("selected_by_scope 必须引用已存在的 Probe")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(
            self,
            "selected_by_scope",
            MappingProxyType(selected),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        """返回可写入工件清单的普通字典。"""

        selected = set(self.selected_by_scope.values())
        return {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "entries": [
                {**item.to_dict(), "selected_on_validation": item.probe_id in selected}
                for item in self.entries
            ],
            "selected_by_scope": dict(self.selected_by_scope),
            "metadata": dict(self.metadata),
        }


class ProbeSuiteTrainer:
    """在每个主体和联合主体视图上训练逐层线性 Probe。"""

    def __init__(
        self,
        *,
        c: float = 1.0,
        max_iter: int = 2000,
        random_seed: int = 0,
    ) -> None:
        """保存统一训练超参数。

        参数：
            c: Logistic Regression 的 L2 正则倒数。
            max_iter: 单个 Probe 的最大优化迭代数。
            random_seed: 所有候选 Probe 共享的可复现随机种子。
        """

        self._trainer = SklearnLinearProbeTrainer(
            c=c,
            max_iter=max_iter,
            random_seed=random_seed,
        )
        self._random_seed = int(random_seed)

    def fit(self, corpus: ActivationCorpus, destination: Path) -> ProbeSuiteReport:
        """训练单主体和联合主体候选，并按验证集分数选层。

        参数：
            corpus: 已冻结且包含显式三分的 Activation Corpus。
            destination: 空输出目录；每个候选 Probe 写入独立子目录。

        返回：
            包含全部候选诊断和每个范围最终选择的报告。

        说明：
            测试集只参与最终报告，不参与阈值或层级选择。
        """

        numpy = _numpy()
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise FileExistsError(f"Probe Suite 目标目录必须为空：{root}")
        train_indices = numpy.asarray(corpus.indices("train"), dtype=numpy.int64)
        validation_indices = numpy.asarray(corpus.indices("validation"), dtype=numpy.int64)
        test_indices = numpy.asarray(corpus.indices("test"), dtype=numpy.int64)
        labels = numpy.asarray(corpus.labels, dtype=numpy.int64)
        candidates = _candidate_streams(corpus)
        entries: list[ProbeSuiteEntry] = []
        by_scope: dict[str, list[ProbeSuiteEntry]] = defaultdict(list)
        for scope_id, target_id, stream_ids in candidates:
            matrix = numpy.concatenate(
                [corpus.stream_features[stream_id] for stream_id in stream_ids],
                axis=1,
            )
            probe_id = f"probe:{scope_id}:{target_id}"
            probe = self._trainer.fit(
                matrix[train_indices],
                labels[train_indices],
                validation_features=matrix[validation_indices],
                validation_labels=labels[validation_indices],
                metadata={
                    "probe_id": probe_id,
                    "version": "1",
                    "model_id": corpus.model_id,
                    "tensor_ref": "+".join(stream_ids),
                    "positive_label": "risk_condition",
                    "training_fingerprint": corpus.corpus_id,
                    "dataset_id": corpus.dataset_id,
                    "dataset_fingerprint": corpus.dataset_fingerprint,
                    "scope_id": scope_id,
                    "target_id": target_id,
                    "stream_ids": list(stream_ids),
                    "split_policy": "declared_family_disjoint_train_validation_test",
                },
            )
            safe_name = _safe_name(probe_id)
            artifact = self._trainer.save(probe, root / "probes" / safe_name)
            test_scores = probe.score(
                matrix[test_indices],
                sample_ids=tuple(corpus.sample_ids[index] for index in test_indices),
            )
            probabilities = numpy.asarray([item.value for item in test_scores])
            test_labels = labels[test_indices]
            entry = ProbeSuiteEntry(
                probe_id=probe_id,
                scope_id=scope_id,
                target_id=target_id,
                stream_ids=stream_ids,
                validation_balanced_accuracy=float(
                    probe.manifest.metrics["validation_balanced_accuracy"]
                ),
                test_balanced_accuracy=_balanced_accuracy(
                    probabilities,
                    test_labels,
                    probe.manifest.threshold,
                ),
                test_family_accuracy=_family_accuracy(
                    probabilities,
                    test_labels,
                    tuple(corpus.family_ids[index] for index in test_indices),
                    probe.manifest.threshold,
                ),
                test_roc_auc=_roc_auc(probabilities, test_labels),
                threshold=probe.manifest.threshold,
                artifact_uri=artifact.uri,
            )
            entries.append(entry)
            by_scope[scope_id].append(entry)
        selected = {
            scope_id: min(
                values,
                key=lambda item: (
                    -item.validation_balanced_accuracy,
                    item.target_id,
                ),
            ).probe_id
            for scope_id, values in sorted(by_scope.items())
        }
        report = ProbeSuiteReport(
            schema_version="warden.probe-suite/1",
            corpus_id=corpus.corpus_id,
            entries=tuple(entries),
            selected_by_scope=selected,
            metadata={
                "selection_split": "validation",
                "final_evaluation_split": "test",
                "random_seed": self._random_seed,
                "candidate_count": len(entries),
                "test_results_are_not_selection_criteria": True,
            },
        )
        _write_json_atomic(report.to_dict(), root / "report.json")
        return report


def _candidate_streams(
    corpus: ActivationCorpus,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """构造单主体与同位置联合主体候选。"""

    by_target: dict[str, list[str]] = defaultdict(list)
    candidates: list[tuple[str, str, tuple[str, ...]]] = []
    for stream_id in sorted(corpus.stream_features):
        metadata = corpus.stream_metadata.get(stream_id, {})
        agent_id = str(metadata.get("agent_id") or stream_id.split("/", 1)[0])
        target_id = str(metadata.get("target_id") or stream_id.split("/", 1)[1])
        candidates.append((f"agent:{agent_id}", target_id, (stream_id,)))
        by_target[target_id].append(stream_id)
    for target_id, stream_ids in sorted(by_target.items()):
        ordered = tuple(sorted(stream_ids))
        if len(ordered) > 1:
            agents = "+".join(item.split("/", 1)[0] for item in ordered)
            candidates.append((f"joint:{agents}", target_id, ordered))
    return tuple(candidates)


def _balanced_accuracy(scores: Any, labels: Any, threshold: float) -> float:
    """计算二分类平衡准确率。"""

    numpy = _numpy()
    predictions = numpy.asarray(scores) >= float(threshold)
    labels = numpy.asarray(labels)
    positives = labels == 1
    negatives = labels == 0
    true_positive_rate = float((predictions & positives).sum() / positives.sum())
    true_negative_rate = float(((~predictions) & negatives).sum() / negatives.sum())
    return (true_positive_rate + true_negative_rate) / 2


def _roc_auc(scores: Any, labels: Any) -> float:
    """使用 Mann-Whitney 等价形式计算 ROC-AUC，平分并列秩。"""

    numpy = _numpy()
    scores = numpy.asarray(scores, dtype=numpy.float64)
    labels = numpy.asarray(labels, dtype=numpy.int64)
    order = numpy.argsort(scores, kind="mergesort")
    ranks = numpy.empty(scores.shape[0], dtype=numpy.float64)
    start = 0
    while start < order.size:
        stop = start + 1
        while stop < order.size and scores[order[stop]] == scores[order[start]]:
            stop += 1
        ranks[order[start:stop]] = (start + 1 + stop) / 2
        start = stop
    positives = labels == 1
    positive_count = int(positives.sum())
    negative_count = int((~positives).sum())
    if positive_count == 0 or negative_count == 0:
        raise ValueError("ROC-AUC 要求测试集同时包含正负样本")
    value = (
        ranks[positives].sum() - positive_count * (positive_count + 1) / 2
    ) / (positive_count * negative_count)
    return float(value)


def _family_accuracy(
    scores: Any,
    labels: Any,
    family_ids: Sequence[str],
    threshold: float,
) -> float:
    """先在案例家族内计算准确率，再对家族等权平均。"""

    numpy = _numpy()
    scores = numpy.asarray(scores)
    labels = numpy.asarray(labels)
    predictions = scores >= float(threshold)
    if len(family_ids) != labels.shape[0]:
        raise ValueError("family_ids 数量必须与测试样本一致")
    grouped: dict[str, list[bool]] = defaultdict(list)
    for family_id, prediction, label in zip(
        family_ids,
        predictions,
        labels,
        strict=True,
    ):
        grouped[str(family_id)].append(bool(prediction == label))
    return float(numpy.mean([numpy.mean(values) for values in grouped.values()]))


def _safe_name(value: str) -> str:
    """把 Probe 标识转换为跨平台目录名。"""

    slug = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)
    return f"{slug}-{sha256(value.encode('utf-8')).hexdigest()[:8]}"


def _write_json_atomic(payload: Mapping[str, Any], destination: Path) -> None:
    """原子写入 Probe Suite 报告。"""

    destination.parent.mkdir(parents=True, exist_ok=True)
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
    """惰性加载 NumPy。"""

    try:
        import numpy
    except ImportError as exc:
        raise RuntimeError("训练 Probe Suite 需要安装 warden-kernel[probe]") from exc
    return numpy

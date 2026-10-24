"""Activation Corpus 与多主体 Probe Suite 集成测试。"""

from pathlib import Path

import pytest

numpy = pytest.importorskip("numpy")
pytest.importorskip("sklearn")

from warden.core.domain.datasets import InteractionDataset, LabeledInteraction  # noqa: E402
from warden.core.domain.models import CaptureTarget  # noqa: E402
from warden.infrastructure.data import (  # noqa: E402
    ActivationCorpusBuilder,
    load_activation_corpus,
    save_activation_corpus,
)
from warden.infrastructure.methods.probe import ProbeSuiteTrainer  # noqa: E402


class _FakeFeatureExtractor:
    """无需 GPU 的确定性多主体特征提取器。"""

    model_id = "test/fake-whitebox-model"

    def extract(self, *, sample_id, inputs_by_agent, targets):
        """从文本中的 label 标记构造可线性分离表征。"""

        del sample_id
        output = {}
        for target in targets:
            layer = float(target.layer or 0)
            for agent_id in target.agent_ids:
                risky = 1.0 if "risk" in inputs_by_agent[agent_id] else -1.0
                offset = 0.2 if agent_id == "sender" else -0.2
                output[f"{agent_id}/{target.target_id}"] = numpy.asarray(
                    [risky + offset, risky * 0.8, layer / 10],
                    dtype=numpy.float32,
                )
        return output

    def close(self):
        """假提取器没有外部资源。"""


def _dataset() -> InteractionDataset:
    """构造具有家族隔离的三分数据集。"""

    samples = []
    for split_index, split in enumerate(("train", "validation", "test")):
        for repeat in range(4):
            for label in (0, 1):
                condition = "risk" if label else "control"
                samples.append(
                    LabeledInteraction(
                        sample_id=f"{split}-{repeat}-{label}",
                        family_id=f"family-{split_index}-{repeat}-{label}",
                        split=split,
                        label=label,
                        inputs_by_agent={
                            "sender": f"sender {condition} {split} {repeat}",
                            "receiver": f"receiver {condition} {split} {repeat}",
                        },
                    )
                )
    return InteractionDataset("workflow-test", samples)


def test_build_save_load_and_train_probe_suite(tmp_path: Path) -> None:
    """Corpus 哈希、单主体 Probe 与联合 Probe 应形成闭环。"""

    targets = (
        CaptureTarget(
            target_id="layer-04",
            agent_ids=("sender", "receiver"),
            layer=4,
            component="resid_post",
        ),
        CaptureTarget(
            target_id="layer-08",
            agent_ids=("sender", "receiver"),
            layer=8,
            component="resid_post",
        ),
    )
    corpus = ActivationCorpusBuilder(_FakeFeatureExtractor()).build(_dataset(), targets)
    save_activation_corpus(corpus, tmp_path / "corpus")
    restored = load_activation_corpus(tmp_path / "corpus")
    assert restored.corpus_id == corpus.corpus_id
    assert set(restored.stream_features) == {
        "receiver/layer-04",
        "receiver/layer-08",
        "sender/layer-04",
        "sender/layer-08",
    }
    report = ProbeSuiteTrainer(random_seed=17).fit(restored, tmp_path / "suite")
    assert len(report.entries) == 6
    assert set(report.selected_by_scope) == {
        "agent:receiver",
        "agent:sender",
        "joint:receiver+sender",
    }
    selected = set(report.selected_by_scope.values())
    assert all(
        item.test_balanced_accuracy == pytest.approx(1.0)
        for item in report.entries
        if item.probe_id in selected
    )
    assert (tmp_path / "suite" / "report.json").is_file()


def test_corpus_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    """特征文件被修改后不得继续加载。"""

    target = CaptureTarget(
        target_id="layer-04",
        agent_ids=("sender", "receiver"),
        layer=4,
    )
    corpus = ActivationCorpusBuilder(_FakeFeatureExtractor()).build(_dataset(), (target,))
    root = save_activation_corpus(corpus, tmp_path / "corpus")
    with (root / "features.npz").open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ValueError, match="哈希不匹配"):
        load_activation_corpus(root)

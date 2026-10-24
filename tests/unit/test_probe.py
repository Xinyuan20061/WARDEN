"""线性 Probe 参考实现测试。"""

import pytest

numpy = pytest.importorskip("numpy")
pytest.importorskip("sklearn")

from warden.infrastructure.methods.probe.linear import (  # noqa: E402
    SklearnLinearProbeTrainer,
    load_linear_probe,
)
from warden.infrastructure.storage.resources import discover_resource_manifests  # noqa: E402


def test_linear_probe_train_save_load_roundtrip(tmp_path) -> None:
    """训练、清单、哈希校验和评分形成完整闭环。"""

    features = numpy.asarray(
        [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]],
        dtype=numpy.float64,
    )
    labels = numpy.asarray([0, 0, 1, 1])
    trainer = SklearnLinearProbeTrainer(random_seed=7)
    probe = trainer.fit(
        features,
        labels,
        validation_features=features,
        validation_labels=labels,
        metadata={
            "probe_id": "test-probe",
            "version": "1",
            "model_id": "test-model",
            "tensor_ref": "layer:1:resid_post",
            "positive_label": "harmful",
            "training_fingerprint": "test-only",
        },
    )
    artifact = trainer.save(probe, tmp_path / "probe")
    restored = load_linear_probe(tmp_path / "probe")
    scores = restored.score(features, sample_ids=("a", "b", "c", "d"))
    assert artifact.kind == "probe"
    assert len(scores) == 4
    assert scores[0].value < scores[-1].value
    resources = discover_resource_manifests(tmp_path / "probe")
    assert len(resources) == 1
    assert resources[0].resource_id == "test-probe"
    assert resources[0].artifact is not None

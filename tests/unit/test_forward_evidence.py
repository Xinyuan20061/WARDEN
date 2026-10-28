"""从真实保存数组复算前向比较；损坏时必须明确失败。"""

import numpy as np
import pytest

from warden.infrastructure.storage.filesystem import FileArtifactRepository
from warden.infrastructure.storage.forward_evidence import (
    compare_forward_evidence,
    save_forward_evidence,
)


def test_comparison_roundtrip_recomputes_from_arrays(tmp_path):
    repository = FileArtifactRepository(tmp_path)
    before = np.array([1., 2., 3.])
    ref = save_forward_evidence(repository, before=before,
                                interventions={"leace": np.array([1., 2., 5.])}, replay=before,
                                metadata={"run_id": "r", "model_revision": "v",
                                          "tensor_ref": "layer:1", "input_sha256": "sha"})
    result = compare_forward_evidence(repository, ref)
    assert result["replay_equal"]
    assert result["logits_l2"]["leace"] == 2.
    assert result["vocabulary_size"] == 3
    next(tmp_path.rglob("*.bin")).write_bytes(b"broken")
    with pytest.raises(ValueError, match="哈希"):
        compare_forward_evidence(repository, ref)


def test_nonfinite_logits_rejected(tmp_path):
    with pytest.raises(ValueError, match="非有限"):
        save_forward_evidence(FileArtifactRepository(tmp_path), before=np.array([0.]),
                              interventions={"patch": np.array([float("nan")])},
                              replay=np.array([0.]), metadata={"run_id":"r", "model_revision":"m",
                                                             "tensor_ref":"r", "input_sha256":"h"})

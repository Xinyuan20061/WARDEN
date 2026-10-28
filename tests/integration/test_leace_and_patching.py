"""官方 LEACE 数值一致性与 StegoPot 单位置干预合同。"""

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("concept_erasure")
pytest.importorskip("stegopot")

from concept_erasure import LeaceEraser  # noqa: E402
from stegopot.domain.model.intervention_runtime import InterventionContext  # noqa: E402
from stegopot.domain.model.reference import TensorRef  # noqa: E402

from warden.infrastructure.adapters.stegopot_interventions import (  # noqa: E402
    build_leace_intervention,
    build_paired_patch,
)
from warden.infrastructure.methods.intervention.leace import LeaceTransform  # noqa: E402


def test_official_leace_numerics_roundtrip_and_fit_boundary(tmp_path):
    generator = torch.Generator().manual_seed(17)
    x = torch.randn(128, 8, generator=generator, dtype=torch.float64)
    y = (x[:, 0] > 0).double()
    ref = TensorRef(layer=1, component="resid_post", token=-1)
    metadata = {"model_id": "tiny", "model_revision": "frozen", "tensor_ref": ref.key,
                "split_sha256": "train-fingerprint", "label_semantics": "decoded_directive",
                "token_policy": "last_token"}
    transform = LeaceTransform.fit(x, y, split="train", metadata=metadata)
    expected = LeaceEraser.fit(x, y[:, None])(x)
    assert torch.allclose(transform.apply(x), expected, atol=1e-10)
    restored = LeaceTransform.load(transform.save(tmp_path / "leace"))
    assert torch.allclose(restored.apply(x), expected, atol=1e-10)
    intervention = build_leace_intervention(restored, target=ref, model_revision="frozen")
    assert torch.allclose(intervention.operator(x, InterventionContext("r", ref)), expected)
    with pytest.raises(ValueError, match="train"):
        LeaceTransform.fit(x, y, split="test", metadata=metadata)
    with pytest.raises(ValueError, match="不一致"):
        build_leace_intervention(restored, target=ref, model_revision="different")


def test_patch_rejects_alignment_and_actually_replaces_value():
    ref = TensorRef(layer=0, component="resid_post", token=-1)
    alignment = {"model_revision": "m", "tokenizer_revision": "t",
                 "token_ids": [1, 2], "target_key": ref.key}
    donor = torch.ones(1, 8)
    patch = build_paired_patch(donor=donor, target=ref,
                              donor_alignment=alignment, recipient_alignment=alignment)
    donor.zero_()
    value = torch.zeros(1, 8)
    assert patch.operator(value, InterventionContext("r", ref)).sum().item() == 8
    with pytest.raises(ValueError, match="shape"):
        patch.operator(torch.zeros(1, 9), InterventionContext("r", ref))
    with pytest.raises(ValueError, match="对齐"):
        build_paired_patch(donor=donor, target=ref, donor_alignment=alignment,
                           recipient_alignment={**alignment, "token_ids": [1, 3]})

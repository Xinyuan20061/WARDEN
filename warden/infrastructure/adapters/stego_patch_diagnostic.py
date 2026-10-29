"""只在固定开发消息上核验真实 Patch 对照；不充当 held-out 防御比较。"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from warden.infrastructure.adapters.huggingface import build_huggingface_runtime
from warden.infrastructure.adapters.live_steganography import load_live_config
from warden.infrastructure.adapters.stego_diagnostics import receiver_text
from warden.infrastructure.adapters.stego_readout import parse_bit
from warden.infrastructure.adapters.stegopot_interventions import build_paired_patch


def diagnose(config_path: Path, destination: Path):
    """保存 donor/recipient 身份、真实激活、应用与续算结果；不读取 test 文件内容。"""
    import numpy as np
    import torch
    from stegopot.domain.model.reference import TensorRef, TracePolicy
    from stegopot.domain.model.runtime import GenerationConfig, ModelInput
    from transformers import AutoTokenizer

    config, model, _, _ = load_live_config(config_path)
    destination.mkdir(parents=True, exist_ok=False)
    tokenizer = AutoTokenizer.from_pretrained(model.model_path, local_files_only=True)
    runtime = build_huggingface_runtime(model)
    rows = []

    def prompt(word):
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": receiver_text(word)}],
            tokenize=False,
            add_generation_prompt=True,
        )

    try:
        for recipient_word, donor_word in (("RED", "BLUE"), ("BLUE", "RED")):
            recipient, alternate = prompt(recipient_word), prompt(donor_word)
            for method in (
                "noop",
                "identity_patch",
                "activation_patch",
                "matched_random_patch",
                "irrelevant_location_patch",
                "swapped_donor_recipient",
            ):
                ref = TensorRef(
                    layer=0 if method == "irrelevant_location_patch" else config["layer"],
                    component="resid_post",
                    token=-1,
                )
                policy = TracePolicy(refs=(ref,), store="cpu")
                current = alternate if method == "swapped_donor_recipient" else recipient
                source = (
                    recipient
                    if method in {"identity_patch", "swapped_donor_recipient"}
                    else alternate
                )
                donor = runtime.forward(ModelInput(source), policy=policy).trace.get(ref).value
                original = runtime.forward(ModelInput(current), policy=policy).trace.get(ref).value
                if method == "matched_random_patch":
                    rng = torch.Generator().manual_seed(config["seed"])
                    random = torch.randn(donor.shape, generator=rng, dtype=donor.dtype)
                    donor = random / random.norm() * donor.norm()
                alignment = {
                    "model_revision": model.revision,
                    "tokenizer_revision": model.revision,
                    "target_key": ref.key,
                }
                patch = (
                    None
                    if method == "noop"
                    else build_paired_patch(
                        donor=donor,
                        target=ref,
                        donor_alignment={**alignment, "token_ids": tokenizer.encode(source)},
                        recipient_alignment={**alignment, "token_ids": tokenizer.encode(current)},
                    )
                )
                session = runtime.generate_session(
                    ModelInput(current),
                    policy=policy,
                    config=GenerationConfig(
                        max_new_tokens=4,
                        seed=config["seed"],
                        stop_token_ids=(tokenizer.eos_token_id,),
                    ),
                )
                applied = False
                try:
                    first = True
                    while not session.finished:
                        step = session.forward_next()
                        if first and patch is not None:
                            step = step.apply((patch,))
                            applied = True
                        session.commit(step.sample())
                        first = False
                    generated = session.result()
                    normalized = tokenizer.decode(generated.token_ids, skip_special_tokens=True)
                finally:
                    session.close()
                name = f"{recipient_word}-{method}.npz"
                np.savez_compressed(
                    destination / name, donor=donor.cpu().numpy(), recipient=original.cpu().numpy()
                )
                rows.append(
                    {
                        "method": method,
                        "recipient_word": recipient_word,
                        "donor_word": donor_word,
                        "actual_recipient_prompt_sha256": sha256(current.encode()).hexdigest(),
                        "actual_donor_prompt_sha256": sha256(source.encode()).hexdigest(),
                        "recipient_tokens": tokenizer.encode(current),
                        "donor_tokens": tokenizer.encode(source),
                        "target_key": ref.key,
                        "shape": list(donor.shape),
                        "applied": applied,
                        "model_revision": model.revision,
                        "tokenizer_revision": model.revision,
                        "raw_output": generated.text,
                        "strict_bit_valid": parse_bit(normalized).value is not None,
                        "normalized_output": normalized,
                        "artifact": name,
                    }
                )
                (destination / "restricted-patches.json").write_text(
                    json.dumps(rows, indent=2), encoding="utf-8"
                )
        public = {
            "schema_version": "warden.patch-diagnostic/1",
            "purpose": "validation_controls_only",
            "used_heldout_cases": False,
            "model_revision": model.revision,
            "rows": [
                {
                    k: v
                    for k, v in r.items()
                    if k
                    not in {
                        "recipient_word",
                        "donor_word",
                        "raw_output",
                        "normalized_output",
                        "recipient_tokens",
                        "donor_tokens",
                    }
                }
                for r in rows
            ],
            "files_sha256": {
                p.name: sha256(p.read_bytes()).hexdigest()
                for p in destination.iterdir()
                if p.is_file()
            },
        }
        (destination / "summary.json").write_text(json.dumps(public, indent=2), encoding="utf-8")
        print(json.dumps({"cases": len(rows), "applied": sum(r["applied"] for r in rows)}))
    finally:
        runtime.close()

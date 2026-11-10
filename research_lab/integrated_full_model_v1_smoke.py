"""Integrated full-model v1 contract smoke. Zero ML imports and zero model calls."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from .integrated_full_model_v1_contract import (
    CHECKPOINT_SCHEMA,
    COMPONENTS,
    fingerprint,
    inspect_checkpoint,
    make_example_spec,
    validate_against_stage1,
)


def main() -> int:
    spec = make_example_spec()
    stage1 = SimpleNamespace(
        latent_dim=128, rssm_deter_dim=256, rssm_stoch_dim=32,
        action_dim=2, encoder_max_steps=512,
    )
    validate_against_stage1(spec, stage1)
    with tempfile.TemporaryDirectory(prefix="hos-integrated-contract-fixture-") as tmp:
        root = Path(tmp)
        # Deliberately NOT real weights; only test the metadata SHA gate.
        fake = b"CONTRACT_METADATA_FIXTURE_NOT_TENSORS"
        (root / "weights.safetensors").write_bytes(fake)
        (root / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        manifest = {
            "schema": CHECKPOINT_SCHEMA,
            "model_spec_sha256": fingerprint(spec),
            "weights_file": "weights.safetensors",
            "weights_sha256": hashlib.sha256(fake).hexdigest(),
            "components": list(COMPONENTS),
            "training_status": "UNTRAINED_ASSEMBLY",
            "source_commit": "a" * 40,
            "run_id": None,
            "approval_id": None,
            "synthetic_data_sha256": None,
            "generator_sha256": None,
            "normalization_sha256": None,
            "global_step": 0,
            "evidence": {
                "asof_dataset_verified": False,
                "independent_review": False,
            },
        }
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        receipt = inspect_checkpoint(root)
    print(json.dumps({
        "status": "PASS_INTEGRATED_CONTRACT_METADATA_ONLY",
        "integrated_components": receipt["components"],
        "horizons_hours": spec["horizons_hours"],
        "targets": [x["name"] for x in spec["targets"]],
        "training": False,
        "model_forward": False,
        "checkpoint_kind": receipt["training_status"],
        "weights_are_real": False,
        "model_pretrained": False,
        "gpu_spend": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

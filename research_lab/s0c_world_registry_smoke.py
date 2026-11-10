"""S0c zero-data registry smoke. Synthetic metadata placeholders only."""
from __future__ import annotations

import json

from .s0c_world_registry import build_registry, validate_job_scope


def main() -> int:
    partitions = ("train", "train", "development", "validation", "ood_blind")
    rows = []
    for i, partition in enumerate(partitions):
        rows.append({
            "world_id": f"fixture-{i}", "partition": partition,
            "hospital_id": f"H{i}", "generator_family": "v041",
            "observation_profile": "v041", "policy_family": "reference",
            "structure_family": "blind" if i == 4 else "known",
            "seed_group": f"independent-{i}",
            "source_manifest_sha256": f"{i + 1:064x}",
            "observation_manifest_sha256": f"{i + 10:064x}",
            "action_manifest_sha256": f"{i + 20:064x}",
            "source_clock": "fixed_utc_plus_01_no_dst",
            "mechanism_tags": ["reference"],
            "readable_by_lab": partition != "ood_blind",
        })
    registry = build_registry(rows, freeze_id="fixture-s0c")
    scope = validate_job_scope(registry, ["fixture-0"], "train")
    assert scope["training_authorized"] is False
    assert "fixture-4" not in json.dumps(registry)
    print(json.dumps({
        "status": "PASS_S0C_METADATA_REGISTRY_ONLY",
        "worlds": len(partitions),
        "blind_world_count": registry["blind_world_count"],
        "blind_holdout_opened": False,
        "training": False,
        "model_forward": False,
        "simulation": False,
        "gpu_spend": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

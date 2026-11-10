"""S0c metadata-only smoke: fabricated registry, no generator or ML dependencies."""
from __future__ import annotations

import json

from .integrated_full_model_v1_contract import make_v041_synthetic_spec
from .s0c_synthetic_registry import compile_index


def main() -> int:
    worlds = []
    for label, partition, seed, shape in (
        ("TRAIN", "train", 101, "a"),
        ("OOD", "validation", 102, "b"),
        ("HIDDEN", "test", 103, "c"),
    ):
        worlds.append({
            "world_id": f"W_{label}", "structure_sha256": shape * 64,
            "replicate": 0, "config": {
                "partition": partition, "hospital_id": f"H_{label}",
                "seed": seed, "days": 365, "mechanism_family": "v041",
                "observation": {}, "dynamics": {
                    "arrivals": "v041", "discharges": "v041", "staffing": "v041",
                },
                "documentary": {
                    "staff_forecasts": "v041", "downstream_confirmation": "v041",
                },
            },
        })
    index, summary = compile_index(
        {"schema_version": "0.1", "plan": {"split_axis": "structure"}, "worlds": worlds},
        model_spec=make_v041_synthetic_spec(),
        temporal_dev_days=28, embargo_hours=24,
    )
    assert len(index["partitions"]) == 3
    assert "W_HIDDEN" not in json.dumps(index)
    print(json.dumps({
        "status": "PASS_S0C_METADATA_ONLY_SMOKE",
        "train_worlds": summary["train_worlds"],
        "development_ood_worlds": summary["development_ood_worlds"],
        "test_world_count": summary["reserved_test_world_count"],
        "test_world_identifiers_exposed": False,
        "model_forward": False,
        "training": False,
        "simulation": False,
        "gpu_spend": 0,
        "source": "FABRICATED_REGISTRY_NOT_CANONICAL_VALIDATION",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

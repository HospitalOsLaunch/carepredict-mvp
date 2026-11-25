"""Run the frozen, paired HospitalOS model on public_features from its research pipeline."""

import argparse
import gzip
import json
from pathlib import Path

import numpy as np

EVIDENCE = Path(__file__).resolve().parents[2] / "evidence" / "action_effects"
ACTIONS = ("none", "cleaning", "transport")
HORIZONS = (6, 12, 24)


def predict_effect(features, action, weights):
    """Estimate intervention minus no additional reinforcement, on the training schedule."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    x = np.asarray(features, dtype=float)
    mean = np.asarray(weights["mean"])
    if x.shape != mean.shape or not np.isfinite(x).all():
        raise ValueError(f"expected one vector of {len(mean)} finite public features")
    offsets = np.zeros((len(HORIZONS), 2))
    if action != "none":
        scaled = (x - mean) / weights["scale"]
        all_effects = np.asarray(weights["coef"]) @ scaled + weights["intercept"]
        index = ACTIONS.index(action) - 1
        offsets = all_effects.reshape(2, len(HORIZONS), 2)[index]
        offsets[0] = 0.0  # The reinforcement only starts at H6.
    return {
        "scope": "synthetic_four_unit_hospital",
        "reference": "no_additional_reinforcement",
        "action": action,
        "staff_hours": 0 if action == "none" else 16,
        "effects": [
            {"horizon_hours": h, "delta_wait_patient_minutes": float(w),
             "delta_uncovered_care_minutes": float(c)}
            for h, (w, c) in zip(HORIZONS, offsets, strict=True)
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--features", type=Path, help="JSON array from run.public_features")
    source.add_argument("--demo", action="store_true", help="First archived TEST episode")
    parser.add_argument("--action", choices=ACTIONS, required=True)
    parser.add_argument("--weights", type=Path, default=EVIDENCE / "effect_model.json")
    args = parser.parse_args()
    if args.demo:
        with gzip.open(EVIDENCE / "examples.json.gz", "rt") as archive:
            row = next(row for row in json.load(archive) if row["split"] == "TEST")
        features = row["features"]
    else:
        features = json.loads(args.features.read_text())
    weights = json.loads(args.weights.read_text())
    print(json.dumps(predict_effect(features, args.action, weights), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

"""Paired, structure-clustered analysis of the preregistered correction holdout."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from analyse import interval


def analyse(root, expected=24):
    paths = sorted(root.glob("structure_*.json"))
    if len(paths) != expected:
        raise ValueError(f"Expected {expected} files, found {len(paths)}")
    states, outcomes, decisions = [], [], []
    for path in paths:
        record = json.loads(path.read_text())
        for future in record["futures"]:
            common = dict(structure=record["structure"], delay=record["delay"], future=future["realisation"])
            states.extend(dict(**common, **s) for s in future["states"])
            for arm, result in future["arms"].items():
                outcomes.append(dict(**common, arm=arm, **{k: result[k] for k in (
                    "wait_patient_min", "uncovered_care_min", "staff_hours", "terminal_queue", "rejected")}))
                decisions.extend(dict(**common, arm=arm, **v) for v in result["decisions"])
    s, o, d = pd.DataFrame(states), pd.DataFrame(outcomes), pd.DataFrame(decisions)
    result = dict(states=[], outcomes=[], decisions=[])
    for (delay, metric), frame in s.groupby(["delay", "metric"]):
        errors = {name: (frame[name] - frame.truth).abs() for name in ("legacy", "public", "service_only", "lifecycle")}
        row = dict(delay=int(delay), metric=metric, mae={k: float(v.mean()) for k, v in errors.items()})
        for ref, target in (("legacy", "public"), ("public", "lifecycle"), ("service_only", "lifecycle")):
            row[f"{ref}_minus_{target}"] = interval(frame.assign(gain=errors[ref] - errors[target]), "gain")
        result["states"].append(row)
    for delay, frame in o.groupby("delay"):
        for metric in ("wait_patient_min", "uncovered_care_min", "staff_hours", "terminal_queue", "rejected"):
            pivot = frame.pivot(index=["structure", "future"], columns="arm", values=metric).reset_index()
            row = dict(delay=int(delay), metric=metric, means={a: float(pivot[a].mean()) for a in ("legacy", "public", "lifecycle", "true_state")})
            for ref, target in (("legacy", "public"), ("public", "lifecycle"), ("public", "true_state")):
                row[f"{ref}_minus_{target}"] = interval(pivot.assign(gain=pivot[ref] - pivot[target]), "gain")
            result["outcomes"].append(row)
    for delay, frame in d.groupby("delay"):
        pivot = frame.pivot(index=["structure", "future", "tick"], columns="arm", values="action")
        row = dict(delay=int(delay), decisions_per_arm=len(pivot),
                   lifecycle_changed=int((pivot.public != pivot.lifecycle).sum()),
                   oracle_changed=int((pivot.public != pivot.true_state).sum()),
                   legacy_changed=int((pivot.public != pivot.legacy).sum()),
                   actions={arm: part.action.value_counts().to_dict() for arm, part in frame.groupby("arm")},
                   positive_predicted_gain={arm: int((part.predicted_gain_vs_none > 1e-6).sum()) for arm, part in frame.groupby("arm")})
        result["decisions"].append(row)
    (root / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    s.to_csv(root / "states.csv", index=False)
    o.to_csv(root / "outcomes.csv", index=False)
    d.to_csv(root / "decisions.csv", index=False)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--expected", type=int, default=24)
    args = parser.parse_args()
    analyse(args.directory, args.expected)

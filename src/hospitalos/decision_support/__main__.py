"""Local command (no network, no hospital system).

    PYTHONPATH=src:. python3 -m hospitalos.decision_support recommend tests/decision_support/fixtures/nominal_auto.json
    PYTHONPATH=src:. python3 -m hospitalos.decision_support simulate tests/decision_support/fixtures/scenario_x1x2.json
    PYTHONPATH=src:. python3 -m hospitalos.decision_support export --out evidence/decision_support/results
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import Recommendation, ScenarioLocks
from .planner import Settings, recommend, simulate
from .snapshot import load_json, snapshot_from_fixture

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "decision_support" / "fixtures"


def summary(r: Recommendation) -> dict[str, object]:
    out: dict[str, object] = {
        "recommendation_id": r.recommendation_id, "status": r.status, "mode": r.mode,
        "scientific_status": r.scientific_status, "reasons": list(r.reasons),
        "diagnostics": list(r.diagnostics), "approvable": r.approvable,
    }
    if r.bundle is not None:
        ev = {e.plan.plan_id: e for e in r.bundle.evaluations}
        for name, pid in (("baseline", r.baseline_plan_id), ("primary", r.primary_plan_id),
                          ("alternative", r.alternative_plan_id), ("locked", r.locked_plan_id)):
            if pid:
                e = ev[pid]
                out[name] = {"plan_id": pid, "label": e.plan.label,
                             "actions": [a.action_id for a in e.plan.actions],
                             "metrics": e.metrics.model_dump(mode="json"),
                             "violations": list(e.violations), "warnings": list(e.warnings),
                             "conditional_on": list(e.conditional_on)}
        out["search"] = r.bundle.search.model_dump(mode="json")
    return out


def run_scenario(path: Path, settings: Settings) -> Recommendation:
    scenario = load_json(path)
    snapshot = snapshot_from_fixture(path.parent / scenario["fixture"])
    return simulate(snapshot, ScenarioLocks.model_validate(scenario["locks"]), settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hospitalos.decision_support")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("recommend")
    rec.add_argument("fixture", type=Path)
    rec.add_argument("--full", action="store_true")
    sim = sub.add_parser("simulate")
    sim.add_argument("scenario", type=Path)
    sim.add_argument("--full", action="store_true")
    exp = sub.add_parser("export")
    exp.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    settings = Settings.default()
    if args.cmd == "recommend":
        r = recommend(snapshot_from_fixture(args.fixture), settings)
    elif args.cmd == "simulate":
        r = run_scenario(args.scenario, settings)
    else:
        from .export import export_all

        manifest = export_all(args.out, settings)
        json.dump(manifest, sys.stdout, indent=1)
        print()
        return 0
    payload = r.model_dump(mode="json") if args.full else summary(r)
    json.dump(payload, sys.stdout, indent=1, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

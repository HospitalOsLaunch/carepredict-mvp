"""Generate the 24-hour plan screen's demonstration data by running the REAL decision engine.

    PYTHONPATH=src:. python web/dev/build_decision_fixtures.py

Output: web/src/fixtures/decision.json. Nothing is hand-written. To keep the bundle small, the
hourly trajectories of plans the screen does not display are dropped; every compacted document
records the SHA-256 of the full engine output it comes from and which trajectories were dropped.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hospitalos.decision_support import ENGINE_VERSION
from hospitalos.decision_support.contracts import Recommendation, ScenarioLocks
from hospitalos.decision_support.planner import Settings, recommend, simulate
from hospitalos.decision_support.snapshot import load_json, snapshot_from_fixture

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "tests" / "decision_support" / "fixtures"
OUT = ROOT / "web" / "src" / "fixtures" / "decision.json"
UNITS = [
    ("nominal_auto", "Médecine polyvalente (fictive) — tension"),
    ("no_action", "Médecine polyvalente (fictive) — calme"),
    ("insufficient_data", "Médecine polyvalente (fictive) — planning incomplet"),
]
MANUAL = [
    ("x1x2", "X1 sortie 10:00, X2 prolongé de 4 h, compléments jusqu'à demain 20:00"),
    ("hypothesis", "Hypothèse : sortie de S04 sans autorisation à 13:00"),
    ("impossible", "S01 verrouillé à 16:00, transport entièrement engagé ailleurs"),
]


def compact(r: Recommendation) -> dict[str, Any]:
    full = r.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(full, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    shown = {
        r.baseline_plan_id, r.primary_plan_id, r.alternative_plan_id, r.locked_plan_id,
    } - {None}
    dropped = []
    if full["bundle"]:
        for e in full["bundle"]["evaluations"]:
            if e["plan"]["plan_id"] not in shown:
                e["trajectory"] = []
                dropped.append(e["plan"]["plan_id"])
    return {"source_sha256": digest, "trajectories_dropped_for": dropped, "recommendation": full}


def main() -> None:
    settings = Settings.default()
    units = []
    for unit, name in UNITS:
        snapshot = snapshot_from_fixture(FX / f"{unit}.json")
        units.append({
            "id": unit, "name": name, "snapshot": snapshot.model_dump(mode="json"),
            **compact(recommend(snapshot, settings)),
        })
    nominal = snapshot_from_fixture(FX / "nominal_auto.json")
    manual = []
    for key, label in MANUAL:
        scenario = load_json(FX / f"scenario_{key}.json")
        locks = ScenarioLocks.model_validate(scenario["locks"])
        manual.append({"id": key, "unit": "nominal_auto", "label": label,
                       "locks": scenario["locks"], **compact(simulate(nominal, locks, settings))})
    body = {
        "generated_by": "web/dev/build_decision_fixtures.py",
        "engine_version": ENGINE_VERSION,
        "synthetic": True,
        "units": units,
        "manual": manual,
        "events": load_json(ROOT / "web" / "decision" / "demo_events.json"),
    }
    OUT.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{OUT.relative_to(ROOT)} {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()

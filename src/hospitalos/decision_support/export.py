"""Export versioned results actually produced by the engine (cockpit data + evidence).

Every file is generated from fixtures by the code; nothing is typed in by hand. Out-of-sample
evaluation uses seeds disjoint from the selection seeds (T23) and is labelled as model-based;
the private-truth replay is labelled as an evaluation-only oracle.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import ENGINE_VERSION
from .contracts import PublicSnapshot, Recommendation, ScenarioLocks
from .planner import Settings, _config, recommend, resolve_horizon, simulate
from .reference_forecaster import ForecastConfig, PrivateOracle, PrivateTruth
from .snapshot import load_json, snapshot_from_fixture

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "decision_support" / "fixtures"


class SeedReuseError(ValueError):
    pass


def evaluate_out_of_sample(
    snapshot: PublicSnapshot, recommendation: Recommendation, settings: Settings
) -> dict[str, Any]:
    selection = set(settings.profile["forecast"]["selection_seeds"])
    evaluation = tuple(settings.profile["forecast"]["evaluation_seeds"])
    if selection & set(evaluation):
        raise SeedReuseError("evaluation seeds overlap selection seeds")
    assert recommendation.bundle is not None
    start, _, hours = resolve_horizon(snapshot, settings.profile, recommendation.locks)
    config = ForecastConfig(settings.profile, settings.score, evaluation, start, hours)
    out: dict[str, Any] = {
        "label": "model_based_out_of_sample_seeds_not_real_world_performance",
        "selection_seeds": sorted(selection),
        "evaluation_seeds": list(evaluation),
        "recommendation_id": recommendation.recommendation_id,
        "plans": {},
    }
    plans = {e.plan.plan_id: e.plan for e in recommendation.bundle.evaluations}
    for role, pid in (("baseline", recommendation.baseline_plan_id),
                      ("primary", recommendation.primary_plan_id)):
        if pid:
            e = settings.backend.forecast(snapshot, plans[pid], config)
            out["plans"][role] = {"plan_id": pid,
                                  "metrics": e.metrics.model_dump(mode="json")}
    return out


def oracle_replay(
    snapshot: PublicSnapshot, recommendation: Recommendation, truth: PrivateTruth,
    settings: Settings,
) -> dict[str, Any]:
    assert recommendation.bundle is not None
    start, _, hours = resolve_horizon(snapshot, settings.profile, recommendation.locks)
    config = _config(settings, start, hours)
    oracle = PrivateOracle(truth)
    plans = {e.plan.plan_id: e.plan for e in recommendation.bundle.evaluations}
    out: dict[str, Any] = {"label": "private_oracle_evaluation_only_not_a_product_backend",
                           "backend": oracle.info().model_dump(), "plans": {}}
    for role, pid in (("baseline", recommendation.baseline_plan_id),
                      ("primary", recommendation.primary_plan_id)):
        if pid:
            run = oracle.outcome(snapshot, plans[pid], config)
            out["plans"][role] = {
                "plan_id": pid,
                "uncovered_care_minutes": sum(run.uncovered_unit) + sum(run.uncovered_waiting),
                "waiting_patient_hours": sum(run.waiting),
                "departures": run.departures,
                "admissions": run.admissions,
            }
    return out


def _write(out: Path, name: str, body: Any) -> dict[str, str]:
    text = json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False, default=str) + "\n"
    (out / name).write_text(text)
    return {"file": name, "sha256": hashlib.sha256(text.encode()).hexdigest()}


def export_all(out: Path, settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or Settings.default()
    out.mkdir(parents=True, exist_ok=True)
    files = []
    nominal = snapshot_from_fixture(FIXTURES / "nominal_auto.json")
    files.append(_write(out, "snapshot_nominal.json", nominal.model_dump(mode="json")))
    auto = recommend(nominal, settings)
    files.append(_write(out, "reco_auto_nominal.json", auto.model_dump(mode="json")))
    for name in ("no_action", "insufficient_data"):
        r = recommend(snapshot_from_fixture(FIXTURES / f"{name}.json"), settings)
        files.append(_write(out, f"reco_auto_{name}.json", r.model_dump(mode="json")))
    for name in ("x1x2", "hypothesis", "impossible", "contradictory"):
        sc = load_json(FIXTURES / f"scenario_{name}.json")
        r = simulate(nominal, ScenarioLocks.model_validate(sc["locks"]), settings)
        files.append(_write(out, f"reco_manual_{name}.json", r.model_dump(mode="json")))
    sweep = []
    base = load_json(FIXTURES / "scenario_x1x2.json")["locks"]
    for t in range(0, 9):
        locks = json.loads(json.dumps(base))
        locks["locks"][1]["extension_hours"] = t
        locks["search_complements"] = False
        r = simulate(nominal, ScenarioLocks.model_validate(locks), settings)
        assert r.bundle is not None
        ev = {e.plan.plan_id: e for e in r.bundle.evaluations}
        m = ev[r.locked_plan_id].metrics if r.locked_plan_id else None
        sweep.append({"t_hours": t, "status": r.status, "recommendation_id": r.recommendation_id,
                      "locked_metrics": m.model_dump(mode="json") if m else None})
    files.append(_write(out, "sweep_x2_extension_t.json",
                        {"label": "locked scenario only (no complements), X2=S02, t=0..8",
                         "points": sweep}))
    files.append(_write(out, "evaluation_out_of_sample_nominal.json",
                        evaluate_out_of_sample(nominal, auto, settings)))
    truth = PrivateTruth.from_fixture(load_json(FIXTURES / "nominal_auto.json")["private_truth"])
    files.append(_write(out, "oracle_replay_nominal.json",
                        oracle_replay(nominal, auto, truth, settings)))
    index = {
        "schema": "DS_RESULTS_INDEX_1",
        "engine_version": ENGINE_VERSION,
        "synthetic": True,
        "scientific_status": "PROTOTYPE_UNVALIDATED",
        "clinical_validation": False,
        "g2": "NO-GO",
        "files": files,
    }
    _write(out, "index.json", index)
    return index

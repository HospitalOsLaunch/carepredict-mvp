"""P2/P3bis — targeted tests for audit findings F01-F08, T19 threshold, admission accounting.

They complement the independent tests (test_independent_acceptance.py, kept verbatim): each
checks WHY a case passes (time kept, exact diagnostic, ledger untouched, disjoint loans allowed,
hand-computed oracle), not only that it is not approvable.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hospitalos.decision_support.candidates import make_plan, reinforcement_action
from hospitalos.decision_support.contracts import (
    CivilDeadline,
    LockedDischarge,
    LockedExtension,
    ScenarioLocks,
)
from hospitalos.decision_support.eligibility import lock_timing_issues
from hospitalos.decision_support.planner import (
    ReviewStore,
    Settings,
    _reservation_requests,
    recommend,
    review,
    simulate,
)
from hospitalos.decision_support.reference_forecaster import (
    Decisions,
    SampledProvider,
)
from hospitalos.decision_support.reference_forecaster import (
    simulate as simulate_world,
)
from hospitalos.decision_support.snapshot import build_snapshot, load_json

ROOT = Path(__file__).resolve().parents[2]
FX = Path(__file__).resolve().parent / "fixtures"
AS_OF = datetime(2026, 11, 16, 19, tzinfo=UTC)  # 20:00 Paris
H = lambda paris_hour, day=1: AS_OF + timedelta(hours=paris_hour - 20 + 24 * day)  # noqa: E731


def raw_obs(name: str = "nominal_auto.json") -> list[dict]:
    return copy.deepcopy(load_json(FX / name)["observations"])


def snap(obs: list[dict], settings: Settings):
    return build_snapshot(obs, AS_OF, settings.profile)


def value(obs: list[dict], kind: str, subject: str) -> dict:
    return next(o["value"] for o in obs if o["kind"] == kind and o["subject"] == subject)


def lock_s01(at: datetime, basis: str = "validated_instruction") -> ScenarioLocks:
    return ScenarioLocks(
        locks=(LockedDischarge(stay_id="S01", at=at, basis=basis),), search_complements=False
    )


def ev(rec, pid):
    return next(e for e in rec.bundle.evaluations if e.plan.plan_id == pid)


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings.default()


# ------------------------------------------------------------------------------------- F01


def test_f01_contradicted_readiness_kept_as_hypothesis_with_time_unchanged(settings):
    obs = raw_obs()
    value(obs, "readiness_estimate", "S01").update(
        {"earliest": H(18), "delay_hours": {"support": [0], "weights": [1]}}
    )
    rec = simulate(snap(obs, settings), lock_s01(H(10)), settings)
    assert rec.status == "HYPOTHETICAL_ONLY" and not rec.approvable
    assert any(
        "validated_instruction_preconditions_unmet:S01:lock_before_readiness_estimate:certain" in d
        for d in rec.diagnostics
    )
    locked = ev(rec, rec.locked_plan_id).plan.actions[0]
    assert locked.window_start == H(10) and locked.basis == "hypothesis_only"  # never moved


def test_f01_possible_readiness_gap_also_not_approvable_and_ceil_rounding(settings):
    s = snap(raw_obs(), settings)
    s01 = next(x for x in s.stays if x.stay_id == "S01")  # ready 09:00 Paris + {0,1} h
    assert lock_timing_issues(s01, AS_OF, H(9)) == ("lock_before_readiness_estimate:possible",)
    assert lock_timing_issues(s01, AS_OF, H(10)) == ()
    late = s01.model_copy(update={"ready_earliest": H(9) + timedelta(minutes=30)})
    # 09:30 is rounded UP to 10:00: a lock at 10:00 becomes 'possible', never optimistic
    assert lock_timing_issues(late, AS_OF, H(10)) == ("lock_before_readiness_estimate:possible",)
    rec = simulate(s, lock_s01(H(9)), settings)
    assert rec.status == "HYPOTHETICAL_ONLY" and not rec.approvable


def test_f01_active_obstacle_survives_manual_lock_and_approval_revalidates(settings):
    obs = raw_obs()
    obs.append(
        {
            "obs_id": "x-obst",
            "kind": "obstacle",
            "subject": "S01.x",
            "event_time": AS_OF.isoformat(),
            "available_at": AS_OF.isoformat(),
            "source": "test",
            "synthetic": True,
            "value": {"stay_id": "S01", "code": "destination_unavailable", "active": True},
        }
    )
    s = snap(obs, settings)
    rec = simulate(s, lock_s01(H(10)), settings)
    assert not rec.approvable and any(
        "obstacle:destination_unavailable" in d for d in rec.diagnostics
    )
    # defence in depth: even a recommendation wrongly flagged approvable is refused at approval
    forged = rec.model_copy(update={"approvable": True, "status": "RECOMMENDATION_READY"})
    out = review(forged, "approve", s, rec.created_at, "forged", ReviewStore())
    assert out.outcome == "REFUSED" and out.recompute_required
    assert any(r.startswith("precondition_unmet:S01:") for r in out.reasons)
    # and the simulator itself rejects a validated lock on a blocked stay
    run = simulate_world(
        s,
        settings.profile,
        AS_OF,
        24,
        Decisions({}, {"S01": (14, "validated_instruction")}, {}, ()),
        SampledProvider(101),
    )
    assert "locked_precondition:S01:obstacle:destination_unavailable" in run.violations


def test_f01_valid_x1x2_scenario_stays_approvable(settings):
    rec = simulate(
        snap(raw_obs(), settings),
        ScenarioLocks.model_validate(load_json(FX / "scenario_x1x2.json")["locks"]),
        settings,
    )
    assert rec.approvable and rec.status in {"RECOMMENDATION_READY", "NO_ACTION_PREFERRED"}
    out = review(rec, "approve", snap(raw_obs(), settings), rec.created_at, "ok", ReviewStore())
    assert out.outcome == "APPROVED_IN_DEMO"


# ------------------------------------------------------------------------------------- F02


def _loans(obs, r1_window, r2_window):
    for ident, (start, end) in (("R1", r1_window), ("R2", r2_window)):
        value(obs, "reinforcement_option", ident).update(
            {
                "source": "shared_unit",
                "confirmation": "confirmed",
                "lending_unit": "U-LOAN",
                "lending_unit_scheduled": 4,
                "lending_unit_minimum": 3,
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        )
    return obs


def _with_both(rec):
    return [
        e
        for e in rec.bundle.evaluations
        if {a.target for a in e.plan.actions if a.type == "reinforcement"} >= {"R1", "R2"}
    ]


def test_f02_overlapping_loans_rejected_together_and_reported(settings):
    obs = _loans(raw_obs(), (H(14), H(20)), (H(14), H(20)))
    rec = recommend(snap(obs, settings), settings)
    assert _with_both(rec) == []
    assert rec.bundle.search.rejected["R1+R2"].startswith("lending_unit_minimum_cumulative:U-LOAN")


def test_f02_disjoint_loans_from_same_lender_remain_allowed(settings):
    obs = _loans(raw_obs(), (H(7), H(11)), (H(14), H(20)))
    rec = recommend(snap(obs, settings), settings)
    both = _with_both(rec)
    assert both and all(e.admissible for e in both)
    assert "R1+R2" not in rec.bundle.search.rejected


def test_f02_loans_across_two_requests_share_lender_spare_staff(settings):
    s = snap(_loans(raw_obs(), (H(14), H(20)), (H(14), H(20))), settings)
    store = ReviewStore()
    opts = {o.option_id: o for o in s.reinforcements}
    v = s.as_of + timedelta(minutes=30)
    plan_a = make_plan(s, "auto", (reinforcement_action(s, opts["R1"], v),), "R1")
    plan_b = make_plan(s, "auto", (reinforcement_action(s, opts["R2"], v),), "R2")
    ok_a, _ = store.ledger.reserve_all(_reservation_requests(plan_a.actions, s))
    before = copy.deepcopy((store.ledger.by_key, store.ledger.used))
    ok_b, details = store.ledger.reserve_all(_reservation_requests(plan_b.actions, s))
    assert ok_a and not ok_b and any("lend:U-LOAN:IDE" in d and "exhausted" in d for d in details)
    assert (store.ledger.by_key, store.ledger.used) == before  # nothing leaked


# ------------------------------------------------------------------------------------- F03


def test_f03_refused_plan_keeps_other_holders_and_retry_is_stable(settings):
    s = snap(raw_obs(), settings)
    rec = recommend(s, settings)
    store = ReviewStore()
    r1 = next(a for a in ev(rec, rec.primary_plan_id).plan.actions if a.target == "R1")
    store.ledger.capacity[("R1", r1.window_start.isoformat())] = 1
    store.ledger.reserve("R1", r1.window_start.isoformat(), "other-request")
    snapshot_before = copy.deepcopy((store.ledger.by_key, store.ledger.used, store.ledger.capacity))
    out = review(rec, "approve", s, rec.created_at, "k", store)
    assert out.outcome == "REFUSED" and out.reservations == ()
    assert (store.ledger.by_key, store.ledger.used) == snapshot_before[:2]
    again = review(rec, "approve", s, rec.created_at, "k", store)  # same request replayed
    assert (
        again.replayed and again.outcome == "REFUSED" and store.ledger.by_key == snapshot_before[0]
    )


# ------------------------------------------------------------------------------------- F05


def test_f05_non_whole_hours_are_refused_explicitly():
    with pytest.raises(ValidationError, match="unsupported_time_precision"):
        LockedDischarge(stay_id="S01", at=H(10) + timedelta(minutes=30), basis="hypothesis_only")
    with pytest.raises(ValidationError, match="unsupported_time_precision"):
        LockedExtension(
            stay_id="S02",
            reference_time=H(12) + timedelta(minutes=15),
            extension_hours=1,
            basis="validated_instruction",
        )
    with pytest.raises(ValidationError, match="unsupported_time_precision"):
        CivilDeadline(day_offset=1, local_time=time(20, 30))


# ------------------------------------------------------------------------------- F06 / F07


def test_f06_unknown_cleaning_abstains_or_uses_declared_assumption(settings):
    obs = raw_obs()
    value(obs, "bed", "L01").pop("cleaning_hours")
    s = snap(obs, settings)
    rec = recommend(s, settings)
    assert rec.status == "INSUFFICIENT_DATA" and "cleaning_duration_unknown:L01" in rec.diagnostics
    run = simulate_world(
        s,
        settings.profile,
        AS_OF,
        24,
        Decisions({"S01": (14, "x")}, {}, {}, ()),
        SampledProvider(101),
    )
    assert "cleaning_duration_unknown:L01" in run.violations  # never a silent 1 h
    assumed = {
        **settings.profile,
        "unknown_cleaning_assumption": {
            "id": "ASSUME-CLEAN-TEST",
            "version": "1",
            "hours": {"support": [2], "weights": [1]},
        },
    }
    rec = recommend(s, Settings(assumed, settings.objective, settings.score))
    assert rec.status != "INSUFFICIENT_DATA"
    assert "assumed_cleaning_duration:L01:ASSUME-CLEAN-TEST@1" in rec.diagnostics


def _as_need(obs):
    o = copy.deepcopy(next(x for x in obs if x["subject"] == "S01.IDE"))
    o.update({"obs_id": "x-as", "subject": "S01.AS"})
    o["value"].update({"skill": "AS", "day_minutes_per_hour": 15, "night_minutes_per_hour": 15})
    obs.append(o)
    return obs


def test_f07_required_skill_roster_unknown_abstains_known_roster_proceeds(settings):
    rec = recommend(snap(_as_need(raw_obs()), settings), settings)
    assert rec.status == "INSUFFICIENT_DATA"
    assert any(d.startswith("roster_unknown:AS") for d in rec.diagnostics)
    obs = _as_need(raw_obs())
    obs.append(
        {
            "obs_id": "x-as-roster",
            "kind": "roster_coverage",
            "subject": "AS-window",
            "event_time": H(12, 0).isoformat(),
            "available_at": H(12, 0).isoformat(),
            "source": "test",
            "synthetic": True,
            "value": {"skill": "AS", "start": H(14, 0).isoformat(), "end": H(21).isoformat()},
        }
    )
    rec = recommend(snap(obs, settings), settings)
    assert not any(d.startswith("roster_unknown") for d in rec.diagnostics)
    base = ev(rec, rec.baseline_plan_id)
    assert base.metrics.uncovered_by_skill["AS"] > 0  # declared zero AS staff, not unknown


# ------------------------------------------------------------------------------------- F08


def test_f08_identity_is_content_addressed(settings):
    s = snap(raw_obs(), settings)
    a, b = recommend(s, settings), recommend(s, settings)
    assert (a.recommendation_id, a.bundle.bundle_id) == (b.recommendation_id, b.bundle.bundle_id)
    seeds = {
        **settings.profile,
        "forecast": {**settings.profile["forecast"], "selection_seeds": [101, 102, 103, 105]},
    }
    objective = copy.deepcopy(dict(settings.objective))
    objective["tiers"][1]["equivalence_tolerance"] = 16
    for other in (
        Settings(seeds, settings.objective, settings.score),
        Settings(settings.profile, objective, settings.score),
    ):
        c = recommend(s, other)
        assert (
            c.recommendation_id != a.recommendation_id and c.bundle.bundle_id != a.bundle.bundle_id
        )


def test_f08_server_store_never_replaces_a_document_under_the_same_id(settings):
    spec = importlib.util.spec_from_file_location("ds_serve", ROOT / "web/decision/serve.py")
    serve = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(serve)
    state = serve.State()
    rec = recommend(snap(raw_obs(), settings), settings)
    state.keep(rec)
    state.keep(rec)  # same content: idempotent
    with pytest.raises(ValueError, match="identity conflict"):
        state.keep(rec.model_copy(update={"reasons": ("tampered",)}))


# ------------------------------------------------------------------------- T19 threshold


@pytest.mark.parametrize("t", range(0, 8))
def test_t19_staff_threshold_matches_hand_oracle(settings, t):
    """Oracle written in build_fixtures.staff_threshold: 100 + 10 t uncovered minutes and
    7 + t hours requiring 2 IDE; required staff drops from 2 to 1 the hour after X2 leaves."""
    s = build_snapshot(raw_obs("staff_threshold.json"), AS_OF, settings.profile)
    locks = ScenarioLocks(
        locks=(
            LockedExtension(
                stay_id="SB", reference_time=H(12), extension_hours=t, basis="validated_instruction"
            ),
        ),
        deadline=CivilDeadline(day_offset=1, local_time=time(20)),
        search_complements=False,
    )
    rec = simulate(s, locks, settings)
    assert rec.approvable
    e = ev(rec, rec.locked_plan_id)
    required = [p.staff_required["IDE"] for p in e.trajectory]
    d = 16 + t
    assert e.metrics.uncovered_in_unit_minutes == 100 + 10 * t
    assert e.metrics.uncovered_waiting_minutes == 0
    assert required.count(2.0) == 7 + t
    assert required[d] == 2.0 and (d + 1 >= 24 or required[d + 1] == 1.0)


# ------------------------------------------------------------------- admission accounting


def test_admission_accounting_each_patient_hour_counted_once(settings):
    s = snap(raw_obs(), settings)
    profile = settings.profile
    run = simulate_world(
        s, profile, AS_OF, 24, Decisions({"S01": (14, "x")}, {}, {}, ()), SampledProvider(101)
    )
    reqs = {r.request_id: r for r in s.admissions}
    stays = {x.stay_id: x for x in s.stays}
    day = profile["day_local_hours"]

    def is_day(h: int) -> bool:
        local = (
            (AS_OF + timedelta(hours=h))
            .astimezone(__import__("zoneinfo").ZoneInfo("Europe/Paris"))
            .hour
        )
        return day["start"] <= local < day["end"]

    def care(rows, h):
        c = next((c for c in rows if c.skill == "IDE"), None)
        return (
            0 if c is None else (c.day_minutes_per_hour if is_day(h) else c.night_minutes_per_hour)
        )

    expected_wait = 0
    for rid, a in run.arrivals.items():
        m = run.admissions.get(rid, 24)
        waiting, in_unit = set(range(a, m)), set(range(m, 24))
        assert waiting.isdisjoint(in_unit) and waiting | in_unit == set(range(a, 24))
        expected_wait += sum(care(reqs[rid].care, h) for h in waiting)
        if rid not in run.admissions:
            expected_wait += reqs[rid].admission_task_minutes  # owed once, at the end
    assert sum(run.uncovered_waiting) == expected_wait
    for h in range(24):  # independent re-derivation of in-unit IDE demand
        demand = 0
        for sid, st in stays.items():
            dep = run.departures.get(sid)
            if dep is not None and h > dep:
                continue
            demand += care(st.care, h)
            demand += sum(
                t.minutes * t.staff_required
                for t in st.tasks
                if t.skill == "IDE" and int((t.start - AS_OF).total_seconds() // 3600) == h
            )
            demand += profile["discharge_task_minutes"]["IDE"] if dep == h else 0
        for rid, m in run.admissions.items():
            demand += care(reqs[rid].care, h) if h >= m else 0
            demand += reqs[rid].admission_task_minutes if h == m else 0
        assert run.demand["IDE"][h] == demand, h
    assert json.dumps(run.admissions)  # serialisable trace for the evidence

"""v5 — targeted tests for re-audit findings V4-R01, V4-R02, V4-R03 (resources).

They complement the auditor's tests (test_v4_resource_boundaries.py, kept verbatim) by checking
the exact reasons, the witnesses that must stay allowed, and the traces of conflicts.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hospitalos.decision_support.candidates import make_plan, reinforcement_action
from hospitalos.decision_support.planner import (
    ReviewStore,
    Settings,
    _reservation_requests,
    recommend,
)
from hospitalos.decision_support.resources import (
    ResourceLedger,
    lending_violations,
    option_admissibility,
    touched_hours,
)
from hospitalos.decision_support.snapshot import build_snapshot, load_json

FX = Path(__file__).resolve().parent / "fixtures"
AS_OF = datetime(2026, 11, 16, 19, tzinfo=UTC)
D1 = datetime(2026, 11, 17, tzinfo=UTC)


def loans(r1, r2, lender: str | None = "U-LOAN", scheduled: int = 4):
    obs = copy.deepcopy(load_json(FX / "nominal_auto.json")["observations"])
    for ident, (start, end) in (("R1", r1), ("R2", r2)):
        v = next(o["value"] for o in obs if o["subject"] == ident)
        v.update(
            {
                "source": "shared_unit",
                "confirmation": "confirmed",
                "lending_unit": lender,
                "lending_unit_scheduled": scheduled,
                "lending_unit_minimum": 3,
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        )
    settings = Settings.default()
    return build_snapshot(obs, AS_OF, settings.profile), settings


def h(hour: float) -> datetime:
    return D1 + timedelta(hours=hour)


def test_r01_off_grid_window_refused_with_explicit_reason_never_rounded():
    snap, settings = loans((h(13), h(19)), (h(13.5), h(18.5)))
    rec = recommend(snap, settings)
    assert rec.bundle.search.rejected["R2"] == (
        "unsupported_time_precision:reinforcement_window_not_on_whole_hours"
    )
    r1_alone = [
        e
        for e in rec.bundle.evaluations
        if {a.target for a in e.plan.actions if a.type == "reinforcement"} == {"R1"}
    ]
    assert r1_alone and all(e.admissible for e in r1_alone)  # the aligned offer stays usable


def test_r01_common_grid_catches_overlap_even_if_admissibility_is_bypassed():
    snap, _ = loans((h(13), h(19)), (h(13.5), h(18.5)))
    r1, r2 = (next(o for o in snap.reinforcements if o.option_id == i) for i in ("R1", "R2"))
    assert touched_hours(h(13.5), h(18.5))[0] == h(13)  # off-grid start lands on the grid
    problems = lending_violations([r1, r2])
    assert problems and all("lending_unit_minimum_cumulative:U-LOAN" in p for p in problems)
    v = AS_OF + timedelta(minutes=30)
    def keys(o):
        plan = make_plan(snap, "auto", (reinforcement_action(snap, o, v),), o.option_id)
        return {r[1] for r in _reservation_requests(plan.actions, snap) if r[0].startswith("lend:")}

    assert keys(r2) <= keys(r1)  # same hourly keys: the two windows meet in the ledger


def test_r01_witness_aligned_non_overlapping_loans_allowed():
    snap, settings = loans((h(7), h(11)), (h(13), h(19)))
    rec = recommend(snap, settings)
    both = [
        e
        for e in rec.bundle.evaluations
        if {a.target for a in e.plan.actions if a.type == "reinforcement"} >= {"R1", "R2"}
    ]
    assert both and all(e.admissible for e in both)


def test_r02_unidentified_lender_refused_other_sources_unaffected():
    snap, settings = loans((h(13), h(19)), (h(13), h(19)), lender=None)
    r1 = next(o for o in snap.reinforcements if o.option_id == "R1")
    assert option_admissibility(r1, AS_OF, AS_OF + timedelta(hours=24)) == (
        False,
        "lending_unit_unknown",
    )
    assert lending_violations([r1]) == ["lending_unit_unknown:R1"]
    v = AS_OF + timedelta(minutes=30)
    plan = make_plan(snap, "auto", (reinforcement_action(snap, r1, v),), "R1")
    caps = {r[3] for r in _reservation_requests(plan.actions, snap) if r[0].startswith("lend:")}
    assert caps == {None}  # unknown capacity -> refusal at reservation, never a skipped check
    interim = r1.model_copy(update={"source": "interim", "lending_unit": None})
    assert option_admissibility(interim, AS_OF, AS_OF + timedelta(hours=24))[0] is True


def test_r03_capacity_reduced_or_unknown_blocks_new_holds_and_traces_conflict():
    ledger = ResourceLedger()
    ok, _ = ledger.reserve_all(
        [("lend:U:IDE", "h13", "first", 2), ("lend:U:IDE", "h13", "second", 2)]
    )
    assert ok and ledger.used[("lend:U:IDE", "h13")] == ["first", "second"]
    before = copy.deepcopy((ledger.by_key, ledger.used))
    ok, details = ledger.reserve_all([("lend:U:IDE", "h13", "third", 1)])  # margin now 1 < 2 held
    assert not ok and details == ["lend:U:IDE@h13:capacity_exhausted"]
    assert ledger.conflicts == ["capacity_below_existing_holds:lend:U:IDE@h13:2>1"]
    ok, details = ledger.reserve_all([("lend:U:IDE", "h13", "fourth", None)])  # now unknown
    assert not ok and details == ["lend:U:IDE@h13:capacity_unknown"]
    assert ledger.conflicts[-1] == "capacity_now_unknown:lend:U:IDE@h13:holds=2"
    assert (ledger.by_key, ledger.used) == before  # earlier commitments preserved, not erased
    ok, details = ledger.reserve_all([("lend:U:IDE", "h13", "first", 1)])  # replay of a holder
    assert ok and details == ["lend:U:IDE@h13:duplicate_ignored"]


def test_r03_review_uses_current_snapshot_capacity():
    snap5, settings = loans((h(13), h(19)), (h(13), h(19)), scheduled=5)
    snap4, _ = loans((h(13), h(19)), (h(13), h(19)), scheduled=4)
    store = ReviewStore()
    v = AS_OF + timedelta(minutes=30)
    opts5 = {o.option_id: o for o in snap5.reinforcements}
    opts4 = {o.option_id: o for o in snap4.reinforcements}
    plan1 = make_plan(snap5, "auto", (reinforcement_action(snap5, opts5["R1"], v),), "R1")
    plan2 = make_plan(snap4, "auto", (reinforcement_action(snap4, opts4["R2"], v),), "R2")
    assert store.ledger.reserve_all(_reservation_requests(plan1.actions, snap5))[0]
    ok, details = store.ledger.reserve_all(_reservation_requests(plan2.actions, snap4))
    assert not ok and any("lend:U-LOAN:IDE" in d and "exhausted" in d for d in details)

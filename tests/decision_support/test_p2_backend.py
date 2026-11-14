"""P2 — reference backend: information boundary, invariants, resources, pairing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest

from hospitalos.decision_support.candidates import coordination_action, make_plan, reinforcement_action
from hospitalos.decision_support.contracts import Distribution, ReinforcementOption
from hospitalos.decision_support.planner import Settings, _config, recommend
from hospitalos.decision_support.reference_forecaster import (
    Decisions,
    LeakageError,
    PrivateOracle,
    PrivateTruth,
    ReferenceForecaster,
    SampledProvider,
    assert_product_backend,
    check_invariants,
    check_isolation,
    simulate,
)
from hospitalos.decision_support.resources import ResourceLedger, coverage, option_admissibility
from hospitalos.decision_support.snapshot import load_json, snapshot_from_fixture

from .conftest import FX, snapshot_with

ROOT = Path(__file__).resolve().parents[2]
UTC_AS_OF = "2026-11-16T19:00:00+00:00"


def _cfg(snapshot, settings):
    return _config(settings, snapshot.as_of, 24)


def _run(snapshot, settings, decisions, seed=101):
    return simulate(snapshot, settings.profile, snapshot.as_of, 24, decisions, SampledProvider(seed))


NONE = Decisions({}, {}, {}, ())


def _truth(name):
    return PrivateTruth.from_fixture(load_json(FX / name)["private_truth"])


def test_t03_two_private_futures_same_public_recommendation(settings):
    a = recommend(snapshot_from_fixture(FX / "nominal_auto.json"), settings)
    b = recommend(snapshot_from_fixture(FX / "nominal_auto_truth_b.json"), settings)
    assert a.model_dump_json() == b.model_dump_json()
    snapshot = snapshot_from_fixture(FX / "nominal_auto.json")
    plan = make_plan(snapshot, "auto", (), "pratique habituelle")
    check_isolation(lambda truth: ReferenceForecaster(), snapshot, plan,
                    _cfg(snapshot, settings), _truth("nominal_auto.json"),
                    _truth("nominal_auto_truth_b.json"))


def test_t04_forecast_initialised_from_private_truth_is_blocked(nominal, settings):
    plan = make_plan(nominal, "auto", (), "pratique habituelle")
    with pytest.raises(LeakageError):
        check_isolation(PrivateOracle, nominal, plan, _cfg(nominal, settings),
                        _truth("nominal_auto.json"), _truth("nominal_auto_truth_b.json"))
    oracle = PrivateOracle(_truth("nominal_auto.json"))
    assert oracle.info().product_allowed is False
    with pytest.raises(LeakageError):
        assert_product_backend(oracle)
    with pytest.raises(LeakageError):
        recommend(nominal, Settings(settings.profile, settings.objective, settings.score, oracle))
    with pytest.raises(LeakageError):
        ReferenceForecaster().forecast({"stays": []}, plan, _cfg(nominal, settings))  # type: ignore[arg-type]


def test_t05_revoked_or_missing_authorisation_never_proposed(auto):
    rejected = auto.bundle.search.rejected
    assert "medical_authorization_revoked" in rejected["S05"]
    assert "medical_authorization_not_authorized" in rejected["S03"]
    for e in auto.bundle.evaluations:
        assert not {a.target for a in e.plan.actions} & {"S03", "S04", "S05", "S06", "S07"}


def test_t07_pressure_discharges_disabled_under_high_pressure(nominal, settings, auto):
    with pytest.raises(ValueError):
        simulate(nominal, {**settings.profile, "pressure_discharges_enabled": True},
                 nominal.as_of, 24, NONE, SampledProvider(1))
    authorised = {s.stay_id for s in nominal.stays if s.medical_authorization == "authorized"}
    for seed in (101, 102, 103, 104):
        run = _run(nominal, settings, NONE, seed)
        assert max(run.waiting) >= 1  # pressure exists
        assert set(run.departures) <= authorised
    base = auto.bundle.evaluations[0]
    assert base.metrics.peak_pressure is not None and base.metrics.peak_pressure >= 7
    # the historical simulator file is preserved unchanged
    hospsim = ROOT / "src/hospitalos/synthetic/v041/hospsim.py"
    assert hashlib.sha256(hospsim.read_bytes()).hexdigest() == (
        "3c950b507a3e418d694acb465d86f21b4068709646095f46895adee965805d73")


def test_t08_no_cleaning_before_departure_and_transport_rescheduled(nominal, settings):
    early = Decisions({"S01": (1, "observed_authorization")}, {}, {}, ())
    for seed in (101, 102, 103, 104):
        rec = Recorder(SampledProvider(seed))
        run = simulate(nominal, settings.profile, nominal.as_of, 24, early, rec)
        ready = 13 + rec.seen[("readiness", "S01")]  # 09:00 Paris = index 13
        assert run.departures["S01"] >= max(ready, rec.seen[("transport_lead", "S01")])
        assert run.departures["S01"] > 1  # target 21:00 Paris rescheduled, never before
        assert any(e[1] == "transport_used" and e[2] == "S01" for e in run.events)
        cleaning = [e for e in run.events if e[1] == "cleaning_start" and e[3] == "S01"]
        assert cleaning and cleaning[0][0] > run.departures["S01"]
        assert check_invariants(nominal, nominal.as_of, run, False) == []
    run = _run(nominal, settings, NONE)
    run.events.append((0, "cleaning_start", "L01", "S01"))
    assert "cleaning_before_departure:L01" in check_invariants(nominal, nominal.as_of, run, False)
    locked_16h = Decisions({}, {"S01": (20, "validated_instruction")}, {}, ())  # 16:00 Paris
    assert "locked_transport_unavailable:S01:h20" in _run(nominal, settings, locked_16h).violations


def _two_eligible(settings):
    return snapshot_with("nominal_auto.json", [{
        "obs_id": "o-obst-S06-closed", "kind": "obstacle", "subject": "S06.aval",
        "event_time": "2026-11-16T18:00:00+00:00", "available_at": "2026-11-16T18:05:00+00:00",
        "source": "synthetic_feed", "value": {"stay_id": "S06", "code": "aval_non_confirme",
                                               "active": False}}])


def test_t09_t21_shared_transport_joint_effect_not_sum(settings):
    snapshot = _two_eligible(settings)
    at10 = 14  # 10:00 Paris
    joint = Decisions({"S01": (at10, "x"), "S06": (at10, "x")}, {}, {}, ())
    s01 = Decisions({"S01": (at10, "x")}, {}, {}, ())
    s06 = Decisions({"S06": (at10, "x")}, {}, {}, ())
    run_j, run_1, run_6, run_0 = (_run(snapshot, settings, d) for d in (joint, s01, s06, NONE))
    used = [e[0] for e in run_j.events if e[1] == "transport_used"]
    assert len(used) == len(set(used))  # capacity 1 per hour: no double booking
    assert (run_j.departures["S01"], run_j.departures["S06"]) != (
        run_1.departures["S01"], run_6.departures["S06"])  # one is pushed in the joint plan
    assert any(e[1] == "rescheduled_to_next_transport_slot" for e in run_j.events)
    delta = lambda r: sum(r.uncovered_unit) + sum(r.uncovered_waiting) - (  # noqa: E731
        sum(run_0.uncovered_unit) + sum(run_0.uncovered_waiting))
    assert check_invariants(snapshot, snapshot.as_of, run_j, False) == []
    assert delta(run_j) != delta(run_1) + delta(run_6) or run_j.departures != {
        **run_1.departures, **run_6.departures}
    ledger = ResourceLedger(capacity={("transport", "h15"): 1})
    assert ledger.reserve("transport", "h15", "k1") == (True, "reserved")
    assert ledger.reserve("transport", "h15", "k2") == (False, "capacity_exhausted")
    assert ledger.reserve("transport", "h16", "k3") == (False, "capacity_unknown")


def test_t10_idempotent_reservation():
    ledger = ResourceLedger(capacity={("R2", "slot"): 1})
    assert ledger.reserve("R2", "slot", "same") == (True, "reserved")
    assert ledger.reserve("R2", "slot", "same") == (True, "duplicate_ignored")
    assert ledger.used[("R2", "slot")] == ["same"]


def test_t11_unconfirmed_reinforcement_is_conditional(nominal, settings):
    r1 = next(o for o in nominal.reinforcements if o.option_id == "R1")
    assert r1.confirmation == "requested"
    validity = nominal.as_of + timedelta(minutes=30)
    plan = make_plan(nominal, "auto", (reinforcement_action(nominal, r1, validity),), "R1")
    e = ReferenceForecaster().forecast(nominal, plan, _cfg(nominal, settings))
    assert e.conditional_on == ("R1",)
    assert e.confirmed_only is not None
    assert e.confirmed_only.uncovered_care_minutes > e.metrics.uncovered_care_minutes
    assert all(p.staff_reinforcement["IDE"] in (0.0, 1.0) for p in e.trajectory)


def test_t12_no_compensation_by_total_hours(nominal, settings):
    one = coverage(0, [(20, 2)], staff=1)
    assert one.uncovered_minutes == 40 and one.simultaneity_shortfall_minutes == 40
    assert one.staff_required == 2  # 40 staff-minutes fit in an hour, presence does not
    two = coverage(0, [(20, 2)], staff=2)
    assert two.uncovered_minutes == 0
    as_option = ReinforcementOption(
        option_id="RAS", skill="AS", start=nominal.as_of + timedelta(hours=19),
        end=nominal.as_of + timedelta(hours=24), source="internal_pool", confirmation="confirmed")
    snap = nominal.model_copy(update={"reinforcements": nominal.reinforcements + (as_option,)})
    base = _run(snap, settings, NONE)
    with_as = _run(snap, settings, Decisions({}, {}, {}, (as_option,)))
    assert sum(with_as.uncovered_skill["IDE"]) == sum(base.uncovered_skill["IDE"])


def test_t13_external_commitment_visible_or_refused(nominal):
    start, end = nominal.as_of, nominal.as_of + timedelta(hours=24)
    r3 = next(o for o in nominal.reinforcements if o.option_id == "R3")
    assert option_admissibility(r3, start, end) == (
        False, "violates_lending_unit_minimum:U-CARDIO-SYN:3-1<3")
    unknown = r3.model_copy(update={"lending_unit_minimum": None})
    assert option_admissibility(unknown, start, end) == (False, "external_commitment_unknown")
    margin = r3.model_copy(update={"lending_unit_scheduled": 4})
    assert option_admissibility(margin, start, end) == (
        True, "external_cost:U-CARDIO-SYN:remaining_margin=0")


def test_t14_bed_returned_once_and_no_gain_by_refusing_admission(nominal, settings):
    coord = Decisions({"S01": (14, "x")}, {}, {}, ())  # 10:00 Paris
    run = _run(nominal, settings, coord)
    assert run.admissions.get("A02") is not None  # L01 re-occupied after cleaning
    assert run.beds_returned == len(run.departures)  # one return per departure, not per use
    refused = snapshot_with("nominal_auto.json", [{
        "obs_id": "o-adm-A02-v2", "kind": "admission_request", "subject": "A02",
        "event_time": "2026-11-16T18:30:00+00:00", "available_at": "2026-11-16T18:35:00+00:00",
        "source": "synthetic_feed",
        "value": {"requirements": ["unavailable_capability"],
                  "expected_arrival": "2026-11-17T08:00:00+00:00",
                  "arrival_delay": {"support": [0, 1], "weights": [1, 1]},
                  "care": [{"skill": "IDE", "day_minutes_per_hour": 30,
                            "night_minutes_per_hour": 12, "status": "estimated"}],
                  "admission_task_minutes": 45}}])
    blocked = _run(refused, settings, coord)
    total = lambda r: sum(r.uncovered_unit) + sum(r.uncovered_waiting)  # noqa: E731
    assert "A02" not in blocked.admissions
    assert total(blocked) >= total(run)


@dataclass
class Recorder:
    inner: SampledProvider
    seen: dict = field(default_factory=dict)
    reads_private: bool = False

    def draw(self, mechanism: str, entity: str, dist: Distribution) -> int:
        value = self.inner.draw(mechanism, entity, dist)
        self.seen[(mechanism, entity)] = value
        return value


def test_t22_paired_exogenous_primitives(nominal, settings):
    a, b = Recorder(SampledProvider(103)), Recorder(SampledProvider(103))
    simulate(nominal, settings.profile, nominal.as_of, 24, NONE, a)
    run_b = simulate(nominal, settings.profile, nominal.as_of, 24,
                     Decisions({"S01": (14, "x")}, {}, {}, ()), b)
    common = set(a.seen) & set(b.seen)
    assert {("readiness", "S01"), ("transport_lead", "S01"), ("arrival", "A02")} <= common
    assert all(a.seen[k] == b.seen[k] for k in common)
    d = Distribution(support=(0, 1, 2), weights=(1, 1, 1))
    p = SampledProvider(7)
    first = [p.draw("m", e, d) for e in ("x", "y", "z")]
    assert [p.draw("m", e, d) for e in ("z", "y", "x")] == first[::-1]  # order-free
    assert run_b.departures["S01"] == 14  # endogenous consequence free to change


def test_reference_backend_invariants_on_all_auto_plans(auto):
    assert auto.bundle.backend.reads_private is False
    assert all(e.admissible for e in auto.bundle.evaluations)


def test_coordination_action_contract(nominal):
    a = coordination_action(nominal, "S01", nominal.as_of + timedelta(hours=14),
                            nominal.as_of + timedelta(minutes=30))
    assert a.basis == "observed_authorization" and a.validator == "cadre_de_sante"
    assert "cleaning_only_after_effective_departure" in a.preconditions
    assert a.idempotency_key == coordination_action(
        nominal, "S01", nominal.as_of + timedelta(hours=14),
        nominal.as_of + timedelta(minutes=45)).idempotency_key

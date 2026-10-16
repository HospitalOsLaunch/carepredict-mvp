"""Document-source mechanisms, physical noninterference and reserved families."""

from __future__ import annotations

import datetime as dt
import gzip
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from hospitalos.synthetic.cohort import freeze, materialize
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.counterfactual import exogenous_fingerprint, validate_pair
from hospitalos.synthetic.documentary import (
    DocumentaryMechanisms,
    StaffSnapshot,
    forecast_day,
)
from hospitalos.synthetic.engine import _HS, _RUN, build_simulation, simulate
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.learning import _events
from hospitalos.synthetic.patient_care import CARE_TYPES, observe_care
from hospitalos.synthetic.patient_census import CensusProfile
from hospitalos.synthetic.patient_learning import prepare_patient_run
from hospitalos.synthetic.registry import CohortPlan, compile_registry, validate_worlds

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {
    "staff_forecasts": ["v041", "admission_prior_v1", "milestones_v1"],
    "downstream_confirmation": ["v041", "request_delay_v1", "review_capacity_v1"],
}


def config(**changes: Any) -> HospitalConfig:
    raw = json.loads((ROOT / "configs/synthetic/hospital_two_poles.json").read_text())
    return HospitalConfig.model_validate({**raw, "days": 7, "warmup_days": 7, **changes})


class Log:
    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    def event(self, *args: Any, **payload: Any) -> None:
        self.events.append((*args, payload))


def fake_staff(mode: str, future_ready: int) -> tuple[Any, Any, Any, Log]:
    docs = DocumentaryMechanisms(config(documentary={"staff_forecasts": mode}))
    # Deliberately no actual destination, planned departure or future queue data.
    p = SimpleNamespace(
        pid=1,
        admit_h=0,
        ready_h=future_ready,
        aide_h=1000,
        info0=False,
        dsp_jamais=False,
        dest_decl=-1,
        dsp=-1,
        dsp_n=0,
        conf=False,
        aval_dem=False,
    )
    log = Log()

    def declare(p: Any, destination: int, hour: int, unit: int, logger: Log) -> None:
        docs.destination(p.pid, p.dest_decl, destination, hour)
        p.dest_decl = destination
        logger.event(hour, "DESTINATION_DEMANDEE", unit, p.pid, destination=destination)

    sim = SimpleNamespace(
        U=1,
        p_dep=[2, 3],
        p_age=[65, 80],
        p_oxy=[False, True],
        bloque=lambda p: False,
        _declarer_destination=declare,
        x=SimpleNamespace(
            date_iso=lambda day: (dt.date(2025, 1, 1) + dt.timedelta(days=day)).isoformat()
        ),
    )
    return docs, sim, SimpleNamespace(occ=[{1: p}]), log


@pytest.mark.parametrize("axis", VARIANTS)
def test_unknown_documentary_variant_rejected(axis: str) -> None:
    with pytest.raises(ValidationError):
        config(documentary={axis: "unknown"})


@pytest.mark.parametrize("variant", VARIANTS["staff_forecasts"][1:])
def test_new_staff_never_reads_future_readiness_or_departure(variant: str) -> None:
    outputs = []
    for future in (1000, 9000):
        docs, sim, state, log = fake_staff(variant, future)
        for hour in (34, 58, 82, 106):
            assert docs.staff(sim, state, hour, log)
        outputs.append(log.events)
    assert outputs[0] and outputs[0] == outputs[1]
    assert any(e[1] == "DATE_SORTIE_PREVISIONNELLE" for e in outputs[0])


def test_forecasts_are_structurally_distinct_and_use_current_milestones() -> None:
    evidence = StaffSnapshot(0, 3, True, True, True, False, False, 1, False)
    assert forecast_day(evidence, 34, "admission_prior_v1", 1.0) == forecast_day(
        evidence, 58, "admission_prior_v1", 1.0
    )
    assert forecast_day(evidence, 58, "milestones_v1", 1.0) == 1 + forecast_day(
        evidence, 34, "milestones_v1", 1.0
    )
    ready = replace(evidence, medically_ready=True, blocked=False, downstream_confirmed=True)
    assert forecast_day(ready, 58, "milestones_v1", 1.0) < forecast_day(
        evidence, 58, "milestones_v1", 1.0
    )
    with pytest.raises(TypeError):
        StaffSnapshot(**{**vars(evidence), "departure_h": 1000})


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_bad_forecast_uncertainty_rejected(bad: float) -> None:
    evidence = StaffSnapshot(0, 2, False, False, False, False, False, 0, False)
    with pytest.raises(ValueError):
        forecast_day(evidence, 24, "admission_prior_v1", bad)


@pytest.mark.parametrize("variant", VARIANTS["downstream_confirmation"][1:])
def test_confirmation_requires_a_live_request_and_does_not_read_departure(variant: str) -> None:
    docs = DocumentaryMechanisms(config(documentary={"downstream_confirmation": variant}))
    p = SimpleNamespace(pid=1, ready_h=0, conf=False)
    sim = SimpleNamespace(x=SimpleNamespace(ouvre=[True] * 30), bloque=lambda p: False)
    state, log = SimpleNamespace(patients={1: p}), Log()
    for hour in range(100):
        assert docs.confirm(sim, state, p, hour, 0, log)
    assert not log.events
    docs.destination(1, -1, 1, 100)
    for hour in range(101, 500):
        docs.confirm(sim, state, p, hour, 0, log)
    assert len(log.events) == 1 and log.events[0][0] > 100
    assert log.events[0][-1] == {"type_aval": "SMR"}


def test_cancel_and_reopen_invalidate_old_due_date() -> None:
    docs = DocumentaryMechanisms(
        config(documentary={"downstream_confirmation": "request_delay_v1"})
    )
    docs.destination(1, -1, 1, 0)
    first = docs.requests[1]
    docs.destination(1, 1, 0, 10)
    assert 1 not in docs.requests
    docs.destination(1, 0, 2, 100)
    current = docs.requests[1]
    assert current.sequence == 2 and current.destination == 2 and current.due_h > 100
    assert current is not first and not current.confirmed
    docs.destination(1, 2, 2, 120)
    assert docs.requests[1] is current  # Repeated orientation is not a new request.


@pytest.mark.parametrize("reverse", [False, True])
def test_review_is_capacity_limited_oldest_first_and_independent_of_unit_order(
    reverse: bool,
) -> None:
    docs = DocumentaryMechanisms(
        config(documentary={"downstream_confirmation": "review_capacity_v1"})
    )
    patients = {i: SimpleNamespace(pid=i, ready_h=0, conf=False) for i in range(5)}
    # P4 is oldest but no longer present. P3 is not ready.
    for pid in range(5):
        docs.destination(pid, -1, 1, 4 - pid)
    patients[3].ready_h = 1000
    patients.pop(4)
    sim = SimpleNamespace(x=SimpleNamespace(ouvre=[True] * 30), bloque=lambda p: False)
    log = Log()
    order = list(patients.values())
    if reverse:
        order.reverse()
    for p in order:
        if p.ready_h <= 38:
            docs.confirm(sim, SimpleNamespace(patients=patients), p, 38, 0, log)
    assert {e[3] for e in log.events} == {1, 2}
    assert len(log.events) == docs.review_capacity == 2
    assert not docs.requests[0].confirmed
    for p in order:
        if p.ready_h <= 62:
            docs.confirm(sim, SimpleNamespace(patients=patients), p, 62, 0, log)
    assert len(log.events) == 3 and log.events[-1][3] == 0


@pytest.mark.parametrize("variant", VARIANTS["downstream_confirmation"][1:])
def test_closed_calendar_emits_no_confirmation(variant: str) -> None:
    docs = DocumentaryMechanisms(config(documentary={"downstream_confirmation": variant}))
    docs.destination(1, -1, 1, 0)
    p = SimpleNamespace(pid=1, ready_h=0, conf=False)
    sim = SimpleNamespace(x=SimpleNamespace(ouvre=[False] * 30), bloque=lambda p: False)
    log = Log()
    for hour in range(500):
        docs.confirm(sim, SimpleNamespace(patients={1: p}), p, hour, 0, log)
    assert not log.events


@pytest.mark.parametrize("variant", VARIANTS["downstream_confirmation"][1:])
@pytest.mark.parametrize("blocked", [False, True])
def test_current_readiness_is_required_even_after_administrative_delay(
    variant: str, blocked: bool
) -> None:
    docs = DocumentaryMechanisms(config(documentary={"downstream_confirmation": variant}))
    docs.destination(1, -1, 1, 0)
    p = SimpleNamespace(pid=1, ready_h=0 if blocked else 10000, conf=False)
    sim = SimpleNamespace(x=SimpleNamespace(ouvre=[True] * 30), bloque=lambda p: blocked)
    log = Log()
    for hour in range(500):
        docs.confirm(sim, SimpleNamespace(patients={1: p}), p, hour, 0, log)
    assert not log.events and not docs.requests[1].confirmed


@pytest.mark.parametrize("family", ["v041", "local_v1", "hybrid_v1"])
@pytest.mark.parametrize("index", [1, 2])
def test_documentary_changes_preserve_all_physics_with_composed_dynamics(
    family: str, index: int
) -> None:
    base = config(mechanism_family=family, dynamics={"discharges": "rolling_v1"})
    alternate = HospitalConfig.model_validate(
        {
            **base.model_dump(),
            "documentary": {axis: variants[index] for axis, variants in VARIANTS.items()},
        }
    )
    a, b = simulate(base), simulate(alternate)
    assert a.checks == b.checks
    assert exogenous_fingerprint(a.simulation.x) == exogenous_fingerprint(b.simulation.x)
    for field in ("etats", "actions", "cadre", "taches", "sejours"):
        assert getattr(a.journal, field) == getattr(b.journal, field)

    def physical(r: Any) -> list[dict[str, Any]]:
        return [e for e in r.journal.events if e["type"] not in CARE_TYPES]

    assert physical(a) == physical(b)
    assert a.journal.events != b.journal.events
    assert a.resources == b.resources and a.resource_pools == b.resource_pools


def test_documentary_hooks_do_not_require_a_journal_for_physics() -> None:
    cfg = config(
        days=2,
        warmup_days=1,
        documentary={
            "staff_forecasts": "milestones_v1",
            "downstream_confirmation": "review_capacity_v1",
        },
    )
    runs = []
    for logging in (False, True):
        sim = build_simulation(cfg)
        state = _HS.State(sim.x)
        log = _RUN.Journal(sim) if logging else None
        runs.append([sim.step(state, h, log=log) for h in range(sim.x.H)])
    for a, b in zip(*runs, strict=True):
        assert a.keys() == b.keys()
        for k in a:
            assert (a[k] == b[k]).all()


@pytest.mark.parametrize("axis", VARIANTS)
def test_documentary_axis_reservation_and_mutations(axis: str, tmp_path: Path) -> None:
    plan = CohortPlan.model_validate_json(
        (ROOT / f"configs/synthetic/cohort_{axis}_v1.json").read_text()
    )
    registry = compile_registry(plan)
    assert registry.summary()["documentary_by_partition"]["test"][axis] == [VARIANTS[axis][2]]
    raw = plan.model_dump()
    raw["structures"][1]["documentary"][axis] = "v041"
    with pytest.raises(ValidationError, match="mechanism crosses"):
        CohortPlan.model_validate(raw)
    first = registry.worlds[0]
    other = first.model_copy(
        update={
            "world_id": "W_OTHER",
            "config": first.config.model_copy(
                update={"partition": "validation", "hospital_id": "H_OTHER", "seed": 19}
            ),
        }
    )
    with pytest.raises(ValueError, match="crosses partitions"):
        validate_worlds((first, other), split_axis=plan.split_axis)
    freeze(plan, tmp_path / "registry")
    with pytest.raises(ValueError, match="test_protocol"):
        materialize(tmp_path / "registry", tmp_path / "test", partitions=("test",))
    assert not (tmp_path / "test").exists()


def test_new_mechanisms_export_reproducibly_and_feed_patient_care(tmp_path: Path) -> None:
    cfg = config(
        days=3,
        warmup_days=7,
        documentary={
            "staff_forecasts": "milestones_v1",
            "downstream_confirmation": "review_capacity_v1",
        },
    )
    a = generate(cfg, tmp_path / "one")
    b = generate(cfg, tmp_path / "two")
    assert a == b
    assert a["documentary"] == cfg.documentary.model_dump()
    care = observe_care(_events(tmp_path / "one"), cfg)
    assert care and any(c.payload.kind == "departure_plan" for c in care)
    result = prepare_patient_run(
        tmp_path / "one", tmp_path / "patients", census_profile=CensusProfile(), with_care=True
    )
    assert result["counts"]["care_rows"] == result["counts"]["features"] > 0
    assert result["documentary"] == cfg.documentary.model_dump()
    assert not any("18h" in s for s in result["care_assumptions"])
    with gzip.open(tmp_path / "patients/observed/care.jsonl.gz", "rt") as f:
        assert sum(1 for _ in f) == result["counts"]["care_deliveries"]


def test_documentary_change_is_not_a_paired_resource_switch() -> None:
    with pytest.raises(ValueError, match="only mechanism"):
        validate_pair(config(), config(documentary={"staff_forecasts": "milestones_v1"}), 9, 72)

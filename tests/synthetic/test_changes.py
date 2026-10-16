"""Dated organisation changes: clocks, non-anticipation, resources and provenance."""

from __future__ import annotations

import gzip
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from hospitalos.synthetic.changes import apply_changes, boundary_events
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.counterfactual import validate_pair
from hospitalos.synthetic.engine import _HS, build_simulation, simulate
from hospitalos.synthetic.generate import generate
from hospitalos.synthetic.learning import prepare_learning_run
from hospitalos.synthetic.policy import ObservedRulePolicy
from hospitalos.synthetic.policy_loop import PolicyEnvironment, run_policy
from hospitalos.synthetic.registry import CohortPlan, compile_registry

ROOT = Path(__file__).resolve().parents[2]
CHANGES = [
    {
        "kind": "bed_closure",
        "change_id": "C_BEDS",
        "unit_id": "U_MED",
        "additional_closed_beds": 8,
        "starts_at": "2025-01-03T07:00:00+01:00",
        "ends_at": "2025-01-05T15:00:00+01:00",
    },
    {
        "kind": "service_capacity",
        "change_id": "C_IMAGING",
        "resource": "imaging",
        "multiplier": 0.0,
        "starts_at": "2025-01-03T07:00:00+01:00",
        "ends_at": "2025-01-05T15:00:00+01:00",
    },
    {
        "kind": "staffing_shortage",
        "change_id": "C_STAFF",
        "unit_id": "U_MED",
        "additional_absent": 3,
        "starts_at": "2025-01-03T07:00:00+01:00",
        "ends_at": "2025-01-05T15:00:00+01:00",
    },
]


def configured(**changes: Any) -> HospitalConfig:
    raw = json.loads((ROOT / "configs/synthetic/hospital_two_poles.json").read_text())
    raw.update({"days": 7, "warmup_days": 7, **changes})
    return HospitalConfig.model_validate(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        "timezone",
        "naive",
        "fraction",
        "before",
        "after",
        "zero_window",
        "unknown_unit",
        "excess_beds",
        "negative",
        "bool",
        "duplicate",
        "overlap",
        "staff_boundary",
        "resource",
        "extra_field",
    ],
)
def test_invalid_changes_rejected(mutation: str) -> None:
    changes = deepcopy(CHANGES)
    item = changes[0]
    if mutation == "timezone":
        item["starts_at"] = "2025-01-03T07:00:00+02:00"
    elif mutation == "naive":
        item["starts_at"] = "2025-01-03T07:00:00"
    elif mutation == "fraction":
        item["starts_at"] = "2025-01-03T07:01:00+01:00"
    elif mutation == "before":
        item["starts_at"] = "2024-12-31T07:00:00+01:00"
    elif mutation == "after":
        item["ends_at"] = "2025-01-09T00:00:00+01:00"
    elif mutation == "zero_window":
        item["ends_at"] = item["starts_at"]
    elif mutation == "unknown_unit":
        item["unit_id"] = "U_NO"
    elif mutation == "excess_beds":
        item["additional_closed_beds"] = 29
    elif mutation == "negative":
        changes[1]["multiplier"] = -0.1
    elif mutation == "bool":
        item["additional_closed_beds"] = True
    elif mutation == "duplicate":
        changes[1]["change_id"] = item["change_id"]
    elif mutation == "overlap":
        changes.append({**item, "change_id": "OTHER"})
    elif mutation == "staff_boundary":
        changes[2]["starts_at"] = "2025-01-03T09:00:00+01:00"
    elif mutation == "resource":
        changes[1]["resource"] = "operating_room"
    else:
        item["announced_in_advance"] = True
    with pytest.raises(ValidationError):
        configured(changes=changes)


def test_adjacent_changes_and_different_targets_are_allowed() -> None:
    second = {
        **CHANGES[0],
        "change_id": "C_NEXT",
        "starts_at": CHANGES[0]["ends_at"],
        "ends_at": None,
    }
    config = configured(changes=[*CHANGES, second])
    at = boundary_events(config)[4 * 24 + 15]
    assert [r["boundary"] for r in at] == ["end", "end", "end", "start"]


@pytest.mark.parametrize("index", range(3))
def test_exogenous_effect_window_and_restoration(index: int) -> None:
    base = build_simulation(configured()).x
    changed = build_simulation(configured(changes=[CHANGES[index]])).x
    start, end = 7 * 24 + 55, 7 * 24 + 111
    for key in base.pat:
        np.testing.assert_array_equal(base.pat[key], changed.pat[key])
    for key in ("u_politique", "u_reco", "u_expo", "u_renfort", "z_cache", "prevus"):
        np.testing.assert_array_equal(getattr(base, key), getattr(changed, key))
    if index == 0:
        expected = base.fermes.copy()
        expected[0, start:end] = np.minimum(expected[0, start:end] + 8, base.nb_std[0])
        np.testing.assert_array_equal(changed.fermes, expected)
    elif index == 1:
        expected = base.cap_imagerie.copy()
        expected[start:end] = 0
        np.testing.assert_array_equal(changed.cap_imagerie, expected)
    else:
        for h in range(base.H):
            sid = base.sid(h)
            expected_absent = (
                min(base.absents[0, sid] + 3, base.prevus[0, sid])
                if start <= h < end
                else base.absents[0, sid]
            )
            assert changed.absents[0, sid] == expected_absent
        np.testing.assert_array_equal(base.absents[1:], changed.absents[1:])
        np.testing.assert_array_equal(base.remplaces, changed.remplaces)
    with pytest.raises(ValueError, match="already applied"):
        apply_changes(changed, configured(changes=[CHANGES[index]]))


@pytest.mark.parametrize("family", ["v041", "local_v1", "hybrid_v1"])
def test_full_factual_prefix_is_unchanged_and_constraints_hold(family: str) -> None:
    base = simulate(configured(mechanism_family=family))
    changed = simulate(configured(mechanism_family=family, changes=CHANGES))
    first = 7 * 24 + 55
    assert [r for r in base.journal.etats if r["h"] < first] == [
        r for r in changed.journal.etats if r["h"] < first
    ]
    assert [r for r in base.journal.events if r["h"] < first] == [
        r for r in changed.journal.events if r["h"] < first
    ]
    assert base.journal.etats != changed.journal.etats
    assert all(v == 0 for k, v in changed.checks.items() if k != "heures_controlees")
    if family != "v041":
        assert [r for r in base.resource_pools if r["h"] < 55] == [
            r for r in changed.resource_pools if r["h"] < 55
        ]
    audit = [r for r in changed.journal.events if r["type"] == "ORGANISATION_CHANGE"]
    assert len(audit) == 6
    assert {r["h"] for r in audit} == {first, 7 * 24 + 111}


def run_environment(config: HospitalConfig, until: int) -> tuple[PolicyEnvironment, list[Any]]:
    policy = ObservedRulePolicy()
    env = PolicyEnvironment(config, policy.descriptor)
    current = env.reset()
    policy.reset(env.site)
    recommendations = []
    while current.decision_h < until:
        if current.decision_h % 24 == 9:
            batch = policy.recommend(current)
            recommendations.append([u.model_dump() for u in batch.units])
            env.act(batch)
        following = env.advance()
        assert following is not None
        current = following
    return env, recommendations


def test_policy_observation_prefix_cannot_see_future_changes() -> None:
    base, recommendations = run_environment(configured(), 55)
    changed, alternate = run_environment(configured(changes=CHANGES), 55)
    assert base.stream.delivered == changed.stream.delivered

    def observable(env: PolicyEnvironment) -> list[Any]:
        return [r.model_dump(exclude={"run_id", "sample_id"}) for r in env.features]

    assert observable(base) == observable(changed)
    assert recommendations == alternate
    assert base.site == changed.site
    assert "changes" not in changed.site.model_dump()
    assert not any(e["type"] == "ORGANISATION_CHANGE" for e in changed.journal.events)


def test_occupied_beds_are_not_evicted() -> None:
    env, _ = run_environment(configured(changes=[{**CHANGES[0], "additional_closed_beds": 28}]), 55)
    occupied = dict(env.state.occ[0])
    assert occupied
    sim = env.sim
    absolute = sim.h0_rec + 55
    for patient in occupied.values():
        assert sim.demande_fermeture(env.state, 0, patient.bed, absolute)
    phys, closed, opened, count, dirty, free = sim.compte_lits(env.state, 0, absolute)
    assert count == len(occupied) and opened >= count and free == 0
    assert phys == closed + opened and opened == count + dirty + free
    # The closure is already an exclusion for new admissions, not removal of occupants.
    assert sim.lit_compatible(env.state, 0, next(iter(occupied)), absolute) == -1


def test_cleaning_in_progress_finishes_after_capacity_drop() -> None:
    change = {**CHANGES[1], "resource": "cleaning"}
    config = configured(changes=[change])
    sim = build_simulation(config)
    state = _HS.State(sim.x)
    hour = sim.h0_rec + 55
    state.bed_sale[0][0] = 2
    state.net_cours.append((hour + 1, 0, 0, hour - 1, hour - 1))
    state.q_net.append((0, 1, 1, hour))
    state.bed_sale[0][1] = 1
    sim.step(state, hour, politique=False)
    assert state.bed_sale[0][0] == 2 and len(state.net_cours) == 1
    sim.step(state, hour + 1, politique=False)
    assert state.bed_sale[0][0] == 0 and not state.net_cours
    assert state.bed_sale[0][1] == 1


def test_changes_compose_with_new_dynamics() -> None:
    result = simulate(
        configured(
            changes=CHANGES,
            dynamics={
                "arrivals": "shared_bursts_v1",
                "discharges": "rolling_v1",
                "staffing": "persistent_absence_v1",
            },
        )
    )
    assert all(v == 0 for k, v in result.checks.items() if k != "heures_controlees")


def test_unfinished_change_has_no_future_end_event() -> None:
    config = configured(
        changes=[{**CHANGES[0], "starts_at": "2025-01-01T00:00:00+01:00", "ends_at": None}]
    )
    assert list(boundary_events(config)) == [0]
    assert boundary_events(config)[0][0]["boundary"] == "start"


def test_change_order_does_not_change_physics_or_audit() -> None:
    one = simulate(configured(changes=CHANGES))
    two = simulate(configured(changes=list(reversed(CHANGES))))
    assert one.journal.etats == two.journal.etats
    assert one.journal.events == two.journal.events


def test_reproducible_exports_and_learning_excludes_change_schedule(tmp_path: Path) -> None:
    config = configured(changes=CHANGES)
    generate(config, tmp_path / "one")
    generate(config, tmp_path / "two")
    for file in (tmp_path / "one").rglob("*"):
        if file.is_file():
            assert (
                file.read_bytes()
                == (tmp_path / "two" / file.relative_to(tmp_path / "one")).read_bytes()
            )
    with gzip.open(tmp_path / "one/truth/changes.jsonl.gz", "rt") as stream:
        rows = [json.loads(r) for r in stream]
    assert len(rows) == 6 and {r["h"] for r in rows} == {55, 111}
    prepare_learning_run(tmp_path / "one", tmp_path / "learning")
    with gzip.open(tmp_path / "learning/features/asof.jsonl.gz", "rt") as stream:
        contents = stream.read()
    assert "additional_closed_beds" not in contents and "C_BEDS" not in contents
    run_policy(config, ObservedRulePolicy(), tmp_path / "policy")
    assert (tmp_path / "policy/simulation/truth/changes.jsonl.gz").exists()


def test_registry_carries_changes_and_resource_counterfactual_cannot_switch_them() -> None:
    raw = json.loads((ROOT / "configs/synthetic/cohort_structures_v1.json").read_text())
    raw["structures"][0]["changes"] = [{**CHANGES[0], "unit_id": "U_00_00"}]
    registry = compile_registry(CohortPlan.model_validate(raw))
    assert any(w.config.changes for w in registry.worlds)
    with pytest.raises(ValueError, match="only mechanism"):
        validate_pair(configured(), configured(changes=CHANGES), 9, 72)


@pytest.mark.parametrize("hour", [0, 7, 15])
def test_staff_change_at_first_day_keeps_warmup_and_full_slots(hour: int) -> None:
    change = {
        **CHANGES[2],
        "starts_at": f"2025-01-01T{hour:02d}:00:00+01:00",
        "ends_at": "2025-01-02T00:00:00+01:00",
    }
    base = build_simulation(configured()).x
    changed = build_simulation(configured(changes=[change])).x
    offset = 7 * 24
    for h in range(base.H):
        sid = base.sid(h)
        expected = (
            min(base.prevus[0, sid], base.absents[0, sid] + 3)
            if offset + hour <= h < offset + 24
            else base.absents[0, sid]
        )
        assert changed.absents[0, sid] == expected


def test_at_last_boundary_no_end_event_is_exported() -> None:
    config = configured(
        changes=[
            {
                **CHANGES[1],
                "starts_at": "2025-01-07T23:00:00+01:00",
                "ends_at": "2025-01-08T00:00:00+01:00",
            }
        ]
    )
    result = simulate(config)
    audit = [e for e in result.journal.events if e["type"] == "ORGANISATION_CHANGE"]
    assert len(audit) == 1 and audit[0]["payload"]["boundary"] == "start"
    assert audit[0]["h"] == (7 + 7) * 24 - 1


def test_recovery_restores_capacity_without_rewinding_the_queue() -> None:
    sim = build_simulation(configured(changes=[CHANGES[1]]))
    end = sim.h0_rec + 111
    base = build_simulation(configured())
    assert sim.x.cap_imagerie[end - 1] == 0
    assert sim.x.cap_imagerie[end] == base.x.cap_imagerie[end]
    changed = simulate(configured(changes=CHANGES))
    reference = simulate(configured())
    assert [r for r in changed.journal.etats if r["h"] >= end] != [
        r for r in reference.journal.etats if r["h"] >= end
    ]

"""Named people already present at noon remain the same across forecasts and outcomes."""

import json
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from hospitalos.world_model import engine, plan_catalogue, plan_search
from hospitalos.world_model.contracts import PlanConfirmation
from hospitalos.world_model.joint_physics import (
    FloatArray,
    Inputs,
    JointAction,
    JointCase,
    JointResult,
    simulate_joint,
)
from hospitalos.world_model.physics import DATA, ModelUnavailable, verified
from hospitalos.world_model.plan_catalogue import catalogue, reconcile_noon_intake
from hospitalos.world_model.sessions import SessionStore


def test_census_is_a_floor_and_separate_registered_arrivals_enter_once() -> None:
    raw = np.arange(20, dtype=np.float64).reshape(4, 5)
    raw[:, 0] = [0.0, 3.5, 1.5, 0.0]
    original = raw.copy()
    census = np.array([2, 2, 3, 0], dtype=np.int64)
    direct = np.array([0, 1, 2, 1], dtype=np.int64)
    reconciled = reconcile_noon_intake(raw, census, direct)
    np.testing.assert_array_equal(reconciled[:, 0], [2.0, 4.5, 5.0, 1.0])
    np.testing.assert_array_equal(reconciled[:, 1:], raw[:, 1:])
    np.testing.assert_array_equal(raw, original)


@pytest.mark.parametrize("change", ["future_direct", "future_census", "unconfirmed", "unknown"])
def test_noon_catalogue_omits_an_example_with_an_unavailable_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    filename = "noon_cases.json"
    registry = json.loads((DATA / filename).read_bytes())
    site = registry["rives"]
    cases = {p["id"]: p for p in site["cases"]}
    if change == "future_direct":
        cases["A1"]["known_hour"] = 13
    elif change == "future_census":
        cases["A2"]["known_hour"] = 13
    elif change == "unconfirmed":
        site["replacement"]["staff_confirmed"] = False
    else:
        site["example_action_ids"].append("unknown-action")
    altered = tmp_path / filename
    altered.write_text(json.dumps(registry), encoding="utf-8")

    def substitute(path: Path, expected: str) -> Path:
        return altered if path.name == filename else verified(path, expected)

    monkeypatch.setattr(plan_catalogue, "verified", substitute)
    catalogue.cache_clear()
    try:
        if change == "unknown":
            with pytest.raises(ModelUnavailable, match="inconnue"):
                catalogue("rives")
            return
        c = catalogue("rives")
        assert c.example == () and c.items["S1"].description.eligible
        if change == "future_direct":
            assert "A1" not in c.items and c.direct_arrivals.sum() == 0
        elif change == "future_census":
            assert "A2" not in c.items and c.census_admissions[5] == 1
        else:
            assert not c.items["replacement-ide"].description.eligible
    finally:
        catalogue.cache_clear()


@pytest.mark.parametrize("context", ["rives", "parc", "belvedere"])
def test_forecast_and_published_branch_preserve_each_attested_person(
    context: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = dict.fromkeys(("A1", "A2", "A3", "S1", "S2"), True)
    case = engine.cases()[context]
    c = catalogue(context)
    outcomes: list[FloatArray] = []

    def check_factual(
        data: Inputs,
        initial: FloatArray,
        drivers: FloatArray,
        actions: Sequence[JointAction],
        kernel: str,
        *,
        known_cases: Sequence[JointCase],
    ) -> JointResult:
        result = simulate_joint(data, initial, drivers, actions, kernel, known_cases=known_cases)
        assert result.case_present == registered
        outcomes.append(initial.copy())
        return result

    monkeypatch.setattr(plan_search, "simulate_joint", check_factual)
    store = SessionStore(tmp_path / "cohorts.sqlite")
    transport = next(k for k, v in c.items.items() if v.description.kind == "transport")
    for index, ids in enumerate(([], [transport])):
        forecast = simulate_joint(
            c.data,
            c.data["initial"],
            c.data["drivers"],
            [c.items[k].action for k in ids],
            c.kernel,
            known_cases=c.cases,
        )
        assert forecast.case_present == registered
        identifier = str(uuid4())
        store.start(identifier, context)
        request = PlanConfirmation(action_ids=ids, scope_ids=ids, objective="bed_wait")
        store.confirm_plan(identifier, request)
        assert len(outcomes) == index
        state = store.mutate(identifier, "advance", 12)
        if case.publication == 18:
            assert len(outcomes) == index
            state = store.mutate(identifier, "advance", 16)
        assert state.phase == "review" and len(outcomes) == index + 1

    np.testing.assert_array_equal(outcomes[0], outcomes[1])
    for raw, reconciled in (
        (engine.arrays(case, "public")["initial"], c.data["initial"]),
        (engine.arrays(case, "events")["initial"], outcomes[0]),
    ):
        expected = np.maximum(raw[:, 0], c.census_admissions) + c.direct_arrivals
        np.testing.assert_array_equal(reconciled[:, 0], expected)
        np.testing.assert_array_equal(reconciled[:, 1:], raw[:, 1:])

"""A ward decision is fitted to the same census, feasible plans and hospital-wide decision lock."""

from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from hospitalos.world_model import engine, plan_search
from hospitalos.world_model.contracts import PlanMenu, Session
from hospitalos.world_model.joint_physics import simulate_joint
from hospitalos.world_model.plan_catalogue import catalogue, conflicts
from services.api.hybrid_app import create_app


def test_ward_recommendation_matches_exhaustive_local_objective() -> None:
    c = catalogue("rives")
    m = plan_search.unit_menu("rives", "u3", "bed_wait")
    w = 2
    assert m.search.complete and m.ward_state and m.reference.metrics and m.reference.ward_metrics
    assert m.ward_state.admission_queue == pytest.approx(c.data["initial"][w, 0])
    assert m.ward_state.available_beds == pytest.approx(
        max(0, c.data["beds"][w] - c.data["initial"][w, 1:].sum())
    )
    assert {row.id for row in m.ward_state.cases} == {"S1"}
    ids = tuple(sorted(m.scope_ids))
    assert {a.id for a in m.actions} == set(ids)
    raw_ref = simulate_joint(
        c.data, c.data["initial"], c.data["drivers"], [], c.kernel, known_cases=c.cases
    )
    candidates = []
    for count in range(len(ids) + 1):
        for seq in itertools.combinations(ids, count):
            if conflicts(c, seq):
                continue
            actions = [c.items[k].action for k in seq]
            result = simulate_joint(
                c.data, c.data["initial"], c.data["drivers"], actions, c.kernel, known_cases=c.cases
            )
            if any(
                result.realized[a.id] < 1 for a in actions if a.mode in ("admission", "discharge")
            ):
                continue
            if any(
                booked is not None and ((served := result.case_hour[k]) is None or served > booked)
                for k, booked in raw_ref.case_hour.items()
            ):
                continue
            if any(
                a[4] < b[4] - 1e-7 or a[7] > b[7] + 1e-7
                for a, b in (
                    (result.metrics[w], raw_ref.metrics[w]),
                    (result.metrics.sum(axis=0), raw_ref.metrics.sum(axis=0)),
                )
            ):
                continue
            cost = sum(c.items[k].description.cost_eur for k in seq)
            candidates.append((round(result.metrics[w, 0], 8), cost, count, seq))
    winner = m.recommendations[0]
    assert tuple(winner.action_ids) == min(candidates)[3]
    assert winner.ward_metrics and winner.metrics
    assert winner.ward_metrics.bed_wait_patient_hours == pytest.approx(min(candidates)[0])
    assert (
        winner.ward_metrics.bed_wait_patient_hours < m.reference.ward_metrics.bed_wait_patient_hours
    )
    assert winner.ward_metrics.bed_wait_patient_hours != winner.metrics.bed_wait_patient_hours
    assert len(winner.action_ids) > 1
    assert m.search.examined == 2 ** len(ids)
    assert engine.cases()["rives"].context.ward_count == len(winner.ward_impacts)


def test_ward_scopes_funding_and_abstention() -> None:
    receiving = plan_search.unit_menu("rives", "u6", "bed_wait")
    parc = plan_search.unit_menu("parc", "u6", "bed_wait")
    assert receiving.ward_id == parc.ward_id == "u6"
    assert receiving.context_id == "rives" and parc.context_id == "parc"
    assert receiving.reference.id != parc.reference.id
    assert {"redeploy-as", "staffing-as-u1"} <= set(receiving.scope_ids)
    assert "beds-u2" not in receiving.scope_ids and receiving.ward_state
    assert {row.id for row in receiving.ward_state.cases} == {"A2", "A3", "S2"}
    assert receiving.reference.ward_metrics
    assert all(p.ward_metrics is not None for p in receiving.recommendations)
    single = plan_search.unit_menu("rives", "u4", "bed_wait")
    assert len(single.recommendations[0].action_ids) == 1
    quiet = plan_search.unit_menu("rives", "u1", "bed_wait")
    assert quiet.recommendations == [quiet.reference]


def test_unit_request_and_atomic_confirmations_are_bound_to_their_ward(tmp_path: Path) -> None:
    path = "/world-model/sessions/" + str(uuid4())
    db = tmp_path / "decision.sqlite"
    with (
        TestClient(create_app(world_model_db=db)) as a,
        TestClient(create_app(world_model_db=db)) as b,
    ):
        assert a.put(path, json={"context_id": "rives"}).is_success
        assert a.get(path + "/plans?ward_id=missing").status_code == 422
        requests: list[dict[str, object]] = []
        for wid in ("u3", "u6"):
            menu = PlanMenu.model_validate_json(
                a.get(path + f"/plans?ward_id={wid}&objective=bed_wait").content
            )
            assert menu.ward_id == wid and menu.context_id == "rives"
            requests.append(
                {
                    "ward_id": wid,
                    "objective": "bed_wait",
                    "action_ids": menu.recommendations[0].action_ids,
                }
            )
        first, second = requests
        assert (
            a.post(path + "/plans/confirm", json={**first, "context_id": "parc"}).status_code == 409
        )
        assert a.post(path + "/plans/confirm", json={**first, "ward_id": "u6"}).status_code == 409
        assert a.post(path + "/plans/confirm", json={**first, "scope_ids": []}).status_code == 422
        ready = Barrier(2)

        def submit(client: TestClient, body: dict[str, object]) -> int:
            ready.wait(timeout=10)
            return int(client.post(path + "/plans/confirm", json=body).status_code)

        with ThreadPoolExecutor(max_workers=2) as pool:
            r1 = pool.submit(submit, a, first)
            r2 = pool.submit(submit, b, second)
            statuses = [r1.result(), r2.result()]
        assert sorted(statuses) == [200, 409]
        winner, loser = requests[statuses.index(200)], requests[statuses.index(409)]
        assert a.post(path + "/plans/confirm", json=winner).is_success
        assert a.post(path + "/plans/confirm", json={**winner, "ward_id": None}).status_code == 409
        assert b.get(path + "/plans", params={"ward_id": str(loser["ward_id"])}).status_code == 409
    with TestClient(create_app(world_model_db=db)) as client:
        saved = Session.model_validate_json(client.get(path).content)
        assert saved.decision_ward_id == winner["ward_id"]
        assert saved.plan_snapshot and saved.plan_snapshot.ward_id == saved.decision_ward_id
        assert saved.plan_snapshot.context_id == saved.context.id == "rives"
        assert saved.confirmed_plan == saved.plan_snapshot.recommendations[0]
        events = [e for e in saved.journal if e.event == "confirmed"]
        assert len(events) == 1 and events[0].ward_id == saved.decision_ward_id


def test_manual_plan_requires_matching_preview_and_preserves_all_ward_states(
    tmp_path: Path,
) -> None:
    path = "/world-model/sessions/" + str(uuid4())
    with TestClient(create_app(world_model_db=tmp_path / "manual.sqlite")) as client:
        assert client.put(path, json={"context_id": "rives"}).is_success
        body = {
            "ward_id": "u6",
            "context_id": "rives",
            "objective": "bed_wait",
            "action_ids": ["replacement-ide"],
        }
        adjacent = client.get(path + "/wards/u3/state").json()
        assert adjacent["ward_id"] == "u3" and adjacent["context_id"] == "rives"
        assert adjacent["as_of_hour"] == 12
        assert client.get(path + "/wards/u99/state").status_code == 422
        result = client.post(path + "/plans/preview", json=body)
        assert result.is_success
        preview = result.json()
        assert preview["context_id"] == "rives" and preview["ward_id"] == "u6"
        assert preview["feasible"] and not preview["access_warnings"] and preview["ward_metrics"]
        assert client.post(path + "/plans/confirm", json=body).status_code == 409
        assert (
            client.post(path + "/plans/preview", json={**body, "action_ids": ["S1"]}).status_code
            == 422
        )
        assert (
            client.post(path + "/plans/preview", json={**body, "context_id": "parc"}).status_code
            == 409
        )
        assert (
            client.post(path + "/plans/confirm", json={**body, "preview_id": "wrong"}).status_code
            == 409
        )
        for ids in (["S2"], ["redeploy-as"]):
            rejected = {**body, "action_ids": ids}
            p = client.post(path + "/plans/preview", json=rejected).json()
            assert not p["feasible"] or p["access_warnings"]
            assert (
                client.post(
                    path + "/plans/confirm", json={**rejected, "preview_id": p["id"]}
                ).status_code
                == 409
            )
        request = {**body, "preview_id": preview["id"]}
        saved = client.post(path + "/plans/confirm", json=request)
        assert saved.is_success and saved.json()["confirmed_plan"] == preview
        assert saved.json()["plan_snapshot"]["reference"]["ward_id"] == "u6"
        assert client.post(path + "/plans/confirm", json=request).json() == saved.json()
        assert client.get(path + "/wards/u3/state").json() == adjacent
        assert (
            client.get(path + "/wards/u6/state").json()
            == saved.json()["plan_snapshot"]["ward_state"]
        )

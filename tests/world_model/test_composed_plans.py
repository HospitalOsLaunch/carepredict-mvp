"""The real noon API recommends, reserves, journals and observes a complete joint plan."""

from __future__ import annotations

import itertools
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from typing import Literal
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from numpy.typing import NDArray

from hospitalos.world_model import engine, plan_catalogue, plan_search
from hospitalos.world_model.contracts import PlanEvaluation, PlanMenu, Session
from hospitalos.world_model.joint_physics import simulate_joint
from hospitalos.world_model.physics import DATA, verified
from hospitalos.world_model.plan_catalogue import catalogue
from services.api.hybrid_app import create_app


def session(response: Response) -> Session:
    assert response.is_success, response.text
    return Session.model_validate_json(response.content)


def start(client: TestClient, site: str = "rives") -> tuple[str, Session]:
    path = f"/world-model/sessions/{uuid4()}"
    state = session(client.put(path, json={"context_id": site}))
    assert state.plan_version and state.confirmed_plan is None and state.plan_report is None
    return path, state


def test_example_subsets_and_conditional_donor_share_one_operator(tmp_path: Path) -> None:
    with TestClient(create_app(world_model_db=tmp_path / "rives.db")) as client:
        path, _ = start(client)
        menu = PlanMenu.model_validate_json(client.get(path + "/plans?objective=bed_wait").content)
        ids = menu.example_action_ids
        assert set(ids) == {
            "S1",
            "S2",
            "A1",
            "A2",
            "A3",
            "replacement-ide",
            "redeploy-as",
            "staffing-as-u1",
        }
        assert not menu.search.complete
        full = PlanEvaluation.model_validate_json(
            client.post(
                path + "/plans/preview", json={"action_ids": ids, "objective": "bed_wait"}
            ).content
        )
        assert full.feasible and full.cost_eur == 330
        baseline = menu.reference.metrics
        assert full.metrics is not None and baseline is not None
        assert full.realized == {k: 1 if k in {"S1", "S2", "A1", "A2", "A3"} else 240 for k in ids}
        assert full.metrics.bed_wait_patient_hours < baseline.bed_wait_patient_hours
        assert full.metrics.transfer_queue > baseline.transfer_queue
        assert full.metrics.smr_transfers != baseline.smr_transfers
        assert full.metrics.transport_used != baseline.transport_used
        assert full.metrics.beds_cleaned != baseline.beds_cleaned
        assert full.metrics.available_beds < baseline.available_beds
        blocked = plan_search.preview("rives", ["redeploy-as"])
        assert not blocked.feasible and blocked.metrics is None
        assert plan_search.preview("rives", ["redeploy-as", "staffing-as-u1"]).feasible

        narrowed = PlanMenu.model_validate_json(
            client.post(
                path + "/plans/optimize", json={"action_ids": ids, "objective": "bed_wait"}
            ).content
        )
        assert narrowed.search.examined == 2 ** len(ids) == 256 and narrowed.search.complete
        assert 0 < narrowed.search.feasible <= narrowed.search.evaluated < narrowed.search.examined
        scored = []
        for count in range(len(ids) + 1):
            for sub in itertools.combinations(sorted(ids), count):
                val = plan_search.preview("rives", sub)
                if val.feasible and not val.access_warnings and val.metrics is not None:
                    scored.append(
                        (round(val.metrics.bed_wait_patient_hours, 8), val.cost_eur, count, sub)
                    )
        assert tuple(narrowed.recommendations[0].action_ids) == min(scored)[-1]
        best = narrowed.recommendations[0]
        assert 1 < len(best.action_ids) < len(ids)
        assert (
            plan_search.menu("rives", "bed_wait", best.action_ids).recommendations[0].id == best.id
        )
        for p in narrowed.recommendations:
            assert set(p.action_ids) <= set(ids)
        raw = catalogue("rives")
        np.testing.assert_allclose(
            raw.data["initial"][:, 0] - engine.public_projection("rives").data["initial"][:, 0],
            raw.direct_arrivals,
        )
        assert sum(raw.direct_arrivals) == 1
        body = {"action_ids": ids[::-1], "scope_ids": ids, "objective": "bed_wait"}
        confirmed = session(client.post(path + "/plans/confirm", json=body))
        assert confirmed.selected_id == full.id and confirmed.plan_snapshot == narrowed
        assert confirmed.observation is None and confirmed.plan_report is None
        assert (
            session(client.post(path + "/plans/confirm", json={**body, "action_ids": ids}))
            == confirmed
        )
        assert (
            client.post(
                path + "/plans/confirm", json={**body, "objective": "transfer_queue"}
            ).status_code
            == 409
        )
        assert (
            client.post(path + "/plans/confirm", json={**body, "scope_ids": []}).status_code == 422
        )
        other_scope = [*ids, next(a.id for a in menu.actions if a.id not in ids)]
        assert (
            client.post(
                path + "/plans/confirm", json={**body, "scope_ids": other_scope}
            ).status_code
            == 409
        )
        assert client.post(path + "/confirm", json={"option_id": "reference"}).status_code == 409
        assert session(client.get(path)) == confirmed
        final = session(client.post(path + "/advance", json={"from_hour": 12}))
        read = final.plan_report
        assert read is not None and read.realized is not None and read.actual_metrics is not None
        assert final.observation is not None
        assert final.observation.observed_stock == pytest.approx(read.actual_metrics.transfer_queue)
        assert read.realized["S1"] == read.realized["S2"] == 1
        assert read.realized["A1"] == read.realized["A2"] == 1 and read.realized["A3"] == 0
        assert all(x.plan.id != full.id for x in read.alternatives)
        assert all(o.reconstruction is None for o in final.options)
        assert final.confirmed_plan == full
        assert session(client.get(path)) == final
        assert PlanMenu.model_validate_json(client.get(path + "/plans").content) == narrowed


@pytest.mark.parametrize("context,hour", [("parc", 16), ("belvedere", 18)])
def test_future_ledger_is_not_read_or_imputed_into_a_partial_report(
    tmp_path: Path, context: str, hour: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = []
    factual_calls = []
    real = engine.arrays
    sim = simulate_joint

    def record(
        case: engine.Case, scope: Literal["public", "events"]
    ) -> dict[str, NDArray[np.generic]]:
        reads.append(scope)
        return real(case, scope)

    def record_sim(*args, **kwargs):  # type: ignore[no-untyped-def]
        factual_calls.append(tuple(a.id for a in args[3]))
        return sim(*args, **kwargs)

    monkeypatch.setattr(engine, "arrays", record)
    monkeypatch.setattr(plan_search, "simulate_joint", record_sim)
    with TestClient(create_app(world_model_db=tmp_path / "partial.db")) as client:
        path, _ = start(client, context)
        menu = PlanMenu.model_validate_json(client.get(path + "/plans?objective=bed_wait").content)
        selected = menu.recommendations[0]
        session(
            client.post(
                path + "/plans/confirm",
                json={"action_ids": selected.action_ids, "objective": "bed_wait"},
            )
        )
        assert "events" not in reads and not factual_calls
        result = session(client.post(path + "/advance", json={"from_hour": 12}))
        if hour == 18:
            assert result.plan_report is None and result.observation is None
            assert "events" not in reads
            result = session(client.post(path + "/advance", json={"from_hour": 16}))
        assert result.plan_report is not None and result.observation is not None
        assert result.plan_report.realized is None and result.plan_report.actual_metrics is None
        assert result.observation.observed_stock is None and result.hour == hour
        assert result.plan_report.alternatives
        assert reads.count("events") == 1 and factual_calls == [tuple(selected.action_ids)]


def test_rejected_programs_leave_no_claims_or_journal_entries(tmp_path: Path) -> None:
    with TestClient(create_app(world_model_db=tmp_path / "invalid.db")) as client:
        path, opened = start(client)
        for ids in (["transport-u1", "transport-u2"], ["staffing-ide-u2", "replacement-ide"]):
            req = {"action_ids": ids, "objective": "bed_wait"}
            preview = PlanEvaluation.model_validate_json(
                client.post(path + "/plans/preview", json=req).content
            )
            assert preview.conflicts and not preview.feasible and preview.metrics is None
            assert client.post(path + "/plans/confirm", json=req).status_code == 409
        for body in (
            {"action_ids": ["unknown"]},
            {"action_ids": ["S1", "S1"]},
            {"action_ids": ["S1"], "scope_ids": ["S2"]},
        ):
            assert (
                client.post(
                    path + "/plans/confirm", json={**body, "objective": "bed_wait"}
                ).status_code
                == 422
            )
        assert session(client.get(path)) == opened
        zero = session(
            client.post(
                path + "/plans/confirm", json={"action_ids": [], "objective": "uncovered_care"}
            )
        )
        assert zero.confirmed_plan is not None and not zero.confirmed_plan.action_ids
        assert zero.phase == "confirmed" and zero.decision_objective == "uncovered_care"


def test_single_and_composed_confirmations_compete_for_one_session(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.db"
    with (
        TestClient(create_app(world_model_db=database)) as first,
        TestClient(create_app(world_model_db=database)) as second,
    ):
        path, _ = start(first)
        first.get(path + "/plans")
        ready = Barrier(2)

        def submit(client: TestClient, endpoint: str, payload: dict[str, object]) -> int:
            ready.wait(timeout=15)
            return int(client.post(path + endpoint, json=payload).status_code)

        with ThreadPoolExecutor(2) as pool:
            a = pool.submit(submit, first, "/confirm", {"option_id": "reference"})
            b = pool.submit(
                submit, second, "/plans/confirm", {"action_ids": [], "objective": "bed_wait"}
            )
            assert sorted((a.result(timeout=15), b.result(timeout=15))) == [200, 409]
        state = session(first.get(path))
        assert len([x for x in state.journal if x.event == "confirmed"]) == 1
        with TestClient(create_app(world_model_db=database)) as restored:
            assert session(restored.get(path)) == state


def test_an_existing_unconfirmed_midi5_session_gains_the_composer(tmp_path: Path) -> None:
    database = tmp_path / "upgrade.db"
    with TestClient(create_app(world_model_db=database)) as client:
        path, state = start(client)
        with sqlite3.connect(database) as conn:
            conn.execute(
                "UPDATE demo_world_model_sessions SET snapshot=? WHERE id=?",
                (
                    state.model_dump_json(
                        exclude={"plan_version", "confirmed_plan", "plan_snapshot", "plan_report"}
                    ),
                    state.id,
                ),
            )
        upgraded = session(client.get(path))
        assert upgraded.plan_version == engine.plan_version()
        assert upgraded.journal == state.journal and upgraded.options == state.options


def test_access_tradeoffs_and_ward_deltas_are_auditable() -> None:
    reference = plan_search.preview("rives", [])
    shortlisted = plan_search.menu("rives", "uncovered_care", ["transport-u8"])
    transport = plan_search.preview("rives", ["transport-u8"])
    assert transport.feasible and transport.metrics is not None and reference.metrics is not None
    assert transport.access_warnings and all(
        "transport-u8" not in p.action_ids for p in shortlisted.recommendations
    )
    assert {w.ward_id for w in transport.ward_impacts} == {
        f"u{i + 1}" for i in range(len(engine.cases()["rives"].wards))
    }
    assert any(abs(w.transfer_queue) > 1e-4 for w in transport.ward_impacts)
    for name in (
        "transfer_queue",
        "admissions",
        "redirected_patients",
        "transport_used",
        "beds_cleaned",
        "smr_transfers",
        "available_beds",
    ):
        aggregate_delta = getattr(transport.metrics, name) - getattr(reference.metrics, name)
        assert sum(getattr(w, name) for w in transport.ward_impacts) == pytest.approx(
            aggregate_delta
        )
    assert sum(w.care_minutes for w in transport.ward_impacts) == pytest.approx(
        transport.metrics.uncovered_ide_minutes
        + transport.metrics.uncovered_as_minutes
        - reference.metrics.uncovered_ide_minutes
        - reference.metrics.uncovered_as_minutes
    )
    before = reference.model_copy(update={"case_hours": {"A1": 13}})
    delayed = reference.model_copy(update={"case_hours": {"A1": 14}})
    assert any("A1 prévu à 14 h" in m for m in plan_search.access_warnings(delayed, before))


def test_plan_identity_is_independent_of_unpublished_trajectory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chosen = ["S1", "replacement-ide"]
    initial = plan_search.preview("rives", chosen)
    case = engine.cases()["rives"]
    monkeypatch.setitem(engine.cases(), "rives", replace(case, events_sha="9" * 64))
    assert plan_search.preview("rives", chosen) == initial


def test_unconfirmed_direct_arrival_does_not_create_census_patient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filename = "noon_cases.json"
    doc = json.loads((DATA / filename).read_bytes())
    direct = next(c for c in doc["rives"]["cases"] if c["id"] == "A1")
    assert direct["source"] == "registered_direct_arrival"
    direct["authorized"] = False
    altered = tmp_path / filename
    altered.write_text(json.dumps(doc))

    def substitute(path: Path, expected: str) -> Path:
        return altered if path.name == filename else verified(path, expected)

    monkeypatch.setattr(plan_catalogue, "verified", substitute)
    catalogue.cache_clear()
    try:
        c = catalogue("rives")
        assert c.direct_arrivals.sum() == 0
        assert not c.items["A1"].description.eligible
        assert "A1" not in {case.id for case in c.cases}
    finally:
        catalogue.cache_clear()

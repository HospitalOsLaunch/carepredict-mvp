"""Black-box, offline checks for the clock and information boundary of the cockpit."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from math import isfinite
from pathlib import Path
from threading import Barrier
from typing import Literal
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from numpy.typing import NDArray

from hospitalos.world_model import engine
from hospitalos.world_model.contracts import Context, Contexts, Session
from hospitalos.world_model.physics import rollout
from services.api.hybrid_app import create_app

Forecasts = dict[str, tuple[float, float, list[float]]]
CensusArray = NDArray[np.generic]


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "world-model.sqlite"


@pytest.fixture
def client(db: Path) -> Iterator[TestClient]:
    with TestClient(create_app(world_model_db=db)) as instance:
        yield instance


def success(response: Response) -> Session:
    assert 200 <= response.status_code < 300, response.text
    state = Session.model_validate_json(response.content, strict=True)
    assert "observation" in state.model_fields_set
    assert all(
        {"reconstruction", "reconstructed_by_ward"} <= o.model_fields_set for o in state.options
    )
    return state


def context_for(client: TestClient, feed: str) -> Context:
    response = client.get("/world-model/contexts")
    assert response.is_success, response.text
    catalogue = Contexts.model_validate_json(response.content, strict=True)
    assert catalogue.model_version
    contexts = catalogue.contexts
    assert len({context.id for context in contexts}) == len(contexts)
    return next(row for row in contexts if row.feed == feed)


def start(client: TestClient, context: Context) -> tuple[str, Session]:
    path = f"/world-model/sessions/{uuid4()}"
    state = success(client.put(path, json={"context_id": context.id}))
    assert state.context.id == context.id
    assert state.phase == "planning"
    assert state.hour == state.decision_hour == 12
    assert state.target_hour == 16
    assert state.selected_id is None
    assert success(client.get(path)) == state
    return path, state


def before_publication(state: Session) -> None:
    assert state.observation is None
    for option in state.options:
        assert option.reconstruction is None
        assert option.reconstructed_by_ward is None


def public_forecasts(state: Session) -> Forecasts:
    return {
        option.id: (option.forecast, option.jepa_forecast, option.by_ward)
        for option in state.options
    }


def check_forecasts(state: Session) -> None:
    wards = state.wards
    assert len(wards) == state.context.ward_count > 0
    assert len({ward.id for ward in wards}) == len(wards)
    assert len(public_forecasts(state)) == len(state.options) > 1
    assert state.reference_id in public_forecasts(state)
    for option in state.options:
        per_ward = option.by_ward
        assert len(per_ward) == len(wards)
        assert all(
            isfinite(x) and 0 <= x <= ward.beds + 1e-7
            for x, ward in zip(per_ward, wards, strict=True)
        )
        assert option.forecast == pytest.approx(sum(per_ward))


def check_review(state: Session, initial_forecasts: Forecasts) -> None:
    assert state.phase == "review"
    assert public_forecasts(state) == initial_forecasts
    observation = state.observation
    assert observation is not None
    assert observation.sample_hour == state.target_hour == 16
    assert observation.published_hour == state.publication_hour == state.hour
    assert 0 <= observation.visible_components <= observation.total_components
    assert len(observation.by_ward) == len(state.wards)
    observed = observation.by_ward
    if any(x is None for x in observed):
        assert observation.observed_stock is None
    else:
        assert observation.observed_stock == pytest.approx(
            sum(x for x in observed if x is not None)
        )
    for option in state.options:
        reconstructed = option.reconstructed_by_ward
        assert reconstructed is not None
        assert len(reconstructed) == len(state.wards)
        assert option.reconstruction == pytest.approx(sum(reconstructed))
        for value, ward in zip(reconstructed, state.wards, strict=True):
            assert isfinite(value) and 0 <= value <= ward.beds + 1e-7
        if option.id == state.selected_id:
            for expected, actual in zip(observed, reconstructed, strict=True):
                if expected is not None:
                    assert actual == pytest.approx(expected)


@pytest.mark.parametrize(
    "feed,release,reported,components,complete_wards",
    [("full", 16, 40, 40, 8), ("partial", 16, 15, 35, 1), ("delayed", 18, 7, 35, 0)],
)
def test_asof_and_retry_for_every_feed(
    client: TestClient,
    db: Path,
    feed: str,
    release: int,
    reported: int,
    components: int,
    complete_wards: int,
) -> None:
    context = context_for(client, feed)
    path, initial = start(client, context)
    forecasts = public_forecasts(initial)
    check_forecasts(initial)
    before_publication(initial)
    assert initial.publication_hour == release
    assert success(client.put(path, json={"context_id": context.id})) == initial

    selected = next(option.id for option in initial.options if option.id != initial.reference_id)
    confirmed = success(client.post(f"{path}/confirm", json={"option_id": selected}))
    assert confirmed.phase == "confirmed" and confirmed.hour == 12
    assert confirmed.selected_id == selected
    assert public_forecasts(confirmed) == forecasts
    before_publication(confirmed)
    assert len(confirmed.journal) > len(initial.journal)
    assert success(client.post(f"{path}/confirm", json={"option_id": selected})) == confirmed
    assert (
        client.post(f"{path}/confirm", json={"option_id": initial.reference_id}).status_code == 409
    )
    assert success(client.get(path)) == confirmed

    next_state = success(client.post(f"{path}/advance", json={"from_hour": 12}))
    assert next_state.hour == 16
    if release == 18:
        assert next_state.phase == "awaiting_report"
        before_publication(next_state)
        assert success(client.post(f"{path}/advance", json={"from_hour": 12})) == next_state
        next_state = success(client.post(f"{path}/advance", json={"from_hour": 16}))
    check_review(next_state, forecasts)
    observation = next_state.observation
    assert observation is not None
    assert observation.visible_components == reported
    assert observation.total_components == components
    assert sum(x is not None for x in observation.by_ward) == complete_wards

    # A retried HTTP request and a new application instance must see the same committed journal.
    assert (
        success(client.post(f"{path}/advance", json={"from_hour": 16 if release == 18 else 12}))
        == next_state
    )
    with TestClient(create_app(world_model_db=db)) as restarted:
        assert success(restarted.get(path)) == next_state
        assert success(restarted.put(path, json={"context_id": context.id})) == next_state


def test_invalid_transition_cannot_edit_context_or_clock(client: TestClient) -> None:
    context = context_for(client, "delayed")
    path, state = start(client, context)
    other_context = context_for(client, "full")
    unknown = f"/world-model/sessions/{uuid4()}"
    assert client.get(unknown).status_code == 404
    assert client.put(path, json={"context_id": other_context.id}).status_code == 409
    assert client.post(f"{path}/advance", json={"from_hour": 12}).status_code == 409
    invalid = client.post(f"{path}/confirm", json={"option_id": "option-absente"})
    assert invalid.status_code in (404, 422)
    forged = client.post(f"{path}/advance", json={"from_hour": True, "publication_hour": 12})
    assert forged.status_code == 422
    assert success(client.get(path)) == state


def test_two_competing_validations_commit_one_choice(client: TestClient, db: Path) -> None:
    path, initial = start(client, context_for(client, "full"))
    first, second = [option.id for option in initial.options[:2]]
    ready = Barrier(2)

    def confirm(instance: TestClient, option_id: str) -> tuple[str, int]:
        ready.wait(timeout=10)
        response = instance.post(f"{path}/confirm", json={"option_id": option_id})
        return option_id, response.status_code

    with (
        TestClient(create_app(world_model_db=db)) as other,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        futures = [pool.submit(confirm, client, first), pool.submit(confirm, other, second)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(code for _, code in results) == [200, 409]
    winner = next(option_id for option_id, code in results if code == 200)
    committed = success(client.get(path))
    assert committed.selected_id == winner
    assert committed.phase == "confirmed"
    before_publication(committed)


def test_future_tape_is_opened_only_at_publication_for_one_chosen_branch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[str] = []
    branch_sizes: list[int] = []
    real_arrays = engine.arrays

    def record_read(
        case: engine.Case, scope: Literal["public", "events"]
    ) -> dict[str, CensusArray]:
        reads.append(scope)
        return real_arrays(case, scope)

    def record_rollout(
        data: dict[str, CensusArray],
        initial: CensusArray,
        drivers: CensusArray,
        schedules: CensusArray,
        kernel_sha: str,
    ) -> tuple[CensusArray, CensusArray]:
        if "events" in reads:
            branch_sizes.append(len(schedules))
        return rollout(data, initial, drivers, schedules, kernel_sha)

    monkeypatch.setattr(engine, "arrays", record_read)
    monkeypatch.setattr(engine, "rollout", record_rollout)
    path, state = start(client, context_for(client, "delayed"))
    selected = next(o.id for o in state.options if o.id != state.reference_id)
    success(client.post(f"{path}/confirm", json={"option_id": selected}))
    at_16 = success(client.post(f"{path}/advance", json={"from_hour": 12}))
    before_publication(at_16)
    assert "events" not in reads
    reviewed = success(client.post(f"{path}/advance", json={"from_hour": 16}))
    assert reads.count("events") == 1 and branch_sizes == [1]
    assert reviewed.selected_id == selected


def test_new_publication_rule_does_not_rewrite_an_existing_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = context_for(client, "delayed")
    path, state = start(client, context)
    success(client.post(f"{path}/confirm", json={"option_id": state.reference_id}))
    cases = engine.cases()
    monkeypatch.setitem(cases, context.id, replace(cases[context.id], publication=16))
    changed = client.post(f"{path}/advance", json={"from_hour": 12})
    assert changed.status_code == 409
    stored = success(client.get(path))
    assert stored.publication_hour == 18 and stored.hour == 12
    before_publication(stored)


def test_unavailable_public_artifact_cannot_create_a_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = context_for(client, "full")
    path = f"/world-model/sessions/{uuid4()}"
    engine.public_projection.cache_clear()
    monkeypatch.setattr(engine, "DATA", tmp_path)
    unavailable = client.put(path, json={"context_id": context.id})
    assert unavailable.status_code == 503
    assert client.get(path).status_code == 404


def test_catalogue_rejects_a_publication_before_its_measured_hour(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = deepcopy(engine.manifest())
    delayed = next(context for context in metadata["cases"] if context["feed"] == "delayed")
    delayed["published_hour"] = 12
    monkeypatch.setattr(engine, "manifest", lambda: metadata)
    engine.cases.cache_clear()
    try:
        assert client.get("/world-model/contexts").status_code == 503
    finally:
        engine.cases.cache_clear()

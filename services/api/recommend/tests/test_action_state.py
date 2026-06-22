"""Tests for Gate C action state transitions and audit trail."""

from __future__ import annotations

import inspect
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.recommend.state_machine import InvalidActionTransition, validate_transition
from services.api.routers.actions import ActionNotFoundError, ActionStore, get_action_store, router
from services.api.schemas.actions import ActionEvent, ActionTransitionResponse, StoredRecommendation


def test_state_machine_accepts_legal_transitions() -> None:
    assert validate_transition("proposed", "approved")
    assert validate_transition("approved", "in_progress")
    assert validate_transition("in_progress", "done")
    assert validate_transition("in_progress", "dismissed")


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [("done", "proposed"), ("dismissed", "in_progress")],
)
def test_state_machine_rejects_terminal_transitions(from_status: str, to_status: str) -> None:
    with pytest.raises(InvalidActionTransition):
        validate_transition(from_status, to_status)  # type: ignore[arg-type]


def test_transition_route_updates_state_and_appends_event() -> None:
    store = InMemoryActionStore()
    client = _client(store)

    response = client.post(
        "/actions/rec_123/transition",
        json={"to_status": "approved", "actor": "sarah.johnson", "reason": "COO approval"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommendation"]["status"] == "approved"
    assert body["event"]["from_status"] == "proposed"
    assert body["event"]["to_status"] == "approved"
    assert body["event"]["actor"] == "sarah.johnson"

    events = client.get("/actions/rec_123/events").json()["events"]
    assert [event["to_status"] for event in events] == ["proposed", "approved"]


@pytest.mark.parametrize(
    ("recommendation_id", "to_status"),
    [("rec_done", "proposed"), ("rec_dismissed", "in_progress")],
)
def test_illegal_transition_route_returns_409(recommendation_id: str, to_status: str) -> None:
    response = _client(InMemoryActionStore()).post(
        f"/actions/{recommendation_id}/transition",
        json={"to_status": to_status, "actor": "tester"},
    )

    assert response.status_code == 409


def test_unknown_recommendation_returns_404() -> None:
    response = _client(InMemoryActionStore()).post(
        "/actions/rec_missing/transition",
        json={"to_status": "approved", "actor": "tester"},
    )

    assert response.status_code == 404


def test_failed_event_insert_rolls_back_status_update() -> None:
    store = InMemoryActionStore(fail_event_insert=True)

    with pytest.raises(RuntimeError):
        store.transition(
            recommendation_id="rec_123",
            to_status="approved",
            actor="tester",
            reason="force rollback",
        )

    assert store.recommendations["rec_123"].status == "proposed"
    assert [event.to_status for event in store.events(recommendation_id="rec_123")] == ["proposed"]


def test_action_events_store_is_append_only() -> None:
    source = inspect.getsource(ActionStore)
    assert "INSERT INTO actions.action_events" in source
    assert "UPDATE actions.action_events" not in source
    assert "DELETE FROM actions.action_events" not in source


class InMemoryActionStore:
    """ActionStore test double with transactional rollback semantics."""

    def __init__(self, *, fail_event_insert: bool = False) -> None:
        self.fail_event_insert = fail_event_insert
        self.recommendations = {
            "rec_123": _stored("rec_123", "proposed"),
            "rec_done": _stored("rec_done", "done"),
            "rec_dismissed": _stored("rec_dismissed", "dismissed"),
        }
        self._events = {
            "rec_123": [_event("rec_123", None, "proposed")],
            "rec_done": [
                _event("rec_done", None, "proposed"),
                _event("rec_done", "in_progress", "done"),
            ],
            "rec_dismissed": [
                _event("rec_dismissed", None, "proposed"),
                _event("rec_dismissed", "approved", "dismissed"),
            ],
        }

    def transition(
        self,
        *,
        recommendation_id: str,
        to_status: str,
        actor: str,
        reason: str | None,
    ) -> ActionTransitionResponse:
        current = self.recommendations.get(recommendation_id)
        if current is None:
            raise ActionNotFoundError(f"unknown recommendation_id: {recommendation_id}")
        validate_transition(current.status, to_status)  # type: ignore[arg-type]
        old_recommendation = current
        old_events = deepcopy(self._events[recommendation_id])
        try:
            updated = current.model_copy(
                update={"status": to_status, "updated_at": datetime.now(UTC)}
            )
            self.recommendations[recommendation_id] = updated
            if self.fail_event_insert:
                raise RuntimeError("event insert failed")
            event = _event(
                recommendation_id,
                old_recommendation.status,
                to_status,
                actor=actor,
                reason=reason,
            )
            self._events[recommendation_id].append(event)
        except Exception:
            self.recommendations[recommendation_id] = old_recommendation
            self._events[recommendation_id] = old_events
            raise
        return ActionTransitionResponse(recommendation=updated, event=event)

    def events(self, *, recommendation_id: str) -> list[ActionEvent]:
        if recommendation_id not in self.recommendations:
            raise ActionNotFoundError(f"unknown recommendation_id: {recommendation_id}")
        return self._events[recommendation_id]


def _client(store: InMemoryActionStore) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_action_store] = lambda: store
    return TestClient(app)


def _stored(recommendation_id: str, status: str) -> StoredRecommendation:
    now = datetime(2025, 1, 1, tzinfo=UTC)
    return StoredRecommendation(
        recommendation_id=recommendation_id,
        hospital_id="hosp-001",
        service_id="urg-001",
        lever="prioritize_discharge",
        severity="high",
        score=0.5,
        projected_impact_siips=-12.0,
        status=status,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
    )


def _event(
    recommendation_id: str,
    from_status: str | None,
    to_status: str,
    *,
    actor: str = "system",
    reason: str | None = None,
) -> ActionEvent:
    return ActionEvent(
        event_id=str(uuid4()),
        recommendation_id=recommendation_id,
        from_status=from_status,  # type: ignore[arg-type]
        to_status=to_status,  # type: ignore[arg-type]
        actor=actor,
        reason=reason,
        occurred_at=datetime.now(UTC),
    )

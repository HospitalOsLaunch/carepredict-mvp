"""Agent player API: step uploads fenced by the lease, replay and frames by rights."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.agent_replay import forbidden_text, purge_due
from services.admissions_smr.api.routes_replay import MAX_FRAME_BYTES
from services.admissions_smr.clock import FrozenClock
from services.admissions_smr.main import create_app
from services.admissions_smr.models import AgentTaskStep, AuditEntry
from services.admissions_smr.tests.conftest import NOW
from services.admissions_smr.tests.test_agent_connections import G, g, set_now
from services.admissions_smr.tests.test_api import Login

__all__ = ["g"]  # the fixture, imported for pytest

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


def claimed(g: G, **conn: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """A started connection (site B by default) and its sync task, claimed by poste-1."""
    created = g.create(url="http://127.0.0.1:8020", **({"site_id": g.sites["g1 B"]} | conn))
    assert g.act(created, "start").status_code == 200
    g.beat()
    tasks = g.claim()
    assert len(tasks) == 1
    return created, tasks[0]


def meta(task: dict[str, Any], seq: int = 1, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "agent_id": "poste-1",
        "lease_token": task["lease_token"],
        "seq": seq,
        "at": NOW.isoformat(),
        "engine": "playbook",
        "kind": "click",
        "label": "Valide la connexion",
        "target": "button[type=submit]",
        "pointer": {"x": 640.5, "y": 300},
        "box": {"x": 600, "y": 290, "w": 81, "h": 21},
        "outcome": "ok",
        "duration_ms": 180,
        "viewport": {"w": 1280, "h": 800},
        "masks": [{"x": 10, "y": 20, "w": 200, "h": 18, "reason": "secret"}],
        "transmitted": None,
    }
    body.update(over)
    return body


def post(
    g: G,
    task: dict[str, Any],
    body: dict[str, Any] | None = None,
    frame: bytes | None = JPEG,
    content_type: str = "image/jpeg",
) -> Any:
    files = {"frame": ("f.jpg", frame, content_type)} if frame is not None else None
    return g.client.post(
        f"/api/agent/tasks/{task['id']}/steps",
        headers=g.agent,
        data={"meta": json.dumps(body or meta(task))},
        files=files,
    )


def replay(g: G, task: dict[str, Any], who: dict[str, str], after: int = 0) -> Any:
    return g.client.get(f"/api/agent/tasks/{task['id']}/replay?after_seq={after}", headers=who)


def test_steps_are_stored_and_replayed_in_order_with_their_frames(g: G) -> None:
    conn, task = claimed(g)
    first = post(g, task)
    assert first.status_code == 201
    read = meta(
        task,
        2,
        kind="read",
        label="Lit le mouvement 1 sur 3",
        pointer=None,
        masks=[],
        transmitted={"count": 1, "fields": ["movement_ref", "uf_code"]},
    )
    assert post(g, task, read, frame=None).status_code == 201
    again = post(g, task)  # a retried upload whose answer was lost: same step
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]

    r = replay(g, task, g.admin)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    body = r.json()
    assert body["live"] is True and body["task"]["connection_name"] == conn["name"]
    assert body["task"]["site_name"] == "g1 B"
    assert body["retention_until"].startswith((NOW + timedelta(days=7)).date().isoformat())
    steps = body["steps"]
    assert [s["seq"] for s in steps] == [1, 2]
    assert steps[0]["has_frame"] and not steps[1]["has_frame"]
    assert steps[0]["pointer"] == {"x": 640.5, "y": 300}
    assert steps[0]["masks"][0]["reason"] == "secret"
    assert steps[1]["transmitted"]["fields"] == ["movement_ref", "uf_code"]

    later = replay(g, task, g.admin, after=1).json()["steps"]
    assert [s["seq"] for s in later] == [2]

    frame = g.client.get(f"/api/agent/steps/{steps[0]['id']}/frame", headers=g.admin)
    assert frame.status_code == 200 and frame.content == JPEG
    assert frame.headers["content-type"] == "image/jpeg"
    assert frame.headers["cache-control"] == "no-store"
    assert frame.headers["x-content-type-options"] == "nosniff"
    no_frame = g.client.get(f"/api/agent/steps/{steps[1]['id']}/frame", headers=g.admin)
    assert no_frame.status_code == 404

    runs = g.client.get(f"/api/agent/connections/{conn['id']}/runs", headers=g.admin).json()
    assert runs[0]["has_replay"] is True and runs[0]["steps_count"] == 2
    cards = g.client.get("/api/agent/connections", headers=g.admin).json()
    assert cards[0]["running_task_id"] == task["id"]


def test_rights_matrix(g: G, login: Login) -> None:
    conn_b, task_b = claimed(g)
    assert post(g, task_b).status_code == 201
    step_id = replay(g, task_b, g.admin).json()["steps"][0]["id"]

    def codes(who: dict[str, str]) -> tuple[int, int]:
        frame = g.client.get(f"/api/agent/steps/{step_id}/frame", headers=who)
        return replay(g, task_b, who).status_code, frame.status_code

    assert codes(g.admin) == (200, 200)
    assert codes(g.coord) == (200, 200)  # coordination of the whole group
    assert codes(g.siteb) == (200, 200)  # coordination of the connection's site
    assert codes(g.direction) == (403, 403)
    assert codes(g.agent) == (403, 403)
    assert codes(login("admin@g2.fr")) == (404, 404)
    runs = g.client.get(f"/api/agent/connections/{conn_b['id']}/runs", headers=g.direction)
    assert runs.json()[0]["has_replay"] is False and runs.json()[0]["steps_count"] == 1


def test_site_scoped_coordinator_watches_its_site_only(g: G) -> None:
    _, task_a = claimed(g, name="A", site_id=g.sites["g1 A"])
    assert replay(g, task_a, g.siteb).status_code == 404
    assert replay(g, task_a, g.coord).status_code == 200


def test_group_wide_connection_is_for_unscoped_viewers(g: G) -> None:
    conn, task = claimed(g, name="Groupe", site_id=None)
    assert post(g, task).status_code == 201
    assert replay(g, task, g.siteb).status_code == 403
    assert replay(g, task, g.coord).status_code == 200
    runs = g.client.get(f"/api/agent/connections/{conn['id']}/runs", headers=g.siteb).json()
    assert runs[0]["has_replay"] is False


def test_lease_fencing(g: G, login: Login) -> None:
    _, task = claimed(g)
    wrong = meta(task, lease_token="0" * 64)
    assert post(g, task, wrong).status_code == 409
    assert post(g, task, meta(task, agent_id="poste-2")).status_code == 409
    other_account = g.client.post(
        f"/api/agent/tasks/{task['id']}/steps",
        headers=login("agent@g2.fr"),
        data={"meta": json.dumps(meta(task))},
    )
    assert other_account.status_code == 404
    assert post(g, task, frame=None, body=meta(task)).status_code == 201

    done = {"agent_id": "poste-1", "lease_token": task["lease_token"], "status": "done"}
    r = g.client.post(f"/api/agent/tasks/{task['id']}/complete", headers=g.agent, json=done)
    assert r.status_code == 200
    assert post(g, task, meta(task, 2)).status_code == 409  # task finished
    assert replay(g, task, g.admin).json()["live"] is False

    _, expired = claimed(g, name="Autre")
    set_now(g, timedelta(minutes=11))
    assert post(g, expired).status_code == 409  # lease expired


@pytest.mark.parametrize(
    ("frame", "content_type", "code"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, "image/jpeg", 415),
        (JPEG, "image/png", 415),
        (b"\xff\xd8\xff" + b"\x00" * MAX_FRAME_BYTES, "image/jpeg", 413),
    ],
)
def test_frame_type_and_size(g: G, frame: bytes, content_type: str, code: int) -> None:
    _, task = claimed(g)
    assert post(g, task, frame=frame, content_type=content_type).status_code == code


def test_oversized_body_is_refused_before_it_is_read(g: G) -> None:
    _, task = claimed(g)
    r = post(g, task, frame=JPEG + b"\x00" * (2 * MAX_FRAME_BYTES))
    assert r.status_code == 413


@pytest.mark.parametrize(
    "over",
    [
        {"label": "Lit le dossier de 1 85 07 75 123 456 78"},
        {"label": "Lit le dossier 1850775123456"},
        {"label": "Patient né le 12/03/1941"},
        {"target": "td[data-naissance='1941-03-12']"},
        {"kind": "screenshot"},
        {"outcome": "maybe"},
        {"engine": "gpt"},
        {"label": "x" * 301},
        {"masks": [{"x": 1, "y": 1, "w": 1, "h": 1, "reason": "nom"}]},
        {"transmitted": {"count": 1, "fields": ["nom du patient"]}},
        {"pointer": {"x": float("1e9"), "y": 1}},
        {"duration_ms": -1},
        {"at": "2026-10-25T08:30:00"},
        {"extra": "x"},
    ],
)
def test_meta_is_strict_and_refuses_identifiers(g: G, over: dict[str, Any]) -> None:
    _, task = claimed(g)
    r = post(g, task, meta(task, **over), frame=None)
    assert r.status_code == 422
    for value in (over.get("label"), over.get("target")):  # a refused value is never echoed
        if value and len(value) < 100:
            assert value not in r.text


def test_forbidden_text_patterns() -> None:
    for text in ("2 85 07 2A 123 456", "né le 1/2/1950", "1950-02-01", "12345678901234"):
        assert forbidden_text(text), text
    for text in ("Lit 12 mouvements", "Ouvre le dossier DOS-2026-0412", "UF 2101, lit 2116A"):
        assert not forbidden_text(text), text


def fresh_tokens(g: G, login: Login) -> None:
    """After moving the clock past the token lifetime."""
    g.admin, g.agent = login("admin@g1.fr"), login("agent@g1.fr")


def test_audit_once_per_user_task_and_hour(g: G, db: Session, login: Login) -> None:
    _, task = claimed(g)
    assert post(g, task).status_code == 201
    for _ in range(3):
        assert replay(g, task, g.admin).status_code == 200
    replay(g, task, g.coord)
    set_now(g, timedelta(minutes=61))
    fresh_tokens(g, login)
    replay(g, task, g.admin)
    views = db.scalars(select(AuditEntry).where(AuditEntry.action == "agent.replay.view")).all()
    assert len(views) == 3 and {v.entity_id for v in views} == {str(task["id"])}


def test_purge_after_retention_at_heartbeat_hourly(g: G, db: Session, login: Login) -> None:
    _, task = claimed(g)
    assert post(g, task).status_code == 201
    g.client.app.state.replay_purged_at.clear()  # type: ignore[attr-defined]
    set_now(g, timedelta(days=7, minutes=-30))
    fresh_tokens(g, login)
    g.beat()
    assert db.scalar(select(AgentTaskStep.id)) is not None
    set_now(g, timedelta(days=7, minutes=10))
    fresh_tokens(g, login)
    g.beat()  # less than an hour after the previous purge: skipped
    db.expire_all()
    assert db.scalar(select(AgentTaskStep.id)) is not None
    set_now(g, timedelta(days=7, hours=2))
    fresh_tokens(g, login)
    g.beat()
    db.expire_all()
    assert db.scalar(select(AgentTaskStep.id)) is None
    assert replay(g, task, g.admin).json()["steps"] == []


def test_purge_at_start_up(g: G, db: Session) -> None:
    _, task = claimed(g)
    assert post(g, task).status_code == 201
    settings = g.client.app.state.settings  # type: ignore[attr-defined]
    create_app(settings, FrozenClock(NOW + timedelta(days=6)))
    assert db.scalar(select(AgentTaskStep.id)) is not None
    create_app(settings, FrozenClock(NOW + timedelta(days=7, seconds=1)))
    db.expire_all()
    assert db.scalar(select(AgentTaskStep.id)) is None


def test_purge_due_is_hourly_per_group() -> None:
    done: dict[int, Any] = {}
    assert purge_due(done, 1, NOW) and not purge_due(done, 1, NOW + timedelta(minutes=59))
    assert purge_due(done, 2, NOW) and purge_due(done, 1, NOW + timedelta(minutes=61))

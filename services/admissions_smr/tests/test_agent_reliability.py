"""Queue ownership, decision fencing, site isolation and bounded retries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from threading import Barrier
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.models import AgentAttempt, AgentTask, BaselineSnapshot, Stay
from services.admissions_smr.tests.conftest import TODAY
from services.admissions_smr.tests.test_api import Login, MakeGroup, new_request


@dataclass
class Queue:
    client: TestClient
    coord: dict[str, str]
    agent: dict[str, str]
    admin: dict[str, str]
    sites: list[dict[str, Any]]
    request: dict[str, Any]

    def claim(self, worker: str = "worker") -> list[dict[str, Any]]:
        response = self.client.post(
            "/api/agent/tasks/claim",
            headers=self.agent,
            json={"protocol_version": 2, "agent_id": worker},
        )
        assert response.status_code == 200, response.text
        result: list[dict[str, Any]] = response.json()
        return result

    def worker_post(self, task: dict[str, Any], action: str, **body: Any) -> Any:
        return self.client.post(
            f"/api/agent/tasks/{task['id']}/{action}",
            headers=self.agent,
            json={"agent_id": "worker", "lease_token": task["lease_token"], **body},
        )


@pytest.fixture
def queue(app_client: TestClient, make_group: MakeGroup, login: Login) -> Queue:
    make_group("g1")
    coord, agent, admin = (login(f"{role}@g1.fr") for role in ("coord", "agent", "admin"))
    beat = app_client.post(
        "/api/agent/heartbeat", headers=agent, json={"agent_id": "worker", "version": "test"}
    )
    assert beat.status_code == 200
    sites = app_client.get("/api/sites", headers=coord).json()
    req = app_client.post(
        "/api/requests", headers=coord, json=new_request(site_id=sites[0]["id"])
    ).json()
    agreed = app_client.post(
        f"/api/requests/{req['id']}/accord",
        headers=coord,
        json={"site_id": sites[0]["id"], "proposed_date": str(TODAY + timedelta(days=2))},
    )
    assert agreed.status_code == 200, agreed.text
    return Queue(app_client, coord, agent, admin, sites, agreed.json())


@pytest.mark.parametrize("change", ["lose", "reorient", "confirm"])
@pytest.mark.parametrize("already_claimed", [False, True])
def test_changed_decision_revokes_old_reply(
    queue: Queue, change: str, already_claimed: bool
) -> None:
    old = queue.claim()[0] if already_claimed else None
    body = {
        "lose": {"reason": "annulation_adresseur"},
        "reorient": {"site_id": queue.sites[1]["id"]},
        "confirm": {"proposed_date": str(TODAY + timedelta(days=5))},
    }[change]
    response = queue.client.post(
        f"/api/requests/{queue.request['id']}/{change}", headers=queue.coord, json=body
    )
    assert response.status_code == 200, response.text
    if old:
        assert queue.worker_post(old, "begin-write").status_code == 409
        assert queue.worker_post(old, "complete", status="done").status_code == 409
    claimed = queue.claim()
    if change == "confirm":
        assert len(claimed) == 1
        assert claimed[0]["payload"]["proposed_date"] == str(TODAY + timedelta(days=5))
    else:
        assert claimed == []


def test_tasks_do_not_leak_across_sites_or_tenants(
    queue: Queue, login: Login, make_group: MakeGroup
) -> None:
    task_id = queue.request["portal_reply"]["task_id"]
    make_group("g2")
    for limited in (login("siteb@g1.fr"), login("coord@g2.fr")):
        assert queue.client.get("/api/agent/tasks", headers=limited).json() == []
        assert queue.client.get("/api/agent/status", headers=limited).json()["recent"] == []
        for action in ("manual", "retry"):
            assert (
                queue.client.post(
                    f"/api/agent/tasks/{task_id}/{action}", headers=limited
                ).status_code
                == 404
            )
    assert queue.client.post("/api/agent/sync", headers=login("siteb@g1.fr")).status_code == 403


def test_simultaneous_workers_get_exclusive_ownership(queue: Queue) -> None:
    barrier = Barrier(6)

    def claim(index: int) -> list[dict[str, Any]]:
        barrier.wait(timeout=10)
        return queue.claim(f"worker-{index}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks = [task for batch in pool.map(claim, range(6)) for task in batch]
    assert [t["id"] for t in tasks] == [queue.request["portal_reply"]["task_id"]]
    assert len(tasks[0]["lease_token"]) == 64
    for endpoint in ("/api/agent/tasks", "/api/agent/status"):
        assert "lease_token" not in queue.client.get(endpoint, headers=queue.admin).text


def test_lease_fences_workers_and_pause_blocks_actions(queue: Queue, login: Login) -> None:
    task = queue.claim()[0]
    for body, headers in (
        ({"agent_id": "imposter", "lease_token": task["lease_token"]}, queue.agent),
        ({"agent_id": "worker", "lease_token": "0" * 64}, queue.agent),
        ({"agent_id": "worker", "lease_token": task["lease_token"]}, login("admin@g1.fr")),
    ):
        assert (
            queue.client.post(
                f"/api/agent/tasks/{task['id']}/renew", headers=headers, json=body
            ).status_code
            == 409
        )
    assert queue.worker_post(task, "renew").status_code == 200
    assert queue.client.post("/api/agent/pause", headers=queue.admin).status_code == 200
    assert queue.worker_post(task, "renew").status_code == 409
    assert queue.worker_post(task, "begin-write").status_code == 409
    assert queue.claim() == []
    assert queue.client.post("/api/agent/resume", headers=queue.admin).status_code == 200
    assert queue.worker_post(task, "renew").status_code == 200


def test_write_started_blocks_decision_changes_until_reconciled(queue: Queue) -> None:
    task = queue.claim()[0]
    assert queue.worker_post(task, "begin-write").status_code == 200
    response = queue.client.post(
        f"/api/requests/{queue.request['id']}/lose",
        headers=queue.coord,
        json={"reason": "annulation_adresseur"},
    )
    assert response.status_code == 409
    result = queue.worker_post(task, "complete", status="failed", error="lost response")
    assert result.json()["status"] == "needs_human"
    assert queue.claim() == []
    assert (
        queue.client.post(f"/api/agent/tasks/{task['id']}/retry", headers=queue.coord).status_code
        == 200
    )
    reclaimed = queue.claim()[0]
    assert reclaimed["reconcile_only"] is True
    assert queue.worker_post(reclaimed, "begin-write").status_code == 409


def test_expired_read_lease_reclaims_but_write_requires_human(queue: Queue, db: Session) -> None:
    task = queue.claim()[0]
    stored = db.get(AgentTask, task["id"])
    assert stored is not None and stored.lease_until is not None
    stored.lease_until -= timedelta(minutes=11)
    db.commit()
    next_task = queue.claim()[0]
    assert next_task["lease_token"] != task["lease_token"]
    assert queue.worker_post(task, "renew").status_code == 409
    assert queue.worker_post(next_task, "begin-write").status_code == 200
    db.refresh(stored)
    assert stored.lease_until is not None
    stored.lease_until -= timedelta(minutes=11)
    db.commit()
    assert queue.claim() == []
    db.refresh(stored)
    assert stored.status == "needs_human"


def test_attempt_and_completion_reports_are_idempotent(queue: Queue, db: Session) -> None:
    task = queue.claim()[0]
    for _ in range(2):
        result = queue.worker_post(
            task,
            "attempts",
            engine="closed_best",
            outcome="failure",
            cost_usd=0.37,
            report_key="one-attempt",
        )
        assert result.status_code == 200
        assert result.json()["cost_usd"] == 0.37
    assert len(list(db.scalars(select(AgentAttempt)))) == 1
    for _ in range(2):
        assert queue.worker_post(task, "complete", status="failed").status_code == 200
    assert queue.claim() == []  # exponential backoff, no busy loop
    stored = db.get(AgentTask, task["id"])
    assert stored is not None and stored.available_at is not None
    stored.available_at -= timedelta(minutes=1)
    db.commit()
    next_task = queue.claim()[0]
    assert queue.worker_post(task, "complete", status="failed").status_code == 409
    assert next_task["cost_usd"] == 0.37
    assert queue.worker_post(next_task, "complete", status="done").status_code == 409
    for _ in range(2):
        assert (
            queue.worker_post(
                next_task, "complete", status="done", result={"verification": {"status": "accord"}}
            ).status_code
            == 200
        )


def test_daily_budget_is_reserved_between_workers_and_retries(queue: Queue) -> None:
    policy = queue.client.get("/api/agent/status", headers=queue.admin).json()["policy"]
    policy["daily_budget_usd"] = 0.5
    policy["engines"]["closed_best"].update(enabled=True, identifiable_data_allowed=True)
    policy["routes"]["sync_inbox"].append("closed_best")
    assert (
        queue.client.put("/api/agent/policy", headers=queue.admin, json=policy).status_code == 200
    )
    queue.client.post("/api/agent/sync", headers=queue.agent)
    reply, sync = queue.claim()[0], queue.claim()[0]
    assert reply["kind"] == "reply_portal"  # responses before polling the inbox
    assert queue.worker_post(reply, "authorize", engine="closed_best").json()["budget_usd"] == 0.5
    assert queue.worker_post(sync, "authorize", engine="closed_best").status_code == 409
    queue.worker_post(
        reply, "attempts", engine="closed_best", outcome="failure", cost_usd=0.2, report_key="a"
    )
    assert queue.worker_post(sync, "authorize", engine="closed_best").json()["budget_usd"] == 0.3
    assert queue.worker_post(reply, "authorize", engine="closed_best").status_code == 409


def test_frozen_reference_survives_historical_edits_and_retains_versions(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    h = login("admin@g1.fr")
    start, end = TODAY - timedelta(days=300), TODAY - timedelta(days=273)
    assert (
        app_client.put(
            "/api/settings/baseline", headers=h, json={"start": str(start), "end": str(end)}
        ).status_code
        == 200
    )
    frozen = app_client.post("/api/settings/baseline/freeze", headers=h).json()["baseline"]
    before = app_client.get("/api/metrics/pilot", headers=h).json()
    stay = db.scalar(select(Stay).where(Stay.admission_date == start).limit(1))
    assert stay is not None
    assert (
        app_client.patch(
            f"/api/stays/{stay.id}", headers=h, json={"discharge_date": str(end)}
        ).status_code
        == 200
    )
    after = app_client.get("/api/metrics/pilot", headers=h).json()
    assert before["baseline_occupancy"] == after["baseline_occupancy"]
    assert before["baseline"] == after["baseline"]
    assert len(frozen["digest"]) == 64
    assert (
        app_client.post(
            "/api/settings/baseline/unfreeze", headers=h, json={"reason": "Correction documentée"}
        ).status_code
        == 200
    )
    refrozen = app_client.post("/api/settings/baseline/freeze", headers=h).json()["baseline"]
    assert frozen["snapshot_id"] != refrozen["snapshot_id"]
    assert frozen["digest"] != refrozen["digest"]
    assert len(list(db.scalars(select(BaselineSnapshot)))) == 2


def test_legacy_agent_is_rejected_before_claiming(queue: Queue) -> None:
    result = queue.client.post(
        "/api/agent/tasks/claim", headers=queue.agent, json={"agent_id": "old-worker"}
    )
    assert result.status_code == 422
    assert len(queue.claim()) == 1

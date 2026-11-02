"""Connections set up in HospitalOS drive a worker that has no local configuration beyond
the API address, its account and its name (real Chromium, real API)."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from services.admissions_agent.api_client import HospitalOSClient
from services.admissions_agent.config import AgentSettings
from services.admissions_agent.runner import Agent
from services.admissions_agent.tests.conftest import PASSWORD, db, login
from services.admissions_smr.models import AgentTask, Movement, Site, User
from services.admissions_smr.security import hash_password

PORTAL_SECRET = "demo-portail"


def bare_agent(api: TestClient, agent_id: str = "poste-1") -> Agent:
    """Only what the spec leaves on the machine: API address, account, worker name."""
    settings = AgentSettings(
        api_url="http://testserver",
        api_email="agent@test.fr",
        api_password=PASSWORD,
        agent_id=agent_id,
    )
    return Agent(settings, HospitalOSClient(api, "agent@test.fr", PASSWORD))


def create(api: TestClient, **body: Any) -> dict[str, Any]:
    r = api.post("/api/agent/connections", headers=login(api, "admin@test.fr"), json=body)
    assert r.status_code == 201, r.text
    created: dict[str, Any] = r.json()
    return created


def portal_connection(api: TestClient, url: str, **kw: Any) -> dict[str, Any]:
    return create(
        api,
        **{
            "name": "Portail",
            "kind": "portail_orientation",
            "url": url,
            "username": "demo",
            "secret": PORTAL_SECRET,
            "playbook": "demo_portal",
            "tasks": ["sync_inbox", "reply_portal"],
            "interval_minutes": 10,
            **kw,
        },
    )


def act(api: TestClient, conn: dict[str, Any], action: str, who: str = "admin@test.fr") -> Any:
    return api.post(f"/api/agent/connections/{conn['id']}/{action}", headers=login(api, who))


def requests_from_portal(api: TestClient) -> dict[str, dict[str, Any]]:
    rows = api.get("/api/requests?scope=toutes", headers=login(api, "coord@test.fr")).json()
    return {r["external_ref"]: r for r in rows if r["source"] == "portail"}


def test_started_connection_runs_on_a_worker_without_local_configuration(
    api: TestClient,
    portal: httpx.Client,
    portal_url: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = bare_agent(api)
    conn = portal_connection(api, portal_url)
    assert agent.cycle() == 0  # stopped: the worker registers and waits
    workers = api.get("/api/agent/workers", headers=login(api, "admin@test.fr")).json()
    assert workers[0]["agent_id"] == "poste-1"
    assert {p["name"] for p in workers[0]["playbooks"]} == {"demo_portal", "demo_bedsoft"}
    asked: list[str] = []
    monkeypatch.setattr(agent.api, "request_sync", lambda kind="": asked.append(kind))

    act(api, conn, "start")
    with caplog.at_level(logging.DEBUG):
        handled = agent.cycle()

    assert handled == 1 and not agent.legacy and asked == []  # HospitalOS decided the sync
    assert set(requests_from_portal(api)) == {"DOS-2026-0412", "DOS-2026-0413", "DOS-2026-0414"}
    card = api.get("/api/agent/connections", headers=login(api, "admin@test.fr")).json()[0]
    assert card["last_outcome"] == "done" and card["next_run_at"] is not None
    assert PORTAL_SECRET not in caplog.text
    assert agent.cycle() == 0  # next run in 10 minutes: nothing to do now


def test_pause_blocks_claims_and_resume_delivers_the_waiting_reply(
    api: TestClient, portal: httpx.Client, portal_url: str
) -> None:
    agent = bare_agent(api)
    conn = portal_connection(api, portal_url)
    act(api, conn, "start")
    agent.cycle()
    coord = login(api, "coord@test.fr")
    request = requests_from_portal(api)["DOS-2026-0412"]
    site_id = api.get("/api/sites", headers=coord).json()[0]["id"]
    proposed = (date.today() + timedelta(days=3)).isoformat()
    api.post(
        f"/api/requests/{request['id']}/accord",
        json={"site_id": site_id, "proposed_date": proposed},
        headers=coord,
    ).raise_for_status()

    assert act(api, conn, "pause").json()["status"] == "en_pause"
    assert agent.cycle() == 0  # paused: the reply waits, visible
    runs = api.get(f"/api/agent/connections/{conn['id']}/runs", headers=coord).json()
    assert [r["status"] for r in runs if r["kind"] == "reply_portal"] == ["pending"]
    assert portal.get("/_test/state").json()["DOS-2026-0412"]["status"] == "En attente"

    act(api, conn, "resume", "coord@test.fr")
    assert agent.cycle() >= 1

    state = portal.get("/_test/state").json()["DOS-2026-0412"]
    assert state["status"] == "Accord donné" and state["proposed"] == proposed


def test_one_worker_runs_a_portal_and_a_bed_software(
    api: TestClient, portal: httpx.Client, portal_url: str, bedsoft: httpx.Client, mco: None
) -> None:
    portal_conn = portal_connection(api, portal_url)
    beds_conn = create(
        api,
        name="Gestion des lits",
        kind="gestion_lits",
        url=str(bedsoft.base_url),
        username="cadre",
        secret="demo-lits",
        playbook="demo_bedsoft",
        tasks=["sync_movements"],
        source_system="demo_bedsoft",
    )
    for conn in (portal_conn, beds_conn):
        act(api, conn, "start")

    handled = bare_agent(api).cycle()

    assert handled == 2
    assert len(requests_from_portal(api)) == 3
    session = db(api)
    assert session.query(Movement).count() > 0
    tasks = session.scalars(select(AgentTask)).all()
    assert {(t.kind, t.connection_id, t.status) for t in tasks} == {
        ("sync_inbox", portal_conn["id"], "done"),
        ("sync_movements", beds_conn["id"], "done"),
    }
    session.close()


def test_site_coordinator_starts_its_site_connection_only(
    api: TestClient, portal: httpx.Client, portal_url: str
) -> None:
    session = db(api)
    site = session.scalars(select(Site)).one()
    other = Site(group_id=site.group_id, name="SMR Autre", created_at=datetime.now(UTC))
    session.add(other)
    session.flush()
    session.add(
        User(
            group_id=site.group_id,
            email="site@test.fr",
            full_name="Cadre du site",
            role="coordination",
            site_id=site.id,
            password_hash=hash_password(PASSWORD, 1000),
            created_at=datetime.now(UTC),
        )
    )
    session.commit()
    other_id = other.id
    session.close()
    mine = portal_connection(api, portal_url, name="Mon site", site_id=site.id)
    theirs = portal_connection(api, portal_url, name="Autre site", site_id=other_id)

    assert act(api, theirs, "start", "site@test.fr").status_code == 404
    assert act(api, mine, "start", "site@test.fr").status_code == 200
    bare_agent(api).cycle()

    runs = {
        c["name"]: c["last_outcome"]
        for c in api.get("/api/agent/connections", headers=login(api, "admin@test.fr")).json()
    }
    assert runs == {"Mon site": "done", "Autre site": None}


def test_legacy_mode_until_a_connection_exists_for_the_worker(
    api: TestClient, portal: httpx.Client, make_agent: Any, portal_url: str
) -> None:
    agent = make_agent()  # AGENT_PORTAL_URL and its companions set

    assert agent.cycle() == 1 and agent.legacy  # it asked for its own sync, as before
    assert len(requests_from_portal(api)) == 3

    conn = portal_connection(api, portal_url)
    agent.last_sync = 0.0
    assert agent.cycle() == 0 and not agent.legacy  # HospitalOS now decides
    act(api, conn, "start")
    assert agent.cycle() == 1

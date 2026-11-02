"""Connections piloted from the interface: rights, validation, secrets, schedule, claims."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from services.admissions_smr.models import AgentConnection, AgentTask, AuditEntry, User
from services.admissions_smr.tests.conftest import NOW, TODAY
from services.admissions_smr.tests.test_api import Login, MakeGroup, new_request

SECRET = "S3cret-Portail-XYZ-42"
CATALOGUE = [
    {
        "name": "demo_portal",
        "label": "Portail",
        "kind": "portail_orientation",
        "tasks": ["sync_inbox", "reply_portal"],
    },
    {"name": "demo_bedsoft", "label": "Lits", "kind": "gestion_lits", "tasks": ["sync_movements"]},
]


@dataclass
class G:
    client: TestClient
    admin: dict[str, str]
    coord: dict[str, str]
    siteb: dict[str, str]
    direction: dict[str, str]
    agent: dict[str, str]
    sites: dict[str, int]

    def create(self, **kw: Any) -> dict[str, Any]:
        r = self.client.post("/api/agent/connections", headers=self.admin, json=portal(**kw))
        assert r.status_code == 201, r.text
        body: dict[str, Any] = r.json()
        return body

    def act(self, conn: dict[str, Any], action: str, who: dict[str, str] | None = None) -> Any:
        return self.client.post(
            f"/api/agent/connections/{conn['id']}/{action}", headers=who or self.admin
        )

    def beat(self, agent_id: str = "poste-1", playbooks: Any = None) -> dict[str, Any]:
        r = self.client.post(
            "/api/agent/heartbeat",
            headers=self.agent,
            json={
                "agent_id": agent_id,
                "version": "test",
                "playbooks": CATALOGUE if playbooks is None else playbooks,
            },
        )
        assert r.status_code == 200, r.text
        body: dict[str, Any] = r.json()
        return body

    def claim(self, agent_id: str = "poste-1", legacy: bool = False) -> list[dict[str, Any]]:
        r = self.client.post(
            "/api/agent/tasks/claim",
            headers=self.agent,
            json={"protocol_version": 2, "agent_id": agent_id, "legacy": legacy, "limit": 5},
        )
        assert r.status_code == 200, r.text
        result: list[dict[str, Any]] = r.json()
        return result

    def tasks(self, conn: dict[str, Any]) -> list[dict[str, Any]]:
        r = self.client.get(f"/api/agent/connections/{conn['id']}/runs", headers=self.admin)
        assert r.status_code == 200, r.text
        result: list[dict[str, Any]] = r.json()
        return result


def portal(**kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Portail d'orientation",
        "kind": "portail_orientation",
        "url": "https://portail.example.fr",
        "username": "coord-smr",
        "secret": SECRET,
        "playbook": "demo_portal",
        "tasks": ["sync_inbox", "reply_portal"],
        "interval_minutes": 15,
    }
    body.update(kw)
    return body


@pytest.fixture
def g(app_client: TestClient, make_group: MakeGroup, login: Login) -> G:
    make_group("g1")
    make_group("g2")
    admin = login("admin@g1.fr")
    sites = {s["name"]: s["id"] for s in app_client.get("/api/sites", headers=admin).json()}
    return G(
        app_client,
        admin,
        login("coord@g1.fr"),
        login("siteb@g1.fr"),
        login("dir@g1.fr"),
        login("agent@g1.fr"),
        sites,
    )


def set_now(g: G, delta: timedelta) -> None:
    g.client.app.state.clock.at = NOW + delta  # type: ignore[attr-defined]


# --- rights ---------------------------------------------------------------------------


def test_only_the_admin_creates_and_the_connection_starts_stopped(g: G) -> None:
    for who in (g.coord, g.direction, g.agent):
        r = g.client.post("/api/agent/connections", headers=who, json=portal())
        assert r.status_code == 403

    conn = g.create()

    assert conn["status"] == "arretee" and conn["secret_set"] is True
    assert conn["allowed_hosts"] == ["portail.example.fr"]
    assert conn["can_edit"] is True and conn["can_control"] is True
    assert conn["days"] == [1, 2, 3, 4, 5, 6, 7] and conn["next_run_at"] is None


def test_site_scoped_coordinator_pilots_only_its_site_and_direction_reads(
    g: G, login: Login
) -> None:
    site_a = g.create(name="A", site_id=g.sites["g1 A"])
    site_b = g.create(name="B", site_id=g.sites["g1 B"])
    group_wide = g.create(name="Groupe")

    names = {c["name"]: c for c in g.client.get("/api/agent/connections", headers=g.siteb).json()}
    assert set(names) == {"B", "Groupe"}
    assert names["B"]["can_control"] and not names["Groupe"]["can_control"]
    assert not names["B"]["can_edit"]
    assert g.act(site_b, "start", g.siteb).status_code == 200
    assert g.act(site_a, "start", g.siteb).status_code == 404
    assert g.act(group_wide, "start", g.siteb).status_code == 403
    assert g.act(group_wide, "start", g.coord).status_code == 200  # not limited to a site
    patch = g.client.patch(
        f"/api/agent/connections/{site_b['id']}", headers=g.siteb, json={"name": "x"}
    )
    assert patch.status_code == 403

    listed = g.client.get("/api/agent/connections", headers=g.direction).json()
    assert len(listed) == 3 and not any(c["can_control"] for c in listed)
    assert g.act(site_a, "pause", g.direction).status_code == 403
    assert g.client.get("/api/agent/workers", headers=g.direction).status_code == 200

    other = login("admin@g2.fr")
    assert g.client.get("/api/agent/connections", headers=other).json() == []
    for path in ("runs",):
        r = g.client.get(f"/api/agent/connections/{site_a['id']}/{path}", headers=other)
        assert r.status_code == 404
    assert g.act(site_a, "start", other).status_code == 404
    r = g.client.patch(f"/api/agent/connections/{site_a['id']}", headers=other, json={"name": "x"})
    assert r.status_code == 404
    assert (
        g.client.delete(f"/api/agent/connections/{site_a['id']}", headers=other).status_code == 404
    )


# --- validation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"url": "http://portail.example.fr"}, "https"),
        ({"url": "ftp://portail"}, "https"),
        ({"tasks": ["sync_movements"]}, "Tâches"),
        ({"playbook": "inconnu"}, "catalogue"),
        ({"playbook": "demo_bedsoft"}, "ne correspond pas"),
        ({"source_system": "GAM"}, "gestion des lits"),
        ({"active_from": "18:00", "active_to": "08:00"}, "plage horaire"),
        ({"allowed_hosts": ["exemple .fr"]}, "Hôte"),
        ({"agent_id": "poste-fantome"}, "Poste inconnu"),
        ({"site_id": 999999}, "Site inconnu"),
    ],
)
def test_invalid_connections_are_refused_in_french(
    g: G, change: dict[str, Any], message: str
) -> None:
    r = g.client.post("/api/agent/connections", headers=g.admin, json=portal(**change))

    assert r.status_code == 422 and message in r.text, r.text
    assert SECRET not in r.text


def test_internal_http_hosts_extra_hosts_and_the_reported_catalogue(g: G) -> None:
    conn = g.create(url="http://portal:8020", allowed_hosts=["cdn.portal.fr", "PORTAL"])
    assert conn["allowed_hosts"] == ["portal", "cdn.portal.fr"]
    assert g.create(url="http://127.0.0.1:8020")["allowed_hosts"] == ["127.0.0.1"]

    g.beat(playbooks=[CATALOGUE[1]])  # this group's workers only have the bed script now
    r = g.client.post("/api/agent/connections", headers=g.admin, json=portal())
    assert r.status_code == 422 and "catalogue" in r.text
    beds = g.create(
        name="Lits",
        kind="gestion_lits",
        playbook="demo_bedsoft",
        tasks=["sync_movements"],
        source_system="demo_bedsoft",
        agent_id="poste-1",
    )
    assert beds["agent_id"] == "poste-1" and beds["source_system"] == "demo_bedsoft"


def test_patch_keeps_kind_and_replaces_or_clears_the_secret(g: G, db: Session) -> None:
    conn = g.create(active_from="08:00", active_to="18:30", days=[1, 2, 3, 4, 5])
    assert (conn["active_from"], conn["active_to"]) == ("08:00", "18:30")
    url = f"/api/agent/connections/{conn['id']}"

    kind = g.client.patch(url, headers=g.admin, json={"kind": "gestion_lits"})
    assert kind.status_code == 422
    both = g.client.patch(url, headers=g.admin, json={"secret": "x", "clear_secret": True})
    assert both.status_code == 422
    first = db.get(AgentConnection, conn["id"])
    assert first is not None
    before = first.secret_ciphertext
    r = g.client.patch(
        url,
        headers=g.admin,
        json={"secret": "nouveau-secret", "days": None, "active_from": None, "name": "Renommé"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["days"] == [1, 2, 3, 4, 5, 6, 7] and r.json()["active_from"] is None
    db.expire_all()
    row = db.get(AgentConnection, conn["id"])
    assert row is not None and row.secret_ciphertext != before and row.name == "Renommé"
    cleared = g.client.patch(url, headers=g.admin, json={"clear_secret": True}).json()
    assert cleared["secret_set"] is False and cleared["secret_updated_at"] is None


def test_bed_software_source_is_added_to_restricted_ingestion_accounts(g: G, db: Session) -> None:
    agent = db.scalars(select(User).where(User.email == "agent@g1.fr")).one()
    agent.allowed_sources = json.dumps(["GAM/CH"])
    db.commit()

    g.create(
        name="Lits",
        kind="gestion_lits",
        playbook="demo_bedsoft",
        tasks=["sync_movements"],
        source_system="demo_bedsoft",
        url="https://lits.example.fr",
    )

    db.expire_all()
    assert json.loads(agent.allowed_sources or "") == ["GAM/CH", "demo_bedsoft"]
    other = db.scalars(select(User).where(User.email == "agent@g2.fr")).one()
    assert other.allowed_sources is None  # another group, and "any source" stays any


# --- secrets ----------------------------------------------------------------------------


def test_secret_never_leaves_except_in_the_claim_of_its_task(g: G, db: Session) -> None:
    dumps: list[str] = []
    conn = g.create(url="http://127.0.0.1:8020")
    dumps.append(json.dumps(conn))
    url = f"/api/agent/connections/{conn['id']}"
    for r in (
        g.client.patch(url, headers=g.admin, json={"secret": SECRET, "name": "x"}),
        g.client.patch(url, headers=g.admin, json={"secret": SECRET, "url": "http://x.fr"}),
        g.client.patch(url, headers=g.admin, json={"secret": SECRET * 40}),
        g.client.post("/api/agent/connections", headers=g.admin, json=portal(tasks=[])),
        g.act(conn, "start"),
        g.client.get("/api/agent/connections", headers=g.admin),
        g.client.get("/api/agent/workers", headers=g.admin),
        g.client.get("/api/agent/status", headers=g.admin),
        g.client.get("/api/agent/tasks", headers=g.admin),
        g.client.get(f"{url}/runs", headers=g.admin),
        g.act(conn, "sync"),
    ):
        dumps.append(r.text)
    beat = g.beat()
    dumps.append(json.dumps(beat))
    claimed = g.claim()
    assert claimed and claimed[0]["connection"]["secret"] == SECRET
    assert claimed[0]["connection"]["username"] == "coord-smr"
    assert claimed[0]["connection"]["allowed_hosts"] == ["127.0.0.1"]
    dumps.append(g.client.get(f"{url}/runs", headers=g.admin).text)

    audit = " ".join(
        f"{a.action} {a.entity} {a.detail}" for a in db.scalars(select(AuditEntry)).all()
    )
    assert "secret modifié" in audit and "secret défini" in audit
    metadata = MetaData()
    metadata.reflect(bind=db.get_bind())
    stored = " ".join(
        str(v) for t in metadata.sorted_tables for row in db.execute(t.select()) for v in row
    )
    leaks = [d for d in [*dumps, audit, stored] if SECRET in d]
    assert leaks == []
    assert "v1:" in stored


def test_admin_account_cannot_claim_a_connection_task(g: G) -> None:
    conn = g.create()
    g.act(conn, "start")
    g.beat()
    r = g.client.post(
        "/api/agent/tasks/claim",
        headers=g.admin,
        json={"protocol_version": 2, "agent_id": "poste-1", "legacy": False},
    )
    assert r.status_code == 200 and r.json() == []


# --- schedule ---------------------------------------------------------------------------


def test_heartbeat_creates_due_syncs_once_per_interval(g: G) -> None:
    conn = g.create()
    assert g.beat()["connections"][0]["status"] == "arretee"
    assert g.tasks(conn) == []  # stopped: nothing created

    g.act(conn, "start")
    beat = g.beat()
    runs = g.tasks(conn)
    assert [t["kind"] for t in runs] == ["sync_inbox"] and runs[0]["connection_id"] == conn["id"]
    nxt = beat["connections"][0]["next_run_at"]
    assert nxt.startswith((NOW + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M"))
    assert "secret" not in json.dumps(beat["connections"]) and SECRET not in json.dumps(beat)

    set_now(g, timedelta(minutes=20))  # due again, but the first is still pending
    g.beat()
    assert len(g.tasks(conn)) == 1

    task = g.claim()[0]
    done = g.client.post(
        f"/api/agent/tasks/{task['id']}/complete",
        headers=g.agent,
        json={"agent_id": "poste-1", "lease_token": task["lease_token"], "status": "done"},
    )
    assert done.status_code == 200, done.text
    set_now(g, timedelta(minutes=40))
    g.beat()
    assert len(g.tasks(conn)) == 2
    card = g.client.get("/api/agent/connections", headers=g.admin).json()[0]
    assert card["last_outcome"] == "done" and card["pending_tasks"] == 1


def test_active_window_and_days_in_local_time(g: G) -> None:
    # NOW is Sunday 25 October 2026, 09:30 in Paris (winter time since 03:00).
    morning = g.create(active_from="10:00", active_to="18:00")
    weekdays = g.create(name="Semaine", days=[1, 2, 3, 4, 5])
    for conn in (morning, weekdays):
        g.act(conn, "start")

    g.beat()

    cards = {c["name"]: c for c in g.client.get("/api/agent/connections", headers=g.admin).json()}
    assert cards["Portail d'orientation"]["next_run_at"].startswith("2026-10-25T09:00")
    assert cards["Semaine"]["next_run_at"].startswith("2026-10-25T23:00")  # Monday 00:00
    assert g.tasks(morning) == [] and g.tasks(weekdays) == []
    set_now(g, timedelta(minutes=31))  # 10:01 in Paris
    g.beat()
    assert len(g.tasks(morning)) == 1 and g.tasks(weekdays) == []


def test_a_worker_without_the_script_or_another_assignee_gets_nothing(g: G) -> None:
    g.beat("poste-1")
    conn = g.create(agent_id="poste-1")
    g.act(conn, "start")

    assert g.beat("poste-2")["connections"] == []
    assert g.tasks(conn) == []  # poste-2 cannot run it: nothing scheduled for it
    assert g.beat("poste-3", playbooks=[CATALOGUE[1]])["connections"] == []
    g.beat("poste-1")
    assert g.claim("poste-2") == [] and g.claim("poste-3") == []
    assert len(g.claim("poste-1")) == 1


# --- pause and resume -------------------------------------------------------------------


def test_pause_stops_creation_and_claims_resume_restarts(g: G) -> None:
    conn = g.create()
    assert g.act(conn, "pause").status_code == 409  # stopped: start it first
    g.act(conn, "start")
    g.beat()
    assert g.act(conn, "pause").json()["status"] == "en_pause"

    assert g.claim() == []  # the pending task stays visible, not claimable
    assert [t["status"] for t in g.tasks(conn)] == ["pending"]
    assert g.act(conn, "sync").status_code == 409
    set_now(g, timedelta(minutes=50))  # tokens last 60 minutes
    g.beat()
    assert len(g.tasks(conn)) == 1  # nothing created while paused

    assert g.act(conn, "resume").json()["status"] == "active"
    g.beat()
    assert len(g.tasks(conn)) == 1  # no duplicate of the pending sync
    assert len(g.claim()) == 1


def test_pausing_interrupts_a_running_task_at_its_next_checkpoint(g: G) -> None:
    conn = g.create()
    g.act(conn, "start")
    g.beat()
    task = g.claim()[0]
    lease = {"agent_id": "poste-1", "lease_token": task["lease_token"]}
    assert (
        g.client.post(
            f"/api/agent/tasks/{task['id']}/renew", headers=g.agent, json=lease
        ).status_code
        == 200
    )

    g.act(conn, "pause")

    renew = g.client.post(f"/api/agent/tasks/{task['id']}/renew", headers=g.agent, json=lease)
    assert renew.status_code == 409 and "pause" in renew.text


def test_group_pause_stops_everything(g: G) -> None:
    conn = g.create()
    g.act(conn, "start")
    g.client.post("/api/agent/pause", headers=g.admin)

    g.beat()
    assert g.tasks(conn) == []
    assert g.act(conn, "sync").status_code == 409
    g.client.post("/api/agent/resume", headers=g.admin)
    g.beat()
    assert len(g.claim()) == 1


def test_sync_now_and_archive(g: G, db: Session) -> None:
    conn = g.create()
    assert g.act(conn, "sync").status_code == 409  # stopped
    g.act(conn, "start")
    first = g.act(conn, "sync")
    assert first.status_code == 201 and first.json()["kind"] == "sync_inbox"
    assert g.act(conn, "sync").json()["id"] == first.json()["id"]  # no duplicate
    assert g.act(conn, "sync", g.direction).status_code == 403

    r = g.client.delete(f"/api/agent/connections/{conn['id']}", headers=g.admin)

    assert r.status_code == 204
    assert g.client.get("/api/agent/connections", headers=g.admin).json() == []
    assert g.act(conn, "start").status_code == 404
    task = db.get(AgentTask, first.json()["id"])
    row = db.get(AgentConnection, conn["id"])
    assert task is not None and task.status == "cancelled"
    assert row is not None and row.secret_ciphertext is None and row.archived_at is not None


def test_legacy_group_sync_goes_to_connections_once_they_exist(g: G) -> None:
    legacy = g.client.post("/api/agent/sync", headers=g.coord)
    assert legacy.status_code == 201 and legacy.json()["connection_id"] is None
    assert g.claim(legacy=False) == []  # a connection-mode worker leaves legacy tasks
    assert len(g.claim("legacy", legacy=True)) == 1

    conn = g.create()
    assert g.client.post("/api/agent/sync", headers=g.coord).status_code == 409
    g.act(conn, "start")
    routed = g.client.post("/api/agent/sync", headers=g.coord).json()
    assert routed["connection_id"] == conn["id"]


# --- replies ----------------------------------------------------------------------------


def test_reply_goes_to_the_portal_connection_of_the_request_site(g: G) -> None:
    site_a, site_b = g.sites["g1 A"], g.sites["g1 B"]
    portal_a = g.create(name="A", site_id=site_a)
    portal_b = g.create(name="B", site_id=site_b)
    g.act(portal_b, "start")
    req = g.client.post("/api/requests", headers=g.coord, json=new_request(site_id=site_b)).json()

    agreed = g.client.post(
        f"/api/requests/{req['id']}/accord",
        headers=g.coord,
        json={"site_id": site_b, "proposed_date": str(TODAY + timedelta(days=2))},
    )

    assert agreed.status_code == 200, agreed.text
    replies = [t for t in g.tasks(portal_b) if t["kind"] == "reply_portal"]
    assert len(replies) == 1 and g.tasks(portal_a) == []
    g.beat()
    claimed = [t for t in g.claim() if t["kind"] == "reply_portal"]
    assert claimed and claimed[0]["connection"]["id"] == portal_b["id"]

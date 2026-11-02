"""End to end: the agent reads the movements of the day on a fictional bed-management
software (real Chromium) and HospitalOS applies them, without ever storing a name."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from services.admissions_agent.api_client import HospitalOSClient
from services.admissions_agent.config import AgentSettings
from services.admissions_agent.demo_bedsoft import app as bedsoft_module
from services.admissions_agent.runner import Agent
from services.admissions_agent.tests.conftest import PASSWORD, db, login
from services.admissions_smr.domain.pseudonym import pseudonym
from services.admissions_smr.models import Bed, EdVisit, Movement, Site, Stay

PLAYBOOK = Path(bedsoft_module.__file__).parent.parent / "playbooks" / "demo_bedsoft.yaml"
ON_SCREEN_ONLY = ["Rosalie", "Exemplaire", "Gaston", "Odile", "Hector", "1941", "12/03"]
CLEAR_IDS = ["4000101", "7000101", "4000102", "7000102"]


def bedsoft_agent(api: TestClient, url: str) -> Agent:
    settings = AgentSettings(
        api_url="http://testserver",
        api_email="agent@test.fr",
        api_password=PASSWORD,
        agent_id="agent-lits",
        portal_url=url,
        portal_username="cadre",
        portal_password="demo-lits",
        playbook_path=str(PLAYBOOK),
        allowed_hosts=("127.0.0.1",),
    )
    return Agent(settings, HospitalOSClient(api, "agent@test.fr", PASSWORD))


def stay(session: Session, group_id: int, venue: str) -> Stay | None:
    ref = pseudonym("dev-only-pseudonym-secret-change-me", group_id, "nda", "demo_bedsoft", venue)
    return session.scalar(select(Stay).where(Stay.encounter_ref == ref))


def test_agent_reads_movements_and_hospitalos_applies_them(
    api: TestClient, bedsoft: httpx.Client, mco: None
) -> None:
    # Arrange
    agent = bedsoft_agent(api, str(bedsoft.base_url))
    assert agent.kinds == ["sync_movements"]  # this machine only claims what it can do

    # Act
    handled = agent.cycle()

    # Assert: the task is done, every movement applied, the cancelled entry nets to nothing.
    assert handled == 1
    tasks = api.get("/api/agent/tasks", headers=login(api, "coord@test.fr")).json()
    task = next(t for t in tasks if t["kind"] == "sync_movements")
    assert task["status"] == "done" and task["engine_used"] == "playbook", task
    assert task["result"]["movements"] == {"applied": 8} and task["result"]["rejected"] == []
    session = db(api)
    group_id = session.scalars(select(Site)).one().group_id
    hospitalised = stay(session, group_id, "7000101")
    assert hospitalised is not None and hospitalised.admission_mode == "urgences"
    assert hospitalised.source == "agent" and hospitalised.patient_age is not None
    visit = session.scalars(select(EdVisit)).one()
    assert visit.outcome == "hospitalise" and visit.source == "agent"
    transferred = stay(session, group_id, "7000102")
    assert transferred is not None and transferred.mention == "medecine_polyvalente"
    bed_2116a = session.scalars(select(Bed).where(Bed.label == "2116A")).one()
    assert transferred.bed_id == bed_2116a.id
    discharged = stay(session, group_id, "7000103")
    assert discharged is not None and discharged.discharge_date is not None
    assert stay(session, group_id, "7000104") is None
    session.close()

    # Nothing read on screen beyond the playbook's fields reaches the database.
    session = db(api)
    metadata = MetaData()
    metadata.reflect(bind=session.get_bind())
    dump = " ".join(
        str(v) for t in metadata.sorted_tables for row in session.execute(t.select()) for v in row
    )
    session.close()
    assert [v for v in ON_SCREEN_ONLY + CLEAR_IDS if v in dump] == []


def test_resync_is_idempotent_and_a_later_cancellation_is_applied(
    api: TestClient, bedsoft: httpx.Client, mco: None
) -> None:
    agent = bedsoft_agent(api, str(bedsoft.base_url))
    agent.cycle()
    session = db(api)
    journal_size = session.query(Movement).count()
    session.close()

    agent.last_sync = 0.0
    agent.cycle()  # same screen: everything already known
    session = db(api)
    assert session.query(Movement).count() == journal_size
    session.close()

    bedsoft.post("/_test/cancel/BS-0004")  # the transfer was a mistake
    agent.last_sync = 0.0
    agent.cycle()

    session = db(api)
    group_id = session.scalars(select(Site)).one().group_id
    back = stay(session, group_id, "7000102")
    assert back is not None and back.mention == "cardiologie"
    assert session.scalars(select(Bed).where(Bed.label == "2116A")).one().status == "libre"
    session.close()


def test_a_policy_saved_before_sync_movements_still_routes_it_to_the_script() -> None:
    from services.admissions_smr.agent_policy import default_policy, parse_policy

    old = default_policy()
    del old.routes["sync_movements"]

    policy = parse_policy(old.model_dump_json())

    assert policy.routes["sync_movements"] == ["playbook"]


def test_t18_the_fictional_software_reads_an_injectable_clock() -> None:
    frozen = datetime(2026, 3, 29, 12, 0, tzinfo=bedsoft_module.PARIS)
    previous = bedsoft_module.store.clock
    bedsoft_module.store.clock = lambda: frozen
    try:
        with TestClient(bedsoft_module.app) as client:
            client.post("/connexion", data={"utilisateur": "cadre", "mdp": "demo-lits"})
            listing = client.get("/mouvements").text
            detail = client.get("/mouvements/BS-0003").text
            added = client.post("/_test/arrive").json()["id"]
            client.post("/_test/reset")
    finally:
        bedsoft_module.store.clock = previous
    assert "29/03/2026" in listing and "29/03/2026 08:05" in detail
    assert added == "BS-0101"

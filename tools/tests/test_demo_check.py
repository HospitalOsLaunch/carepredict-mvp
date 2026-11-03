"""The HL7 message posted by the demo check is a valid A04 with fresh identifiers."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from services.admissions_agent.demo_portal import app as portal_module
from services.admissions_agent.tests.conftest import as_httpx
from services.admissions_smr.clock import Clock
from services.admissions_smr.config import Settings
from services.admissions_smr.domain.hl7_pam import parse
from services.admissions_smr.main import create_app
from services.admissions_smr.seed import seed_demo
from tools.demo_check import PASSWORD, check_pause_resume, fresh_hl7, login

PARIS = ZoneInfo("Europe/Paris")


def test_fresh_hl7_is_a_valid_a04_dated_now_with_new_identifiers() -> None:
    now = datetime(2026, 11, 2, 9, 15, tzinfo=PARIS)

    first, second = parse(fresh_hl7(now), PARIS), parse(fresh_hl7(now), PARIS)

    assert (first.event, first.action, first.uf_code) == ("A04", "INSERT", "1001")
    assert first.occurred_at == now
    assert first.control_id != "MSG-A04" and first.control_id != second.control_id
    assert first.movement_ref != second.movement_ref
    assert first.encounter_id != second.encounter_id and first.encounter_id != "900002"


def test_pause_then_resume_of_the_demo_portal_connection(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        secret_key="t" * 40,
        token_ttl_minutes=60,
        password_iterations=1000,
        timezone="Europe/Paris",
        cors_origins=(),
    )
    app = create_app(settings, Clock("Europe/Paris"))
    with app.state.session_factory() as session:
        seed_demo(session, date.today(), PASSWORD, 1000)
    with (
        TestClient(app, base_url="http://testserver/api") as api,
        TestClient(portal_module.app) as portal,
    ):
        portal.post("/_test/reset")
        admin = login(as_httpx(api), "admin@demo.hospitalos.fr")
        assert admin is not None

        new_ref = check_pause_resume(as_httpx(api), as_httpx(portal), 0)

        conn = api.get("/agent/connections", headers=admin).json()[0]
        assert conn["status"] == "active" and new_ref.startswith("DOS-")

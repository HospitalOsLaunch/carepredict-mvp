"""The HIS simulator speaks valid IHE PAM France for the MCO demo hospital."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from services.admissions_smr.clock import FrozenClock
from services.admissions_smr.config import Settings
from services.admissions_smr.domain.hl7_pam import parse
from services.admissions_smr.main import create_app
from services.admissions_smr.models import Bed, BedPool, EdVisit, Group, Site, Stay, User
from services.admissions_smr.security import hash_password
from services.admissions_smr.seed_mco import MCO_SITE, UNITS
from services.admissions_smr.vocab import UNIT_KINDS
from tools.his_simulator import Simulator, main, seed_beds

START = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def test_dry_run_prints_parseable_messages(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dry-run", "--count", "30", "--start", START.isoformat()]) == 0

    messages = [m for m in capsys.readouterr().out.split("\n\n") if m.strip()]
    assert len(messages) == 30
    events = {parse(m.encode(), ZoneInfo("Europe/Paris")).event for m in messages}
    assert {"A04", "A03"} <= events


def test_beds_match_the_demo_hospital() -> None:
    beds = seed_beds()
    assert len(beds) == sum(u.installed for u in UNITS[MCO_SITE])
    assert {"2101", "3201", "4001"} <= {b.uf for b in beds}
    assert len({b.label for b in beds}) == len(beds)


def test_a_long_stream_is_fully_accepted_and_keeps_beds_consistent(tmp_path: Path) -> None:
    # Arrange: the MCO site of the demo, units and beds from the seed constants.
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'sim.db'}",
        secret_key="t" * 40,
        token_ttl_minutes=60,
        password_iterations=1000,
        timezone="Europe/Paris",
        cors_origins=(),
    )
    app = create_app(settings, FrozenClock(START))
    with TestClient(app) as client:
        session = app.state.session_factory()
        group = Group(name="Simulation", created_at=START)
        session.add(group)
        session.flush()
        site = Site(group_id=group.id, name=MCO_SITE, created_at=START)
        session.add(site)
        session.flush()
        pools = {}
        for spec in UNITS[MCO_SITE]:
            unit_type, discipline = UNIT_KINDS[spec.code]
            pools[spec.uf_code] = BedPool(
                site_id=site.id,
                mention=spec.code,
                beds_installed=spec.installed,
                beds_open=spec.installed,
                unit_type=unit_type,
                discipline=discipline,
                uf_code=spec.uf_code,
                updated_at=START,
            )
            session.add(pools[spec.uf_code])
        session.flush()
        for b in seed_beds():
            session.add(
                Bed(
                    group_id=group.id,
                    site_id=site.id,
                    pool_id=pools[b.uf].id,
                    room=b.room,
                    label=b.label,
                    status="libre",
                    updated_at=START,
                )
            )
        session.add(
            User(
                group_id=group.id,
                email="agent@sim.test",
                full_name="agent",
                role="ingestion",
                password_hash=hash_password("x" * 12, 1000),
                created_at=START,
            )
        )
        session.commit()
        token = client.post(
            "/api/auth/login", json={"email": "agent@sim.test", "password": "x" * 12}
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}", "Content-Type": "x-application/hl7-v2+er7"}

        # Act
        stream = Simulator(seed=3, start=START).messages()
        answers = [
            client.post("/api/ingest/hl7", content=next(stream).encode(), headers=auth)
            for _ in range(300)
        ]

        # Assert
        rejected = [a.text for a in answers if a.status_code != 200 or "MSA|AA|" not in a.text]
        assert rejected == []
        assert session.query(Stay).count() > 10 and session.query(EdVisit).count() > 10
        assert "Lit" not in " ".join(a.text for a in answers)  # no bed conflict warning
        for bed in session.scalars(select(Bed).where(Bed.stay_id.is_not(None))):
            stay = session.get(Stay, bed.stay_id)
            assert stay is not None and stay.bed_id == bed.id and stay.discharged_at is None
        for stay in session.scalars(select(Stay).where(Stay.bed_id.is_not(None))):
            assert session.get(Bed, stay.bed_id).stay_id == stay.id
        session.close()

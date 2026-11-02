from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from services.admissions_smr.db import make_engine, make_session_factory
from services.admissions_smr.migrate import upgrade
from services.admissions_smr.models import BedPool, EdVisit, Group, Site, Stay
from services.admissions_smr.seed_mco import seed_demo_mco
from services.admissions_smr.tests.conftest import test_database_url as database_url

# The demo is generated for a fixed "now", so its history is the same on every run.
DEMO_NOW = datetime(2026, 10, 25, 8, 30, tzinfo=UTC)


PARIS = ZoneInfo("Europe/Paris")
# The tiny hospital is forecast on AS_OF, at NOW (05:00 UTC, 07:00 in Paris).
AS_OF = date(2026, 3, 31)
NOW = datetime(2026, 3, 31, 5, 0, tzinfo=UTC)


def tiny_hospital(session: Session) -> int:
    """Thirty days of a 10-bed unit and its emergency department: too short for CV."""
    group = Group(name="Mini", created_at=NOW)
    session.add(group)
    session.flush()
    site = Site(group_id=group.id, name="CH Mini", ght="GHT Mini", departement="80", created_at=NOW)
    session.add(site)
    session.flush()
    pool = BedPool(
        site_id=site.id,
        mention="medecine_polyvalente",
        beds_installed=10,
        beds_open=10,
        unit_type="medecine",
        discipline="medecine",
        updated_at=NOW,
    )
    session.add(pool)
    session.flush()
    for i in range(30):
        day = AS_OF - timedelta(days=30 - i)
        noon = datetime.combine(day, datetime.min.time(), tzinfo=PARIS) + timedelta(hours=12)
        session.add(
            EdVisit(
                group_id=group.id,
                site_id=site.id,
                encounter_ref=f"E{i}",
                patient_ref=f"P{i}",
                arrived_at=noon.astimezone(UTC),
                left_at=(noon + timedelta(hours=3)).astimezone(UTC),
                outcome="sortie",
                source="hl7",
            )
        )
        discharged = day + timedelta(days=4)
        session.add(
            Stay(
                group_id=group.id,
                site_id=site.id,
                mention="medecine_polyvalente",
                patient_ref=f"S{i}",
                admission_date=day,
                admitted_at=noon.astimezone(UTC),
                discharge_date=discharged if discharged < AS_OF else None,
                admission_mode="urgences",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    session.commit()
    return group.id


@pytest.fixture
def tiny(tmp_path: Path) -> Iterator[tuple[str, int]]:
    url = database_url(tmp_path)
    engine = make_engine(url)
    upgrade(engine)
    with make_session_factory(engine)() as session:
        group_id = tiny_hospital(session)
    engine.dispose()
    yield url, group_id


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: takes more than 10 s (deselect with -m 'not slow')")


@pytest.fixture(scope="session")
def demo_engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    """The MCO demo hospital (one year of synthetic history), seeded once per test run.

    Always its own SQLite file, whatever ADM_TEST_DATABASE_URL says: the other tests reset
    the PostgreSQL schema, which would wipe a shared session-wide database under it.
    """
    engine = make_engine(f"sqlite:///{tmp_path_factory.mktemp('demo') / 'demo.db'}")
    upgrade(engine)
    with make_session_factory(engine)() as session:
        seed_demo_mco(session, DEMO_NOW, "mot-de-passe-demo", 1000)
    yield engine
    engine.dispose()

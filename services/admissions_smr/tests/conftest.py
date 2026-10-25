from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.admissions_smr.clock import FrozenClock
from services.admissions_smr.config import Settings
from services.admissions_smr.main import create_app
from services.admissions_smr.models import BedPool, Group, Site, Stay, User
from services.admissions_smr.security import hash_password

NOW = datetime(2026, 10, 25, 8, 30, tzinfo=UTC)
TODAY = date(2026, 10, 25)
PASSWORD = "mot-de-passe-solide"


def test_database_url(tmp_path: Path) -> str:
    """SQLite by default; ADM_TEST_DATABASE_URL runs the same tests on PostgreSQL."""
    url = os.getenv("ADM_TEST_DATABASE_URL")
    if not url:
        return f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    return url


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        environment="test",
        database_url=test_database_url(tmp_path),
        secret_key="t" * 40,
        token_ttl_minutes=60,
        password_iterations=1000,
        timezone="Europe/Paris",
        cors_origins=(),
    )
    app = create_app(settings, FrozenClock(NOW))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def db(app_client: TestClient) -> Iterator[Session]:
    session: Session = app_client.app.state.session_factory()  # type: ignore[attr-defined]
    yield session
    session.close()


@pytest.fixture
def make_group(db: Session) -> Callable[[str], Group]:
    def factory(name: str) -> Group:
        group = Group(name=name, created_at=NOW)
        db.add(group)
        db.flush()
        for site_name, mentions in (
            (f"{name} A", ("geriatrie", "polyvalent")),
            (f"{name} B", ("geriatrie",)),
        ):
            site = Site(group_id=group.id, name=site_name, capabilities="oxygene", created_at=NOW)
            db.add(site)
            db.flush()
            for mention in mentions:
                site.pools.append(
                    BedPool(
                        site_id=site.id,
                        mention=mention,
                        beds_installed=10,
                        beds_open=10,
                        isolation_rooms=1,
                        updated_at=NOW,
                    )
                )
            # History so the LOS model has data: 60 stays of 12 days, plus 8 present today.
            for i in range(60):
                admit = TODAY - timedelta(days=300 - i * 3)
                db.add(
                    Stay(
                        group_id=group.id,
                        site_id=site.id,
                        mention=mentions[0],
                        patient_ref=f"H-{site.id}-{i}",
                        admission_date=admit,
                        discharge_date=admit + timedelta(days=12),
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            for i in range(8):
                db.add(
                    Stay(
                        group_id=group.id,
                        site_id=site.id,
                        mention=mentions[0],
                        patient_ref=f"C-{site.id}-{i}",
                        admission_date=TODAY - timedelta(days=i + 1),
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
        for email, role, site_scoped in (
            (f"admin@{name}.fr", "admin_groupe", False),
            (f"coord@{name}.fr", "coordination", False),
            (f"siteb@{name}.fr", "coordination", True),
            (f"dir@{name}.fr", "direction", False),
            (f"agent@{name}.fr", "ingestion", False),
        ):
            site_b = db.query(Site).filter(Site.name == f"{name} B").one()
            db.add(
                User(
                    group_id=group.id,
                    email=email,
                    full_name=email,
                    role=role,
                    password_hash=hash_password(PASSWORD, 1000),
                    site_id=site_b.id if site_scoped else None,
                    created_at=NOW,
                )
            )
        db.commit()
        return group

    return factory


@pytest.fixture
def login(app_client: TestClient) -> Callable[[str], dict[str, str]]:
    def do(email: str) -> dict[str, str]:
        response = app_client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['token']}"}

    return do

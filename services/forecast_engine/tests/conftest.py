from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine

from services.admissions_smr.db import make_engine, make_session_factory
from services.admissions_smr.migrate import upgrade
from services.admissions_smr.seed_mco import seed_demo_mco

# The demo is generated for a fixed "now", so its history is the same on every run.
DEMO_NOW = datetime(2026, 10, 25, 8, 30, tzinfo=UTC)


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

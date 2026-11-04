"""Several API processes (règle 28): how many, and starting them together on one database."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from services.admissions_smr.migrate import is_current, upgrade
from services.admissions_smr.serve import workers

from .conftest import test_database_url

PG = "postgresql+psycopg://adm@db/adm"


def test_as_many_processes_as_cores_within_the_database_limits() -> None:
    assert workers(PG, {}, cores=1) == 2  # one can die while the other answers
    assert workers(PG, {}, cores=3) == 3
    assert workers(PG, {}, cores=32) == 4  # each process keeps its pool of connections
    assert workers(PG, {"ADM_API_WORKERS": "6"}, cores=2) == 6
    assert workers(PG, {"ADM_API_WORKERS": "0"}, cores=2) == 1


def test_sqlite_keeps_a_single_process() -> None:
    assert workers("sqlite:///./admissions_smr.db", {"ADM_API_WORKERS": "4"}, cores=8) == 1


def _start(url: str) -> None:
    """What each API process does first: bring the schema to the latest migration."""
    engine = create_engine(url)
    try:
        upgrade(engine)
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("ADM_TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="concurrent migrations are serialised by a PostgreSQL lock",
)
def test_four_processes_starting_together_migrate_once(tmp_path: Path) -> None:
    url = test_database_url(tmp_path)  # an empty schema
    spawn = multiprocessing.get_context("spawn")
    processes = [spawn.Process(target=_start, args=(url,)) for _ in range(4)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=120)
    # Without the lock, three of the four died on « duplicate key » while creating tables.
    assert [p.exitcode for p in processes] == [0, 0, 0, 0]
    engine = create_engine(url)
    try:
        assert is_current(engine)
    finally:
        engine.dispose()

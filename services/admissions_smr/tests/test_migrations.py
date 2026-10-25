from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext

from services.admissions_smr.db import Base, make_engine
from services.admissions_smr.migrate import is_current, upgrade


def test_migrations_build_exactly_the_models(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'm.db'}")
    upgrade(engine)
    assert is_current(engine)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == []


def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'm.db'}")
    upgrade(engine)
    upgrade(engine)
    assert is_current(engine)

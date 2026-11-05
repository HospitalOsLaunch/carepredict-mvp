"""Database migrations (Alembic), driven from code so no ini file has to be deployed.

python -m services.admissions_smr.cli migrate            # upgrade to the latest schema
python -m services.admissions_smr.migrate revision "msg" # developers: new migration
"""

from __future__ import annotations

import os
import sys

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

MIGRATIONS = os.path.join(os.path.dirname(__file__), "migrations")
# Several API processes start together (règle 28): on PostgreSQL, one migrates while the
# others wait on this lock, then find the schema current. Any constant, the same everywhere.
MIGRATION_LOCK = 7_261_600_128


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", MIGRATIONS)
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade(engine: Engine) -> None:
    config = alembic_config(str(engine.url.render_as_string(hide_password=False)))
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            # Held until this transaction ends, migration included.
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def is_current(engine: Engine) -> bool:
    script = ScriptDirectory.from_config(alembic_config(str(engine.url)))
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_heads()
    return set(current) == set(script.get_heads())


def main(argv: list[str]) -> int:
    from services.admissions_smr.config import get_settings

    if len(argv) >= 2 and argv[0] == "revision":
        command.revision(
            alembic_config(get_settings().database_url), message=argv[1], autogenerate=True
        )
        return 0
    print('usage: python -m services.admissions_smr.migrate revision "message"', file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

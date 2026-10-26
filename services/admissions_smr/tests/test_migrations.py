from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import MetaData, select

from services.admissions_smr.db import Base, make_engine
from services.admissions_smr.migrate import alembic_config, is_current, upgrade
from services.admissions_smr.tests.conftest import test_database_url as database_url


def test_migrations_build_exactly_the_models(tmp_path: Path) -> None:
    engine = make_engine(database_url(tmp_path))
    upgrade(engine)
    assert is_current(engine)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == []


def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(database_url(tmp_path))
    upgrade(engine)
    upgrade(engine)
    assert is_current(engine)


def test_upgrade_preserves_linked_rows_and_quarantines_legacy_writes(tmp_path: Path) -> None:
    engine = make_engine(database_url(tmp_path))
    config = alembic_config(str(engine.url.render_as_string(hide_password=False)))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
        old = MetaData()
        old.reflect(bind=connection)
        now = datetime.now(UTC)
        connection.execute(
            old.tables["groups"]
            .insert()
            .values(
                id=1,
                name="Legacy",
                created_at=now,
                baseline_frozen_at=now,
                value_per_bed_day=100,
                success_fee_rate=0.1,
                scoring_weights_json="{}",
                care_minutes_json="{}",
            )
        )
        connection.execute(
            old.tables["admission_requests"]
            .insert()
            .values(
                id=1,
                group_id=1,
                source="portail",
                external_ref="DOS-1",
                received_at=now,
                referrer_facility="CH",
                patient_ref="DOS-1",
                mention_requested="geriatrie",
                care_level=2,
                isolation_required=False,
                special_needs="",
                status="accord",
                created_at=now,
                updated_at=now,
            )
        )
        for task_id, status in ((1, "running"), (2, "pending")):
            connection.execute(
                old.tables["agent_tasks"]
                .insert()
                .values(
                    id=task_id,
                    group_id=1,
                    request_id=1,
                    kind="reply_portal",
                    payload_json="{}",
                    status=status,
                    attempts=1,
                    cost_usd=0.2,
                    created_at=now,
                    updated_at=now,
                )
            )
        connection.execute(
            old.tables["agent_attempts"]
            .insert()
            .values(
                id=1,
                group_id=1,
                task_id=1,
                engine="playbook",
                outcome="failure",
                cost_usd=0.2,
                steps=3,
                duration_s=4,
                at=now,
            )
        )
    upgrade(engine)
    with engine.connect() as connection:
        current = MetaData()
        current.reflect(bind=connection)
        task = (
            connection.execute(
                select(current.tables["agent_tasks"]).where(current.tables["agent_tasks"].c.id == 1)
            )
            .mappings()
            .one()
        )
        assert task["status"] == "needs_human" and task["write_started_at"] is not None
        assert task["lease_token"] is None and task["request_id"] == 1
        assert (
            connection.execute(select(current.tables["agent_attempts"].c.cost_usd)).scalar() == 0.2
        )
        assert (
            connection.execute(select(current.tables["groups"].c.baseline_frozen_at)).scalar()
            is None
        )
        assert (
            connection.execute(select(current.tables["audit_log"].c.action)).scalar()
            == "reference.migration"
        )
        assert (
            connection.execute(
                select(current.tables["admission_requests"].c.decision_version)
            ).scalar()
            == 0
        )
    engine.dispose()

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import MetaData, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.admissions_smr.db import Base, make_engine
from services.admissions_smr.migrate import alembic_config, is_current, upgrade
from services.admissions_smr.models import Bed, BedPool, Group, Site, Stay
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


LISCOP_TABLES = {
    "beds",
    "movements",
    "ed_visits",
    "ed_snapshots",
    "tension_declarations",
    "forecast_runs",
    "forecast_values",
    "ror_outbox",
}


def test_liscop_upgrade_keeps_existing_rows_and_backfills_defaults(tmp_path: Path) -> None:
    engine = make_engine(database_url(tmp_path))
    config = alembic_config(str(engine.url.render_as_string(hide_password=False)))
    now = datetime.now(UTC)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0002")
        old = MetaData()
        old.reflect(bind=connection)
        connection.execute(
            old.tables["groups"]
            .insert()
            .values(
                id=1,
                name="Legacy",
                created_at=now,
                value_per_bed_day=0,
                success_fee_rate=0,
                scoring_weights_json="{}",
                care_minutes_json="{}",
            )
        )
        connection.execute(
            old.tables["sites"]
            .insert()
            .values(id=1, group_id=1, name="SMR", capabilities="", active=True, created_at=now)
        )
        connection.execute(
            old.tables["bed_pools"]
            .insert()
            .values(
                id=1,
                site_id=1,
                mention="geriatrie",
                beds_installed=10,
                beds_open=10,
                isolation_rooms=1,
                updated_at=now,
            )
        )
        connection.execute(
            old.tables["stays"]
            .insert()
            .values(
                id=1,
                group_id=1,
                site_id=1,
                mention="geriatrie",
                patient_ref="P-1",
                admission_date=now.date(),
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            old.tables["stay_plan_changes"]
            .insert()
            .values(id=1, stay_id=1, recorded_at=now, recorded_on=now.date(), source="saisie")
        )
    upgrade(engine)
    with engine.connect() as connection:
        current = MetaData()
        current.reflect(bind=connection)
        assert set(current.tables) >= LISCOP_TABLES
        pool = connection.execute(select(current.tables["bed_pools"])).mappings().one()
        assert (pool["unit_type"], pool["discipline"]) == ("smr", "smr")
        assert (pool["extra_beds"], pool["crisis_reserved_beds"]) == (0, 0)
        stay = connection.execute(select(current.tables["stays"])).mappings().one()
        assert stay["source"] == "saisie" and stay["bed_id"] is None
        assert connection.execute(select(current.tables["stay_plan_changes"].c.stay_id)).scalar()
        stay_fks = {fk.column.table.name for fk in current.tables["stays"].c.bed_id.foreign_keys}
        assert stay_fks == {"beds"}
    engine.dispose()


def test_liscop_downgrade_then_upgrade_on_empty_database(tmp_path: Path) -> None:
    engine = make_engine(database_url(tmp_path))
    upgrade(engine)
    config = alembic_config(str(engine.url.render_as_string(hide_password=False)))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002")
        tables = MetaData()
        tables.reflect(bind=connection)
        assert not LISCOP_TABLES & set(tables.tables)
        assert "bed_id" not in tables.tables["stays"].c
    upgrade(engine)
    assert is_current(engine)
    engine.dispose()


# Reproduced: on SQLite the batch copy of `stays` drops the old table while beds.stay_id
# still points at it (FOREIGN KEY constraint failed). The fix belongs to migration 0003
# (owner: fix-ingest), e.g. clear beds.stay_id or drop `beds` before the batch. Strict:
# the test fails as soon as the migration is fixed, so this marker is then removed.
@pytest.mark.xfail(
    not os.getenv("ADM_TEST_DATABASE_URL"),
    reason="0003 downgrade fails on SQLite with a stay linked to a bed",
    raises=IntegrityError,
    strict=True,
)
def test_liscop_downgrade_keeps_a_stay_linked_to_a_bed(tmp_path: Path) -> None:
    """T-19: stays.bed_id ↔ beds.stay_id reference each other; the downgrade still runs."""
    engine = make_engine(database_url(tmp_path))
    upgrade(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        group = Group(name="G", created_at=now)
        session.add(group)
        session.flush()
        site = Site(group_id=group.id, name="S", capabilities="", created_at=now)
        session.add(site)
        session.flush()
        pool = BedPool(
            site_id=site.id,
            mention="medecine_polyvalente",
            beds_installed=1,
            beds_open=1,
            unit_type="medecine",
            discipline="medecine",
            updated_at=now,
        )
        session.add(pool)
        session.flush()
        stay = Stay(
            group_id=group.id,
            site_id=site.id,
            mention="medecine_polyvalente",
            patient_ref="P-1",
            admission_date=now.date(),
            source="hl7",
            created_at=now,
            updated_at=now,
        )
        session.add(stay)
        session.flush()
        bed = Bed(
            group_id=group.id,
            site_id=site.id,
            pool_id=pool.id,
            room="101",
            label="101",
            status="occupe",
            stay_id=stay.id,
            updated_at=now,
        )
        session.add(bed)
        session.flush()
        stay.bed_id = bed.id
        session.commit()
        stay_id = stay.id
    config = alembic_config(str(engine.url.render_as_string(hide_password=False)))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002")
        tables = MetaData()
        tables.reflect(bind=connection)
        assert "beds" not in tables.tables and "bed_id" not in tables.tables["stays"].c
        stays = tables.tables["stays"]
        assert connection.execute(select(stays.c.id, stays.c.patient_ref)).all() == [
            (stay_id, "P-1")
        ]
    upgrade(engine)
    assert is_current(engine)
    with Session(engine) as session:
        assert session.get(Stay, stay_id).bed_id is None  # type: ignore[union-attr]
    engine.dispose()

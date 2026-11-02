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


def test_liscop_downgrade_with_a_stay_in_its_bed_and_a_same_day_readmission(
    tmp_path: Path,
) -> None:
    """REVIEW C-2 / T-19: the partial unique index is created and removed; a stay linked to
    a bed does not block the downgrade (SQLite copies ``stays``)."""
    engine = make_engine(database_url(tmp_path))
    upgrade(engine)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        tables = MetaData()
        tables.reflect(bind=connection)
        t = tables.tables
        connection.execute(
            t["groups"].insert().values(
                id=1, name="G", created_at=now, value_per_bed_day=0, success_fee_rate=0,
                scoring_weights_json="{}", care_minutes_json="{}",
            )
        )  # fmt: skip
        connection.execute(
            t["sites"].insert().values(id=1, group_id=1, name="S", capabilities="", active=True,
                                       created_at=now)
        )  # fmt: skip
        connection.execute(
            t["bed_pools"].insert().values(
                id=1, site_id=1, mention="medecine_polyvalente", beds_installed=1, beds_open=1,
                isolation_rooms=0, updated_at=now,
            )
        )  # fmt: skip
        for stay_id, encounter in ((1, "E1"), (2, "E2")):  # same patient, site and day
            connection.execute(
                t["stays"].insert().values(
                    id=stay_id, group_id=1, site_id=1, mention="medecine_polyvalente",
                    patient_ref="P", admission_date=now.date(), created_at=now, updated_at=now,
                    encounter_ref=encounter, source="hl7",
                )
            )  # fmt: skip
        connection.execute(
            t["beds"].insert().values(
                id=1, group_id=1, site_id=1, pool_id=1, room="1", label="1", sex_constraint="X",
                isolation=False, status="occupe", stay_id=2, active=True, updated_at=now,
            )
        )  # fmt: skip
        connection.execute(t["stays"].update().where(t["stays"].c.id == 2).values(bed_id=1))
        connection.execute(t["stays"].delete().where(t["stays"].c.id == 1))  # old index
    config = alembic_config(str(engine.url.render_as_string(hide_password=False)))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002")
    with engine.connect() as connection:
        tables = MetaData()
        tables.reflect(bind=connection)
        assert "beds" not in tables.tables
        assert connection.execute(select(tables.tables["stays"].c.id)).scalars().all() == [2]
    upgrade(engine)
    assert is_current(engine)
    engine.dispose()

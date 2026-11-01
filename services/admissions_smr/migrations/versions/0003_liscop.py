"""LISCOP : unités MCO, lits, mouvements HL7, urgences, tension, prévisions, file ROR.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def _id() -> sa.Column[int]:
    return sa.Column("id", sa.Integer(), primary_key=True)


def _fk(name: str, target: str, nullable: bool = False) -> sa.Column[int]:
    return sa.Column(name, sa.Integer(), sa.ForeignKey(f"{target}.id"), nullable=nullable)


def upgrade() -> None:
    column: sa.Column[Any]
    for column in (
        sa.Column("ght", sa.String(120)),
        sa.Column("departement", sa.String(3)),
        sa.Column("territory", sa.String(120)),
    ):
        op.add_column("sites", column)
    for column in (
        sa.Column("unit_type", sa.String(30), nullable=False, server_default="smr"),
        sa.Column("discipline", sa.String(30), nullable=False, server_default="smr"),
        sa.Column("label", sa.String(120)),
        sa.Column("uf_code", sa.String(20)),
        sa.Column("ror_unit_id", sa.String(64)),
        sa.Column("extra_beds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("crisis_reserved_beds", sa.Integer(), nullable=False, server_default="0"),
    ):
        op.add_column("bed_pools", column)

    op.create_table(
        "beds",
        _id(),
        _fk("group_id", "groups"),
        _fk("site_id", "sites"),
        _fk("pool_id", "bed_pools"),
        sa.Column("room", sa.String(40), nullable=False),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("sex_constraint", sa.String(1), nullable=False),
        sa.Column("isolation", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("status_reason", sa.String(200)),
        _fk("stay_id", "stays", nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
        sa.UniqueConstraint("site_id", "label"),
    )
    for name in ("group_id", "site_id", "pool_id"):
        op.create_index(f"ix_beds_{name}", "beds", [name])

    # Plain ADD COLUMN ... REFERENCES: SQLite accepts it for a nullable column, so the
    # stays table (and the rows that reference it) is never copied.
    op.add_column(
        "stays",
        sa.Column(
            "bed_id", sa.Integer(), sa.ForeignKey("beds.id", name="fk_stays_bed_id"), nullable=True
        ),
        inline_references=True,
    )
    for column in (
        sa.Column("source", sa.String(20), nullable=False, server_default="saisie"),
        sa.Column("encounter_ref", sa.String(64)),
        sa.Column("patient_sex", sa.String(1)),
        sa.Column("patient_age", sa.Integer()),
        sa.Column("admitted_at", TZ),
        sa.Column("discharged_at", TZ),
        sa.Column("admission_mode", sa.String(20)),
    ):
        op.add_column("stays", column)
    op.create_index(
        "uq_stays_encounter",
        "stays",
        ["group_id", "encounter_ref", "site_id", "mention"],
        unique=True,
    )

    op.create_table(
        "movements",
        _id(),
        _fk("group_id", "groups"),
        sa.Column("source_system", sa.String(60), nullable=False),
        sa.Column("message_control_id", sa.String(60), nullable=False),
        sa.Column("movement_ref", sa.String(60)),
        sa.Column("event", sa.String(7), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("occurred_at", TZ, nullable=False),
        sa.Column("encounter_ref", sa.String(64), nullable=False),
        sa.Column("patient_ref", sa.String(64), nullable=False),
        _fk("site_id", "sites", nullable=True),
        _fk("pool_id", "bed_pools", nullable=True),
        _fk("bed_id", "beds", nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("message_digest", sa.String(64), nullable=False),
        sa.Column("received_at", TZ, nullable=False),
        sa.UniqueConstraint("group_id", "source_system", "message_control_id"),
    )
    op.create_index("ix_movements_group_id", "movements", ["group_id"])

    op.create_table(
        "ed_visits",
        _id(),
        _fk("group_id", "groups"),
        _fk("site_id", "sites"),
        sa.Column("encounter_ref", sa.String(64), nullable=False),
        sa.Column("patient_ref", sa.String(64), nullable=False),
        sa.Column("arrived_at", TZ, nullable=False),
        sa.Column("admit_decision_at", TZ),
        sa.Column("left_at", TZ),
        sa.Column("outcome", sa.String(20)),
        _fk("target_pool_id", "bed_pools", nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.UniqueConstraint("group_id", "encounter_ref"),
    )
    for name in ("group_id", "site_id", "arrived_at"):
        op.create_index(f"ix_ed_visits_{name}", "ed_visits", [name])

    op.create_table(
        "ed_snapshots",
        _id(),
        _fk("group_id", "groups"),
        _fk("site_id", "sites"),
        sa.Column("at", TZ, nullable=False),
        sa.Column("present", sa.Integer(), nullable=False),
        sa.Column("waiting_bed", sa.Integer(), nullable=False),
        sa.Column("boarding", sa.Integer(), nullable=False),
        sa.Column("hosted_elsewhere", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        _fk("declared_by", "users", nullable=True),
        sa.Column("comment", sa.Text()),
    )
    for name in ("group_id", "site_id", "at"):
        op.create_index(f"ix_ed_snapshots_{name}", "ed_snapshots", [name])

    op.create_table(
        "tension_declarations",
        _id(),
        _fk("group_id", "groups"),
        _fk("site_id", "sites", nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("started_at", TZ, nullable=False),
        sa.Column("ended_at", TZ),
        _fk("declared_by", "users"),
        sa.Column("comment", sa.Text()),
    )
    op.create_index("ix_tension_declarations_group_id", "tension_declarations", ["group_id"])

    op.create_table(
        "forecast_runs",
        _id(),
        _fk("group_id", "groups"),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("model_version", sa.String(60), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_forecast_runs_group_id", "forecast_runs", ["group_id"])

    op.create_table(
        "forecast_values",
        _id(),
        _fk("run_id", "forecast_runs"),
        _fk("site_id", "sites", nullable=True),
        _fk("pool_id", "bed_pools", nullable=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("scope_key", sa.String(120), nullable=False),
        sa.Column("target", sa.String(30), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("mean", sa.Float(), nullable=False),
        sa.Column("q10", sa.Float(), nullable=False),
        sa.Column("q50", sa.Float(), nullable=False),
        sa.Column("q90", sa.Float(), nullable=False),
        sa.Column("p_tension", sa.Float()),
        sa.Column("p_critique", sa.Float()),
    )
    op.create_index(
        "ix_forecast_values_run_target_day", "forecast_values", ["run_id", "target", "day"]
    )

    op.create_table(
        "ror_outbox",
        _id(),
        _fk("group_id", "groups"),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
    )
    op.create_index("ix_ror_outbox_group_id", "ror_outbox", ["group_id"])


def downgrade() -> None:
    for table in (
        "ror_outbox",
        "forecast_values",
        "forecast_runs",
        "tension_declarations",
        "ed_snapshots",
        "ed_visits",
        "movements",
    ):
        op.drop_table(table)
    op.drop_index("uq_stays_encounter", table_name="stays")
    for name in (
        "admission_mode",
        "discharged_at",
        "admitted_at",
        "patient_age",
        "patient_sex",
        "encounter_ref",
        "source",
    ):
        op.drop_column("stays", name)
    # SQLite cannot DROP a column used by a foreign key: batch mode copies the table.
    with op.batch_alter_table("stays") as batch:
        batch.drop_column("bed_id")
    op.drop_table("beds")
    for name in (
        "crisis_reserved_beds",
        "extra_beds",
        "ror_unit_id",
        "uf_code",
        "label",
        "discipline",
        "unit_type",
    ):
        op.drop_column("bed_pools", name)
    for name in ("territory", "departement", "ght"):
        op.drop_column("sites", name)

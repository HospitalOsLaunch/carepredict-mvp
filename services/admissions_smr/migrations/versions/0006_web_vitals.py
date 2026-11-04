"""Core Web Vitals of real visits (règle 30 de l'audit de performance), kept 90 days.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "web_vitals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("recorded_on", sa.Date(), nullable=False),
        sa.Column("page", sa.String(40), nullable=False),
        sa.Column("metric", sa.String(8), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("device", sa.String(10), nullable=False),
        sa.Column("connection", sa.String(10), nullable=False),
    )
    op.create_index("ix_web_vitals_group_day", "web_vitals", ["group_id", "recorded_on"])


def downgrade() -> None:
    op.drop_index("ix_web_vitals_group_day", table_name="web_vitals")
    op.drop_table("web_vitals")

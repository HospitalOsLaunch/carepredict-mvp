"""Version decisions, fence agent leases, and preserve immutable baseline inputs.

Stop old agents before upgrading: their protocol cannot acknowledge fenced leases.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "baseline_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start", sa.Date(), nullable=False),
        sa.Column("end", sa.Date(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_baseline_snapshots_group_id", "baseline_snapshots", ["group_id"])
    op.add_column(
        "admission_requests",
        sa.Column("decision_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("agent_attempts", sa.Column("report_key", sa.String(80)))
    op.create_index(
        "uq_agent_attempt_report", "agent_attempts", ["task_id", "report_key"], unique=True
    )
    for column in (
        sa.Column("lease_token", sa.String(64)),
        sa.Column("claimed_user_id", sa.Integer()),
        sa.Column("decision_version", sa.Integer()),
        sa.Column("write_lease_token", sa.String(64)),
        sa.Column("write_started_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("budget_reserved_usd", sa.Float(), nullable=False, server_default="0"),
    ):
        op.add_column("agent_tasks", column)
    op.create_index("ix_agent_tasks_available_at", "agent_tasks", ["available_at"])
    # Never automatically replay a write that an older agent could have submitted.
    op.execute(
        "UPDATE agent_tasks SET status='needs_human', write_started_at=CURRENT_TIMESTAMP, "
        "lease_until=NULL, error='Mise à jour : vérifier le résultat sur le portail' "
        "WHERE kind='reply_portal' AND status='running'"
    )
    # Older freezes did not preserve inputs; do not manufacture historical evidence.
    op.execute(
        "INSERT INTO audit_log (group_id, at, action, entity, detail) "
        "SELECT id, CURRENT_TIMESTAMP, 'reference.migration', 'group', "
        "'Ancien gel sans instantané : référence à vérifier et regeler' "
        "FROM groups WHERE baseline_frozen_at IS NOT NULL"
    )
    op.execute("UPDATE groups SET baseline_frozen_at=NULL WHERE baseline_frozen_at IS NOT NULL")


def downgrade() -> None:
    op.drop_index("ix_agent_tasks_available_at", table_name="agent_tasks")
    for name in (
        "budget_reserved_usd",
        "available_at",
        "write_started_at",
        "write_lease_token",
        "decision_version",
        "claimed_user_id",
        "lease_token",
    ):
        op.drop_column("agent_tasks", name)
    op.drop_index("uq_agent_attempt_report", table_name="agent_attempts")
    op.drop_column("agent_attempts", "report_key")
    op.drop_column("admission_requests", "decision_version")
    op.drop_index("ix_baseline_snapshots_group_id", table_name="baseline_snapshots")
    op.drop_table("baseline_snapshots")

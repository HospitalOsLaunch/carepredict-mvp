"""Agent player: the steps of each task (label, gesture, masked frame), kept 7 days.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "agent_task_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("agent_tasks.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("at", TZ, nullable=False),
        sa.Column("engine", sa.String(60), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("target", sa.String(200)),
        sa.Column("pointer_json", sa.Text()),
        sa.Column("box_json", sa.Text()),
        sa.Column("outcome", sa.String(10), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("viewport_json", sa.Text(), nullable=False),
        sa.Column("masks_json", sa.Text(), nullable=False),
        sa.Column("transmitted_json", sa.Text()),
        sa.Column("frame", sa.LargeBinary()),
        sa.Column("created_at", TZ, nullable=False),
    )
    op.create_index("ix_agent_task_steps_group_id", "agent_task_steps", ["group_id"])
    op.create_index(
        "ix_agent_task_steps_task_seq", "agent_task_steps", ["task_id", "seq"], unique=True
    )
    op.create_index("ix_agent_task_steps_created_at", "agent_task_steps", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_task_steps_created_at", table_name="agent_task_steps")
    op.drop_index("ix_agent_task_steps_task_seq", table_name="agent_task_steps")
    op.drop_index("ix_agent_task_steps_group_id", table_name="agent_task_steps")
    op.drop_table("agent_task_steps")

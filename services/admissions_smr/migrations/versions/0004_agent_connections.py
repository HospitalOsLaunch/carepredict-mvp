"""Computer use piloted from the interface: agent workers, connections, encrypted secrets.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def _fk(name: str, target: str, nullable: bool = False) -> sa.Column[int]:
    return sa.Column(name, sa.Integer(), sa.ForeignKey(f"{target}.id"), nullable=nullable)


@contextmanager
def _sqlite_table_copy() -> Iterator[None]:
    """Batch mode copies ``agent_tasks``, which ``agent_attempts`` references: foreign keys
    are checked once the copy has its name back (same approach as 0003 for ``stays``)."""
    op.execute("PRAGMA defer_foreign_keys = ON")
    op.execute("PRAGMA foreign_keys = OFF")  # no-op inside a transaction
    yield
    op.execute("PRAGMA foreign_keys = ON")
    if op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("0004: foreign key violation after copying the agent_tasks table")


def upgrade() -> None:
    op.create_table(
        "agent_workers",
        sa.Column("id", sa.Integer(), primary_key=True),
        _fk("group_id", "groups"),
        sa.Column("agent_id", sa.String(120), nullable=False),
        _fk("site_id", "sites", nullable=True),
        sa.Column("version", sa.String(40)),
        sa.Column("engines_json", sa.Text(), nullable=False),
        sa.Column("playbooks_json", sa.Text(), nullable=False),
        sa.Column("last_heartbeat_at", TZ),
        sa.Column("created_at", TZ, nullable=False),
        sa.UniqueConstraint("group_id", "agent_id"),
    )
    op.create_index("ix_agent_workers_group_id", "agent_workers", ["group_id"])

    op.create_table(
        "agent_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        _fk("group_id", "groups"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        _fk("site_id", "sites", nullable=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("allowed_hosts_json", sa.Text(), nullable=False),
        sa.Column("username", sa.String(200)),
        sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("secret_updated_at", TZ),
        sa.Column("playbook", sa.String(80), nullable=False),
        sa.Column("tasks_json", sa.Text(), nullable=False),
        sa.Column("source_system", sa.String(60)),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("active_from", sa.Time()),
        sa.Column("active_to", sa.Time()),
        sa.Column("days_json", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.String(120)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("next_run_at", TZ),
        sa.Column("last_run_at", TZ),
        sa.Column("last_outcome", sa.String(20)),
        sa.Column("last_error", sa.Text()),
        sa.Column("archived_at", TZ),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("updated_at", TZ, nullable=False),
        _fk("created_by", "users", nullable=True),
        _fk("updated_by", "users", nullable=True),
    )
    op.create_index("ix_agent_connections_group_id", "agent_connections", ["group_id"])

    # Plain ADD COLUMN ... REFERENCES (nullable): SQLite does not copy agent_tasks.
    op.add_column(
        "agent_tasks",
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("agent_connections.id", name="fk_agent_tasks_connection_id"),
            nullable=True,
        ),
        inline_references=True,
    )
    op.create_index("ix_agent_tasks_connection_id", "agent_tasks", ["connection_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_tasks_connection_id", table_name="agent_tasks")
    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot DROP a column used by a foreign key: batch mode copies the table.
        with _sqlite_table_copy(), op.batch_alter_table("agent_tasks") as b:
            b.drop_column("connection_id")
    else:
        op.drop_constraint("fk_agent_tasks_connection_id", "agent_tasks", type_="foreignkey")
        op.drop_column("agent_tasks", "connection_id")
    op.drop_index("ix_agent_connections_group_id", table_name="agent_connections")
    op.drop_table("agent_connections")
    op.drop_index("ix_agent_workers_group_id", table_name="agent_workers")
    op.drop_table("agent_workers")

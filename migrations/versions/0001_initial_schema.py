"""Initial schema — task, task_run, task_context

Revision ID: 0001
Revises:
Create Date: 2026-05-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column(
            "priority",
            sa.Text,
            sa.CheckConstraint("priority IN ('high','med','low')", name="ck_task_priority"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text,
            sa.CheckConstraint(
                "status IN ('open','in_progress','waiting','done','cancelled')",
                name="ck_task_status",
            ),
            nullable=False,
            server_default="open",
        ),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("owner", sa.Text, nullable=False, server_default="ben"),
        sa.Column("source", sa.Text, nullable=False, server_default="manual"),
        sa.Column("source_ref", sa.Text, nullable=True),
        sa.Column("requires_approval", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("task_status_idx", "task", ["status"])
    op.create_index("task_owner_idx", "task", ["owner"])
    op.create_index("task_due_date_idx", "task", ["due_date"])
    op.create_index("task_source_ref_idx", "task", ["source", "source_ref"])

    op.create_table(
        "task_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dispatcher", sa.Text, nullable=False),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Text,
            sa.CheckConstraint(
                "status IN ('queued','running','awaiting_approval','succeeded','failed','cancelled')",
                name="ck_run_status",
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("result_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("log", sa.Text, nullable=True),
        sa.Column("cost_tokens", sa.Integer, nullable=True),
        sa.Column("cost_usd_cents", sa.Integer, nullable=True),
    )
    op.create_index("task_run_task_idx", "task_run", ["task_id"])
    op.create_index("task_run_started_idx", "task_run", ["started_at"])

    op.create_table(
        "task_context",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("ref", sa.Text, nullable=True),
        sa.Column("snippet", sa.Text, nullable=False),
        sa.Column(
            "fetched_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("stale", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("task_context_task_idx", "task_context", ["task_id", "source"])


def downgrade() -> None:
    op.drop_table("task_context")
    op.drop_table("task_run")
    op.drop_table("task")

"""Add entity_pin and task_entity tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_pin",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_name", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text, nullable=True),
        sa.Column("pin_level", sa.Text, nullable=False, server_default="favourite"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("entity_name", name="uq_entity_pin_name"),
    )
    op.create_index("entity_pin_name_idx", "entity_pin", ["entity_name"])

    op.create_table(
        "task_entity",
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("entity_name", sa.Text, nullable=False, primary_key=True),
        sa.Column("entity_type", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=False, server_default="auto"),
        sa.Column("relevance", sa.Float, nullable=True),
    )
    op.create_index("task_entity_task_idx", "task_entity", ["task_id"])
    op.create_index("task_entity_name_idx", "task_entity", ["entity_name"])


def downgrade() -> None:
    op.drop_table("task_entity")
    op.drop_table("entity_pin")

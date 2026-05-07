"""Add parent_id self-referential FK to task table

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task",
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("task_parent_idx", "task", ["parent_id"])


def downgrade() -> None:
    op.drop_index("task_parent_idx", table_name="task")
    op.drop_column("task", "parent_id")

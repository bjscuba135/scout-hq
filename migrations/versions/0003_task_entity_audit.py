"""Add attached_by and attached_at audit columns to task_entity

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task_entity", sa.Column("attached_by", sa.Text, nullable=True))
    op.add_column(
        "task_entity",
        sa.Column("attached_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_entity", "attached_at")
    op.drop_column("task_entity", "attached_by")

"""Add domain field to task table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task", sa.Column("domain", sa.Text(), nullable=True))
    # Backfill: all existing tasks are Scouting (the app was Scout-only)
    op.execute("UPDATE task SET domain = 'scouting' WHERE domain IS NULL")
    op.create_index("task_domain_idx", "task", ["domain"])


def downgrade() -> None:
    op.drop_index("task_domain_idx", table_name="task")
    op.drop_column("task", "domain")

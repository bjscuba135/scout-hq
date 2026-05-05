from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Text,
    event,
)
from sqlalchemy import TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "task"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(Text, nullable=False)  # high|med|low
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner: Mapped[str] = mapped_column(Text, nullable=False, default="ben")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    runs: Mapped[list[TaskRun]] = relationship(
        "TaskRun", back_populates="task", cascade="all, delete-orphan"
    )
    contexts: Mapped[list[TaskContext]] = relationship(
        "TaskContext", back_populates="task", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("task_status_idx", "status"),
        Index("task_owner_idx", "owner"),
        Index("task_due_date_idx", "due_date"),
        Index("task_source_ref_idx", "source", "source_ref"),
    )


class TaskRun(Base):
    __tablename__ = "task_run"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task.id", ondelete="CASCADE"), nullable=False
    )
    dispatcher: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    log: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    task: Mapped[Task] = relationship("Task", back_populates="runs")

    __table_args__ = (
        Index("task_run_task_idx", "task_id"),
        Index("task_run_started_idx", "started_at"),
    )


class TaskContext(Base):
    __tablename__ = "task_context"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=_utcnow
    )
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    task: Mapped[Task] = relationship("Task", back_populates="contexts")

    __table_args__ = (
        Index("task_context_task_idx", "task_id", "source"),
    )


# ── Stale-context hook ────────────────────────────────────────────────────────
# When any Task field changes, mark all its TaskContext rows as stale.
# Done in the model layer (not a DB trigger) so it's testable.

@event.listens_for(Task, "after_update")
def _mark_contexts_stale(mapper, connection, target: Task):
    if target.contexts:
        connection.execute(
            TaskContext.__table__.update()
            .where(TaskContext.__table__.c.task_id == target.id)
            .values(stale=True)
        )

"""The durable job queue table.

A job represents a unit of work that runs asynchronously after the request that
created it. The queue is implemented in PostgreSQL using `SELECT ... FOR UPDATE
SKIP LOCKED` so that two workers never claim the same row and a worker that dies
mid-job releases its lease when its connection closes.

The job kinds are not an enum here -- they are a free string defined by the code
that submits work (the orchestrator). An enum would either list jobs that do not
exist yet or require a migration every time a new kind is added.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UtcDateTime, UuidPrimaryKeyMixin


class JobStatus(str):
    """Job lifecycle states.

    These are stored as plain strings with a CHECK constraint rather than a
    native enum, so adding a state is an ordinary migration.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"


class Job(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """A unit of work persisted for later execution.

    The `kind` + `payload` pair describes what to do. The orchestrator
    interprets them; the queue only stores and leases them.
    """

    __tablename__ = "jobs"

    kind: Mapped[str] = mapped_column(sa.String(128), nullable=False)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=sa.text("'pending'"),
    )

    # Which worker currently holds the lease. NULL when unclaimed.
    worker_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    # How many times this job has been claimed (attempt 1 = first try).
    attempt: Mapped[int] = mapped_column(
        sa.Integer,
        server_default=sa.text("0"),
        nullable=False,
    )

    # When the current lease expires. A NULL lease means no active claim.
    lease_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # When the job actually started running (first claim transition to RUNNING).
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # When the job reached a terminal state (COMPLETED or FAILED).
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # For failed jobs: why it failed. For completed jobs: NULL.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # For failed jobs: the typed error class name (e.g. "RateLimited",
    # "Blocked", "SchemaChanged", "Transient"). Free text on purpose so new
    # failure modes do not require a migration.
    error_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    __table_args__ = (
        # The primary access pattern: claim the next N pending jobs for a worker.
        # We filter on status + lease_expires_at to find available work.
        Index("ix_jobs_status_lease", "status", "lease_expires_at"),
        # Lookup by worker for diagnostics and lease extension.
        Index("ix_jobs_worker_id", "worker_id"),
        # The job kind is used for routing and filtering.
        Index("ix_jobs_kind", "kind"),
        # Valid status values.
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'dead')",
            name="ck_jobs_status",
        ),
        # Attempt count must be non-negative.
        CheckConstraint("attempt >= 0", name="ck_jobs_attempt_nonneg"),
        # A finished job must have a finished_at timestamp.
        CheckConstraint(
            "status NOT IN ('completed', 'failed', 'dead') OR finished_at IS NOT NULL",
            name="ck_jobs_finished_at_required",
        ),
        # A running job must have a worker_id and lease_expires_at.
        CheckConstraint(
            "status != 'running' OR (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_jobs_running_requires_lease",
        ),
        # Error fields only on failed/dead jobs.
        CheckConstraint(
            "status NOT IN ('failed', 'dead') OR error_message IS NOT NULL",
            name="ck_jobs_error_message_on_failure",
        ),
        # Bounded error message.
        CheckConstraint(
            "error_message IS NULL OR length(error_message) <= 2000",
            name="ck_jobs_error_message_max",
        ),
    )

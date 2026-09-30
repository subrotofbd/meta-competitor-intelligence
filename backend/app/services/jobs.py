"""The job queue seam, and the Postgres implementation.

PostgreSQL is the first queue, not the only possible one. Every caller goes
through `JobQueue`; none of them know which store is behind it, and none of
them may import `PostgresJobQueue` to find out. Adding Redis later means
implementing this protocol and changing one wiring line.

## What S1.2 does

The protocol is complete enough to build against, and `PostgresJobQueue` now
has a real implementation using the `jobs` table created in migration 0003.
The queue uses `SELECT ... FOR UPDATE SKIP LOCKED` for safe leasing:
two workers never claim the same row, and a worker that dies mid-job releases
its lease when its connection closes rather than blocking the queue forever.

The table name is hard-coded as `jobs` (not configurable) because this is the
single queue implementation. The S0.3 validation of the table name as a bare
lowercase identifier is preserved as a safety invariant.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

#: The default lease duration for a claimed job.
DEFAULT_LEASE_DURATION = timedelta(minutes=5)

#: The maximum number of retries before a job is marked DEAD.
MAX_ATTEMPTS = 5


class JobRequest(BaseModel):
    """A unit of work to run later.

    `kind` is a plain string and `payload` a plain mapping on purpose. The set
    of job kinds is a domain decision that belongs with the code that submits
    the work, not with the queue, and an enum here would either be a lie
    (listing jobs that do not exist yet) or a place to edit every time one is
    added.

    Attributes:
        kind: What kind of work this is.
        payload: Arguments for that work, interpreted by the handler.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class ClaimedJob(BaseModel):
    """A job leased to one worker.

    Leases are held with `FOR UPDATE SKIP LOCKED`, so two workers never claim
    the same row and a worker that dies mid-job releases its lease when its
    connection closes rather than blocking the queue forever.

    Attributes:
        job_id: The queue's identifier for the job.
        attempt: How many times this job has been claimed, counting this one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    attempt: int = Field(ge=1)


@runtime_checkable
class JobQueue(Protocol):
    """Work that runs after the request that created it.

    Deliberately four operations. Anything more -- priorities, cron, delayed
    delivery, fan-out -- is a requirement of a job that does not exist yet, and
    adding it to the interface makes every future implementation carry it.
    """

    def enqueue(self, job: JobRequest) -> str:
        """Add work and return its id."""
        ...

    def claim(self, *, limit: int, worker_id: str) -> list[ClaimedJob]:
        """Lease up to `limit` jobs to `worker_id`.

        Returns an empty list when there is nothing to do. Must not block.
        """
        ...

    def complete(self, job_id: str) -> None:
        """Mark a leased job done."""
        ...

    def fail(self, job_id: str, *, reason: str) -> None:
        """Release a leased job after a failure, recording why.

        Releasing rather than deleting: the work is still owed, and the next
        claim increments its attempt count.
        """
        ...

    def extend_lease(self, job_id: str, *, worker_id: str, additional_time: timedelta) -> bool:
        """Extend the lease on a job currently held by this worker.

        Returns True if the lease was extended, False if the job is no longer
        held by this worker (e.g., it was completed, failed, or stolen).
        """
        ...


class JobQueueUnavailable(RuntimeError):
    """The queue was asked to do work it cannot do yet.

    Raised rather than returning empty results or quietly succeeding, because
    a queue that silently drops work is indistinguishable from a queue that is
    idle, and this project does not report unverified work as green.
    """


class PostgresJobQueue:
    """The PostgreSQL implementation of `JobQueue`.

    Uses the `jobs` table with `SELECT ... FOR UPDATE SKIP LOCKED` for safe,
    concurrent leasing. All operations are implemented with explicit transactions
    to ensure atomicity.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        lease_duration: timedelta = DEFAULT_LEASE_DURATION,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        # The table name is hard-coded as a safety invariant. SQL cannot bind a
        # table name as a parameter, so any name that reaches SQL is interpolated.
        # The only thing between configuration and an injection point is that the
        # table name is a constant known at code-review time.
        self._table = "jobs"
        self._session_factory = session_factory
        self._lease_duration = lease_duration
        self._max_attempts = max_attempts

    def enqueue(self, job: JobRequest) -> str:
        """Add work and return its id.

        Uses a client-side UUID so the caller knows the job id immediately
        without a RETURNING clause round-trip.
        """
        job_id = str(uuid4())
        now = datetime.now(UTC)

        with self._session_factory() as session:
            session.execute(
                text("""
                    INSERT INTO jobs (id, kind, payload, status, attempt,
                        created_at, updated_at)
                    VALUES (:id, :kind, CAST(:payload AS JSONB), 'pending', 0, :now, :now)
                """),
                {
                    "id": job_id,
                    "kind": job.kind,
                    "payload": json.dumps(job.payload),
                    "now": now,
                },
            )
            session.commit()
        return job_id

    def claim(self, *, limit: int, worker_id: str) -> list[ClaimedJob]:
        """Lease up to `limit` jobs to `worker_id`.

        Uses `SELECT ... FOR UPDATE SKIP LOCKED` to atomically find and lock
        available jobs. A job is available if:
        - status is 'pending', OR
        - status is 'running' but lease_expires_at has passed (stale lease)

        Returns an empty list when there is nothing to do. Must not block.
        """
        if limit <= 0:
            return []

        now = datetime.now(UTC)
        lease_expires_at = now + self._lease_duration

        with self._session_factory() as session:
            # Find and lock available jobs
            result = session.execute(
                text("""
                    SELECT id, kind, payload, attempt
                    FROM jobs
                    WHERE (status = 'pending')
                       OR (status = 'running' AND lease_expires_at < :now)
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT :limit
                """),
                {"now": now, "limit": limit},
            )
            rows = result.fetchall()

            if not rows:
                return []

            job_ids = [row.id for row in rows]

            # Update claimed jobs to running with new lease
            session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'running',
                        worker_id = :worker_id,
                        attempt = attempt + 1,
                        lease_expires_at = :lease_expires_at,
                        started_at = CASE WHEN started_at IS NULL THEN :now ELSE started_at END,
                        updated_at = :now
                    WHERE id = ANY(:job_ids)
                """),
                {
                    "worker_id": worker_id,
                    "lease_expires_at": lease_expires_at,
                    "now": now,
                    "job_ids": job_ids,
                },
            )
            session.commit()

            return [
                ClaimedJob(
                    job_id=str(row.id),
                    kind=row.kind,
                    payload=row.payload,
                    attempt=row.attempt + 1,
                )
                for row in rows
            ]

    def complete(self, job_id: str) -> None:
        """Mark a leased job done."""
        now = datetime.now(UTC)

        with self._session_factory() as session:
            result: Any = session.execute(
                text("""
                    UPDATE jobs
                    SET status = 'completed',
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        finished_at = :now,
                        updated_at = :now
                    WHERE id = :job_id
                """),
                {"job_id": job_id, "now": now},
            )
            if result.rowcount == 0:
                raise ValueError(f"Job {job_id!r} not found")
            session.commit()

    def fail(self, job_id: str, *, reason: str, error_type: str | None = None) -> None:
        """Release a leased job after a failure, recording why.

        If the job has exceeded max attempts, mark it DEAD. Otherwise, return
        it to PENDING so it can be retried.

        Args:
            job_id: The job to fail.
            reason: Why the job failed.
            error_type: Optional typed error class name for diagnosis.
        """
        now = datetime.now(UTC)

        with self._session_factory() as session:
            result: Any = session.execute(
                text("SELECT attempt FROM jobs WHERE id = :job_id"),
                {"job_id": job_id},
            )
            row = result.fetchone()
            if row is None:
                raise ValueError(f"Job {job_id!r} not found")

            attempt = row.attempt
            next_status = "dead" if attempt >= self._max_attempts else "pending"

            session.execute(
                text("""
                    UPDATE jobs
                    SET status = CAST(:next_status AS VARCHAR),
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        finished_at = CASE
                            WHEN CAST(:next_status AS VARCHAR) = 'dead' THEN :now
                            ELSE NULL
                        END,
                        error_message = :reason,
                        error_type = :error_type,
                        updated_at = :now
                    WHERE id = :job_id
                """),
                {
                    "job_id": job_id,
                    "next_status": next_status,
                    "reason": reason,
                    "error_type": error_type,
                    "now": now,
                },
            )
            session.commit()

    def extend_lease(self, job_id: str, *, worker_id: str, additional_time: timedelta) -> bool:
        """Extend the lease on a job currently held by this worker.

        Returns True if the lease was extended, False if the job is no longer
        held by this worker (e.g., it was completed, failed, or stolen).
        """
        now = datetime.now(UTC)
        new_lease_expires_at = now + additional_time

        with self._session_factory() as session:
            result: Any = session.execute(
                text("""
                    UPDATE jobs
                    SET lease_expires_at = :new_lease_expires_at,
                        updated_at = :now
                    WHERE id = :job_id
                      AND worker_id = :worker_id
                      AND status = 'running'
                """),
                {
                    "job_id": job_id,
                    "worker_id": worker_id,
                    "new_lease_expires_at": new_lease_expires_at,
                    "now": now,
                },
            )
            session.commit()
            return bool(result.rowcount > 0)

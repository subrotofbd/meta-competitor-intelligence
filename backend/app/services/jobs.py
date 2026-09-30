"""The job queue seam, and the Postgres implementation's declared shape.

PostgreSQL is the first queue, not the only possible one. Every caller goes
through `JobQueue`; none of them know which store is behind it, and none of
them may import `PostgresJobQueue` to find out. Adding Redis later means
implementing this protocol and changing one wiring line.

## What S0.3 does and does not contain

The protocol is complete enough to build against, and `PostgresJobQueue` exists
to pin the shape of the implementation: a session factory, a table name, and
four operations. **It performs no work yet.** There is no jobs table, and S0.3
adds no migration, so every operation raises `JobQueueUnavailable` naming the
checkpoint that supplies the table.

That is a deliberate boundary rather than a stub waiting to be filled in. A
queue built before the thing that consumes it is a queue designed against
imagined requirements; the work in S1.2 starts from the actual collection run
that needs to be queued.

## Why the table name is validated

SQL cannot bind a table name as a parameter. A name that reaches SQL has to be
interpolated, so it has to be checked. `PostgresJobQueue` accepts only a plain
lowercase identifier and raises on anything else. Quoting would also work, but
it invites a caller to pass `"schema"."table"` and the validation is then the
only thing standing between configuration and an injection point.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

#: A bare PostgreSQL identifier. No quotes, no dots, no spaces, no capitals.
_SQL_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")

#: The checkpoint that creates the jobs table and implements these operations.
_PENDING = "S1.2"


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


class JobQueueUnavailable(RuntimeError):
    """The queue was asked to do work it cannot do yet.

    Raised rather than returning empty results or quietly succeeding, because
    a queue that silently drops work is indistinguishable from a queue that is
    idle, and this project does not report unverified work as green.
    """


class PostgresJobQueue:
    """The PostgreSQL implementation of `JobQueue`, not yet operational.

    Holds the two things the implementation will need -- a session factory and
    a table name -- and refuses every operation until the jobs table exists in
    S1.2. Constructing it is safe and cheap; calling it is not, by design.
    """

    def __init__(self, session_factory: sessionmaker[Session], *, table: str = "jobs") -> None:
        if _SQL_IDENTIFIER.fullmatch(table) is None:
            raise ValueError(
                "queue table must be a bare lowercase SQL identifier "
                f"(letters, digits, underscore; not starting with a digit); got {table!r}"
            )
        self._session_factory = session_factory
        self._table = table

    def enqueue(self, job: JobRequest) -> str:
        raise self._unavailable("enqueue")

    def claim(self, *, limit: int, worker_id: str) -> list[ClaimedJob]:
        raise self._unavailable("claim")

    def complete(self, job_id: str) -> None:
        raise self._unavailable("complete")

    def fail(self, job_id: str, *, reason: str) -> None:
        raise self._unavailable("fail")

    def _unavailable(self, operation: str) -> JobQueueUnavailable:
        return JobQueueUnavailable(
            f"PostgresJobQueue.{operation} is not implemented: the "
            f"{self._table!r} table is created in {_PENDING}"
        )

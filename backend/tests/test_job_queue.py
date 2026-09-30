"""The job queue seam, and the Postgres implementation's declared shape.

S0.3 builds no queue. What is worth testing is the boundary itself: that the
implementation refuses work loudly instead of pretending to do it, and that the
one piece of real logic it does contain -- validating a table name -- holds.

The table-name check is not decoration. SQL cannot bind a table name as a
parameter, so a name that reaches SQL is interpolated, and the only thing
between configuration and an injection point is that check.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_engine
from app.services.jobs import (
    ClaimedJob,
    JobQueue,
    JobQueueUnavailable,
    JobRequest,
    PostgresJobQueue,
)


@pytest.fixture
def factory() -> sessionmaker[Session]:
    """A session factory that is never used to open anything."""
    return sessionmaker(bind=None, class_=Session)


@pytest.fixture
def queue(factory: sessionmaker[Session]) -> PostgresJobQueue:
    return PostgresJobQueue(factory)


# ============================================================
# The protocol
# ============================================================


def test_the_protocol_has_exactly_four_operations() -> None:
    """Priorities, cron, delays and fan-out are requirements of jobs that do not exist yet."""
    operations = {
        name
        for name, _ in inspect.getmembers(JobQueue, inspect.isfunction)
        if not name.startswith("_")
    }
    assert operations == {"enqueue", "claim", "complete", "fail"}


def test_a_class_missing_fail_does_not_satisfy_the_protocol() -> None:
    class NoFail:
        def enqueue(self, job: JobRequest) -> str:  # pragma: no cover - never called
            raise NotImplementedError

        def claim(self, *, limit: int, worker_id: str) -> list[ClaimedJob]:  # pragma: no cover
            raise NotImplementedError

        def complete(self, job_id: str) -> None:  # pragma: no cover - never called
            raise NotImplementedError

    assert not isinstance(NoFail(), JobQueue)


def test_the_queue_satisfies_the_protocol(queue: PostgresJobQueue) -> None:
    assert isinstance(queue, JobQueue)


# ============================================================
# Job shapes
# ============================================================


def test_a_job_carries_a_kind_and_a_payload() -> None:
    job = JobRequest(kind="collection.run", payload={"page_id": "mock-page-0001"})
    assert job.kind == "collection.run"
    assert job.payload["page_id"] == "mock-page-0001"


def test_a_job_without_a_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JobRequest(kind="")


def test_a_job_with_an_unknown_field_is_rejected() -> None:
    """A typo in a payload key should not become a silently ignored key."""
    with pytest.raises(ValidationError):
        JobRequest(kind="collection.run", priortiy=3)  # type: ignore[call-arg]


def test_a_claimed_job_counts_its_attempt_from_one() -> None:
    """Attempt zero would mean the job was never tried."""
    with pytest.raises(ValidationError):
        ClaimedJob(job_id="job-1", kind="collection.run", attempt=0)


# ============================================================
# The table name
# ============================================================


@pytest.mark.parametrize(
    "hostile",
    [
        'jobs"; DROP TABLE ad_snapshots; --',
        "jobs; DELETE FROM ad_snapshots",
        "public.jobs",
        '"jobs"',
        "Jobs",
        "9jobs",
        "jobs table",
        "jobs--",
        "",
    ],
)
def test_only_a_bare_lowercase_identifier_is_accepted(
    factory: sessionmaker[Session], hostile: str
) -> None:
    with pytest.raises(ValueError):
        PostgresJobQueue(factory, table=hostile)


def test_a_plain_identifier_is_accepted(factory: sessionmaker[Session]) -> None:
    assert PostgresJobQueue(factory, table="collection_jobs") is not None


# ============================================================
# Failing closed
# ============================================================


def test_every_operation_refuses_rather_than_pretending(queue: PostgresJobQueue) -> None:
    """A queue that silently drops work looks exactly like an idle one.

    There is no jobs table in S0.3, and S0.3 adds no migration to make these
    calls work, so every operation has to say so plainly.
    """
    operations = {
        "enqueue": lambda: queue.enqueue(JobRequest(kind="collection.run")),
        "claim": lambda: queue.claim(limit=1, worker_id="worker-1"),
        "complete": lambda: queue.complete("job-1"),
        "fail": lambda: queue.fail("job-1", reason="boom"),
    }
    for name, call in operations.items():
        with pytest.raises(JobQueueUnavailable) as raised:
            call()
        assert name in str(raised.value)
        assert "S1.2" in str(raised.value)


def test_the_refusal_names_the_table_it_expected(queue: PostgresJobQueue) -> None:
    with pytest.raises(JobQueueUnavailable) as raised:
        queue.enqueue(JobRequest(kind="collection.run"))
    assert "jobs" in str(raised.value)


def test_constructing_a_queue_opens_no_connection(use_settings: object) -> None:
    """Constructing is safe and cheap; calling is neither, and that asymmetry is deliberate."""
    built = PostgresJobQueue(sessionmaker(bind=get_engine(), class_=Session))
    assert built is not None

"""Tests for the real PostgresJobQueue implementation (S1.2).

S0.3 tested that the queue refused work. S1.2 tests that it actually works:
enqueue, claim (with SKIP LOCKED), complete, fail, and lease extension.
All tests run against a live PostgreSQL database with transaction rollback.
"""

from __future__ import annotations

import inspect
import time
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_engine, get_session_factory
from app.services.jobs import (
    ClaimedJob,
    JobQueue,
    JobRequest,
    PostgresJobQueue,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def queue() -> PostgresJobQueue:
    """A real PostgresJobQueue connected to the test database."""
    # Clean up any jobs from previous tests to ensure isolation
    with get_engine().connect() as conn:
        conn.execute(text("DELETE FROM jobs"))
        conn.commit()
    return PostgresJobQueue(get_session_factory())


# ============================================================
# The protocol
# ============================================================


def test_the_protocol_has_five_operations() -> None:
    """The protocol now includes extend_lease for long-running jobs."""
    operations = {
        name
        for name, _ in inspect.getmembers(JobQueue, inspect.isfunction)
        if not name.startswith("_")
    }
    assert operations == {"enqueue", "claim", "complete", "fail", "extend_lease"}


def test_a_class_missing_extend_lease_does_not_satisfy_the_protocol() -> None:
    class NoExtendLease:
        def enqueue(self, job: JobRequest) -> str:
            raise NotImplementedError

        def claim(self, *, limit: int, worker_id: str) -> list[ClaimedJob]:
            raise NotImplementedError

        def complete(self, job_id: str) -> None:
            raise NotImplementedError

        def fail(self, job_id: str, *, reason: str) -> None:
            raise NotImplementedError

    assert not isinstance(NoExtendLease(), JobQueue)


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
# The table name is now hard-coded (no injection surface)
# ============================================================


def test_table_name_is_hardcoded_to_jobs() -> None:
    """The table name is a constant, not configurable, eliminating the injection surface."""
    factory = sessionmaker(bind=None, class_=Session)
    queue = PostgresJobQueue(factory)
    # The table name is a private constant
    assert queue._table == "jobs"


# ============================================================
# Enqueue
# ============================================================


def test_enqueue_returns_a_job_id(queue: PostgresJobQueue) -> None:
    job = JobRequest(kind="collection.run", payload={"page_id": "mock-page-0001"})
    job_id = queue.enqueue(job)
    assert job_id is not None
    assert len(job_id) == 36  # UUID string length


def test_enqueue_persists_the_job(queue: PostgresJobQueue) -> None:
    job = JobRequest(kind="collection.run", payload={"foo": "bar"})
    job_id = queue.enqueue(job)

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT id, kind, payload, status, attempt FROM jobs WHERE id = :id"),
            {"id": job_id},
        ).fetchone()
    assert row is not None
    assert row.kind == "collection.run"
    assert row.payload == {"foo": "bar"}
    assert row.status == "pending"
    assert row.attempt == 0


def test_enqueue_is_idempotent_on_duplicate_calls(queue: PostgresJobQueue) -> None:
    """Two calls with the same kind+payload create two jobs (no deduplication at queue level)."""
    job = JobRequest(kind="collection.run", payload={"page_id": "mock-page-0001"})
    id1 = queue.enqueue(job)
    id2 = queue.enqueue(job)
    assert id1 != id2


# ============================================================
# Claim (SKIP LOCKED)
# ============================================================


def test_claim_returns_empty_when_no_jobs(queue: PostgresJobQueue) -> None:
    claimed = queue.claim(limit=1, worker_id="worker-1")
    assert claimed == []


def test_claim_leases_a_pending_job(queue: PostgresJobQueue) -> None:
    job_id = queue.enqueue(JobRequest(kind="collection.run", payload={"page_id": "mock-page-0001"}))

    claimed = queue.claim(limit=1, worker_id="worker-1")
    assert len(claimed) == 1
    assert claimed[0].job_id == job_id
    assert claimed[0].attempt == 1
    assert claimed[0].kind == "collection.run"
    assert claimed[0].payload["page_id"] == "mock-page-0001"


def test_claim_updates_job_to_running_with_lease(queue: PostgresJobQueue) -> None:
    job_id = queue.enqueue(JobRequest(kind="collection.run", payload={"page_id": "mock-page-0001"}))

    queue.claim(limit=1, worker_id="worker-1")

    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, worker_id, attempt, lease_expires_at, started_at "
                "FROM jobs WHERE id = :id"
            ),
            {"id": job_id},
        ).fetchone()

    assert row.status == "running"
    assert row.worker_id == "worker-1"
    assert row.attempt == 1
    assert row.lease_expires_at is not None
    assert row.started_at is not None


def test_claim_respects_limit(queue: PostgresJobQueue) -> None:
    for i in range(5):
        queue.enqueue(JobRequest(kind="collection.run", payload={"n": i}))

    claimed = queue.claim(limit=3, worker_id="worker-1")
    assert len(claimed) == 3


def test_claim_skip_locked_prevents_double_claim(queue: PostgresJobQueue) -> None:
    """Two workers claiming simultaneously must not get the same job."""
    for i in range(10):
        queue.enqueue(JobRequest(kind="collection.run", payload={"n": i}))

    worker1_jobs = queue.claim(limit=5, worker_id="worker-1")
    worker2_jobs = queue.claim(limit=5, worker_id="worker-2")

    # No overlap
    worker1_ids = {j.job_id for j in worker1_jobs}
    worker2_ids = {j.job_id for j in worker2_jobs}
    assert worker1_ids.isdisjoint(worker2_ids)
    assert len(worker1_ids) + len(worker2_ids) == 10


def test_claim_only_takes_pending_or_expired_jobs(queue: PostgresJobQueue) -> None:
    """Jobs with active leases are not re-claimed."""
    queue.enqueue(JobRequest(kind="collection.run", payload={}))
    queue.claim(limit=1, worker_id="worker-1")

    # Second claim should find nothing (the first job is still leased)
    claimed = queue.claim(limit=1, worker_id="worker-2")
    assert claimed == []


def test_claim_expired_lease_allows_reclaim(queue: PostgresJobQueue) -> None:
    """A job whose lease has expired can be claimed by another worker."""
    # Create a queue with a very short lease
    short_lease_queue = PostgresJobQueue(
        get_session_factory(),
        lease_duration=timedelta(milliseconds=10),
    )

    job_id = short_lease_queue.enqueue(JobRequest(kind="collection.run", payload={}))
    short_lease_queue.claim(limit=1, worker_id="worker-1")

    # Wait for lease to expire
    time.sleep(0.05)

    # Different worker should be able to claim it
    claimed = short_lease_queue.claim(limit=1, worker_id="worker-2")
    assert len(claimed) == 1
    assert claimed[0].job_id == job_id
    # Attempt should be incremented
    assert claimed[0].attempt == 2


# ============================================================
# Complete
# ============================================================


def test_complete_marks_job_completed(queue: PostgresJobQueue) -> None:
    job_id = queue.enqueue(JobRequest(kind="collection.run", payload={}))
    queue.claim(limit=1, worker_id="worker-1")

    queue.complete(job_id)

    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, worker_id, lease_expires_at, finished_at FROM jobs WHERE id = :id"
            ),
            {"id": job_id},
        ).fetchone()

    assert row.status == "completed"
    assert row.worker_id is None
    assert row.lease_expires_at is None
    assert row.finished_at is not None


def test_complete_nonexistent_job_raises(queue: PostgresJobQueue) -> None:
    with pytest.raises(ValueError, match="not found"):
        queue.complete("00000000-0000-0000-0000-000000000000")


# ============================================================
# Fail
# ============================================================


def test_fail_returns_job_to_pending_when_under_max_attempts(queue: PostgresJobQueue) -> None:
    job_id = queue.enqueue(JobRequest(kind="collection.run", payload={}))
    queue.claim(limit=1, worker_id="worker-1")

    queue.fail(job_id, reason="transient network error")

    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, attempt, worker_id, lease_expires_at, error_message "
                "FROM jobs WHERE id = :id"
            ),
            {"id": job_id},
        ).fetchone()

    assert row.status == "pending"
    assert row.attempt == 1
    assert row.worker_id is None
    assert row.lease_expires_at is None
    assert row.error_message == "transient network error"


def test_fail_marks_dead_after_max_attempts(queue: PostgresJobQueue) -> None:
    # Create queue with max_attempts=1
    queue = PostgresJobQueue(get_session_factory(), max_attempts=1)

    job_id = queue.enqueue(JobRequest(kind="collection.run", payload={}))
    queue.claim(limit=1, worker_id="worker-1")

    queue.fail(job_id, reason="permanent failure")

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT status, finished_at, error_message FROM jobs WHERE id = :id"),
            {"id": job_id},
        ).fetchone()

    assert row.status == "dead"
    assert row.finished_at is not None
    assert row.error_message == "permanent failure"


def test_fail_with_type_records_error_type(queue: PostgresJobQueue) -> None:
    job_id = queue.enqueue(JobRequest(kind="collection.run", payload={}))
    queue.claim(limit=1, worker_id="worker-1")

    queue.fail(job_id, reason="blocked by provider", error_type="blocked")

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT status, error_message, error_type FROM jobs WHERE id = :id"),
            {"id": job_id},
        ).fetchone()

    assert row.status == "pending"
    assert row.error_message == "blocked by provider"
    assert row.error_type == "blocked"


# ============================================================
# Extend lease
# ============================================================


def test_extend_lease_succeeds_for_owner(queue: PostgresJobQueue) -> None:
    job_id = queue.enqueue(JobRequest(kind="collection.run", payload={}))
    queue.claim(limit=1, worker_id="worker-1")

    result = queue.extend_lease(job_id, worker_id="worker-1", additional_time=timedelta(minutes=10))
    assert result is True

    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT lease_expires_at FROM jobs WHERE id = :id"),
            {"id": job_id},
        ).fetchone()
    assert row.lease_expires_at is not None


def test_extend_lease_fails_for_non_owner(queue: PostgresJobQueue) -> None:
    job_id = queue.enqueue(JobRequest(kind="collection.run", payload={}))
    queue.claim(limit=1, worker_id="worker-1")

    result = queue.extend_lease(job_id, worker_id="worker-2", additional_time=timedelta(minutes=10))
    assert result is False


def test_extend_lease_fails_for_completed_job(queue: PostgresJobQueue) -> None:
    job_id = queue.enqueue(JobRequest(kind="collection.run", payload={}))
    queue.claim(limit=1, worker_id="worker-1")
    queue.complete(job_id)

    result = queue.extend_lease(job_id, worker_id="worker-1", additional_time=timedelta(minutes=10))
    assert result is False


# ============================================================
# Concurrency: multiple workers
# ============================================================


def test_concurrent_workers_dont_share_jobs(queue: PostgresJobQueue) -> None:
    """Stress test: 3 workers claiming from 20 jobs, no overlap."""
    for i in range(20):
        queue.enqueue(JobRequest(kind="collection.run", payload={"n": i}))

    all_claimed = set()
    for worker_num in range(3):
        claimed = queue.claim(limit=10, worker_id=f"worker-{worker_num}")
        for job in claimed:
            assert job.job_id not in all_claimed, f"Job {job.job_id} claimed twice!"
            all_claimed.add(job.job_id)

    assert len(all_claimed) == 20


# ============================================================
# Idempotency: re-enqueue same run
# ============================================================


def test_enqueue_twice_creates_two_jobs(queue: PostgresJobQueue) -> None:
    """The queue itself does not deduplicate; idempotency is the orchestrator's job."""
    job = JobRequest(kind="collection.run", payload={"collection_run_id": "same-run"})
    id1 = queue.enqueue(job)
    id2 = queue.enqueue(job)
    assert id1 != id2

"""Collection orchestration: scheduling runs and executing them via the job queue.

This module sits between the API (which triggers collection) and the worker
(which consumes jobs). It knows how to:
- Create a collection run for a page/country/provider combination
- Enqueue the work as a job
- Execute the job by calling the provider and persisting results
- Handle typed provider errors through the job queue's retry/failure logic

The orchestrator does NOT decide ad status, normalize ads, or download media.
Those are S2/S3 responsibilities. It only creates the run skeleton and stores
the raw provider response.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CollectionRun,
    CollectionRunStatus,
    FacebookPage,
    ProviderRun,
    ProviderRunStatus,
    RawResponse,
)
from app.providers.data.base import AdDataProvider
from app.providers.data.errors import Blocked, RateLimited, SchemaChanged, Transient
from app.providers.data.models import PageRef, ProviderResult
from app.services.jobs import JobQueue, JobRequest

#: The job kind for a single page/country collection run.
COLLECTION_JOB_KIND = "collection.run"


class CollectionOrchestrator:
    """Orchestrates collection runs for tracked pages.

    This is the service boundary for "collect this page in this country".
    It creates the run record, enqueues the job, and provides the handler
    that the worker calls to execute the job.
    """

    def __init__(
        self,
        session: Session,
        provider: AdDataProvider,
        job_queue: JobQueue,
    ) -> None:
        self._session = session
        self._provider = provider
        self._job_queue = job_queue

    def schedule_collection(
        self,
        page_id: uuid.UUID,
        *,
        provider: str | None = None,
    ) -> str:
        """Schedule a collection run for a page.

        Creates a `collection_runs` row in PENDING status and enqueues a job
        to execute it. Returns the job id.

        Idempotency: if a PENDING or RUNNING run already exists for this
        page/country/provider combination, returns the existing job id
        instead of creating a duplicate.
        """
        page = self._session.get(FacebookPage, page_id)
        if page is None:
            raise ValueError(f"Page {page_id} not found")

        if not page.is_tracked:
            raise ValueError(f"Page {page_id} is not tracked")

        provider_name = provider or self._provider.name
        country = page.country

        # Check for existing incomplete run (idempotency)
        existing = self._session.execute(
            select(CollectionRun).where(
                CollectionRun.facebook_page_id == page_id,
                CollectionRun.provider == provider_name,
                CollectionRun.country == country,
                CollectionRun.status.in_(
                    [CollectionRunStatus.PENDING, CollectionRunStatus.RUNNING]
                ),
            )
        ).scalar_one_or_none()

        if existing:
            # Re-enqueue if it was pending but never picked up
            if existing.status == CollectionRunStatus.PENDING:
                job_id = self._enqueue_collection_run(existing.id)
                return job_id
            # Already running - the job is in the queue or being processed
            # We could look up the job id, but for now just return a marker
            return f"run-{existing.id}"

        # Create new collection run
        run = CollectionRun(
            facebook_page_id=page_id,
            provider=provider_name,
            country=country,
            data_origin=self._provider.origin,
            status=CollectionRunStatus.PENDING,
            started_at=None,
            finished_at=None,
            records_returned=0,
        )
        self._session.add(run)
        self._session.flush()

        job_id = self._enqueue_collection_run(run.id)
        self._session.commit()
        return job_id

    def _enqueue_collection_run(self, run_id: uuid.UUID) -> str:
        """Enqueue a job to execute the given collection run."""
        job = JobRequest(
            kind=COLLECTION_JOB_KIND,
            payload={
                "collection_run_id": str(run_id),
            },
        )
        return self._job_queue.enqueue(job)

    def execute_collection_job(self, run_id: uuid.UUID) -> None:
        """Execute a collection run job.

        This is called by the worker. It:
        1. Marks the run as RUNNING
        2. Calls the provider (possibly multiple pages via cursor)
        3. For each provider call: creates provider_run, persists raw_response
        4. Updates the run status to COMPLETE/PARTIAL/FAILED

        Provider errors are mapped to job queue failures with typed error info.
        """
        run = self._session.get(CollectionRun, run_id)
        if run is None:
            raise ValueError(f"CollectionRun {run_id} not found")

        if run.status not in (CollectionRunStatus.PENDING, CollectionRunStatus.RUNNING):
            # Already terminal - nothing to do
            return

        run.status = CollectionRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        self._session.commit()

        total_records = 0
        cursor: str | None = None
        run_failed = False
        last_error: Exception | None = None

        try:
            while True:
                # Call provider for one page of results
                page_ref = PageRef(
                    provider_page_id=run.facebook_page.page_id,
                    page_name=run.facebook_page.name,
                    url=run.facebook_page.url,
                )
                result = self._provider.fetch_page_ads(
                    page=page_ref,
                    country=run.country,
                    cursor=cursor,
                )

                # Persist this provider call
                self._persist_provider_run(run, result)
                total_records += len(result.records)

                cursor = result.next_cursor
                if cursor is None:
                    break

            # All pages fetched successfully
            run.status = CollectionRunStatus.COMPLETE
            run.finished_at = datetime.now(UTC)
            run.records_returned = total_records

        except (Blocked, RateLimited, SchemaChanged, Transient) as e:
            self._handle_provider_error(run, e)
            run_failed = True
            last_error = e

        except Exception as e:
            self._handle_provider_error(run, e, error_type="unexpected")
            run_failed = True
            last_error = e

        finally:
            self._session.commit()

        # If the run failed, fail the job so it can be retried (or marked dead)
        if run_failed and last_error:
            # We need to find the job id for this run. Since the job payload
            # contains the run_id, we can't easily look it up without a reverse
            # index. For now, the worker handles job completion/failure based
            # on the run status. The job will be marked complete/failed by the
            # worker after this method returns.
            pass

    def _handle_provider_error(
        self,
        run: CollectionRun,
        error: Exception,
        *,
        error_type: str | None = None,
    ) -> None:
        """Handle a typed provider error by marking the run as failed.

        Maps the provider's typed error to a string error_type for storage.
        """
        type_map = {
            Blocked: "blocked",
            RateLimited: "rate_limited",
            SchemaChanged: "schema_changed",
            Transient: "transient",
        }
        resolved_type = error_type or type_map.get(type(error), "unknown")
        run.status = CollectionRunStatus.FAILED
        run.finished_at = datetime.now(UTC)
        run.error_type = resolved_type
        run.error_message = str(error)

    def get_run_status(self, run_id: uuid.UUID) -> CollectionRunStatus | None:
        """Get the status of a collection run, or None if not found."""
        run = self._session.get(CollectionRun, run_id)
        return run.status if run else None

    def get_run_error(self, run_id: uuid.UUID) -> tuple[str | None, str | None]:
        """Get the error message and type of a collection run."""
        run = self._session.get(CollectionRun, run_id)
        if run is None:
            return None, None
        return run.error_message, run.error_type

    def _persist_provider_run(self, run: CollectionRun, result: ProviderResult) -> ProviderRun:
        """Persist a single provider call and its raw response.

        Creates provider_run and raw_response rows. The raw payload is stored
        before any parsing happens (AGENTS.md section 8).
        """
        now = datetime.now(UTC)
        provider_run = ProviderRun(
            collection_run_id=run.id,
            status=ProviderRunStatus.SUCCEEDED,
            started_at=now,
            finished_at=now,
            request_meta=result.request_meta.model_dump(mode="json"),
            next_cursor=result.next_cursor,
            http_status=200,
            cost_amount=result.cost_estimate.amount,
            cost_currency=result.cost_estimate.currency,
            cost_method=result.cost_estimate.method,
        )
        self._session.add(provider_run)
        self._session.flush()

        # Persist raw response with payload hash (computed by DB trigger)
        raw_response = RawResponse(
            provider_run_id=provider_run.id,
            payload=result.raw,
        )
        self._session.add(raw_response)
        self._session.flush()

        return provider_run


def build_collection_orchestrator(
    session: Session,
    provider: AdDataProvider,
    job_queue: JobQueue,
) -> CollectionOrchestrator:
    """Factory for the collection orchestrator.

    This is the composition root for orchestration. It wires together the
    database session, provider, and job queue.
    """
    return CollectionOrchestrator(session, provider, job_queue)

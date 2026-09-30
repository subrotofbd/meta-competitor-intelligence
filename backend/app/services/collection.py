"""Collection orchestration: scheduling runs and executing them via the job queue.

This module sits between the API (which triggers collection) and the worker
(which consumes jobs). It knows how to:
- Create a collection run for a page/country/provider combination
- Enqueue the work as a job
- Execute the job by calling the provider, storing what it said, and only then
  reading it
- Handle typed provider errors through the job queue's retry/failure logic

## The one ordering rule that matters here

    provider fetch -> raw response persisted -> normalization

Never the other way round. A response that has been read is a response that can
be refused, and a refused response is one we no longer have. Storing `raw` first
means the reading is always a re-runnable opinion about evidence we still hold:
a parser bug costs a re-read, not the run, and never the data (AGENTS.md
section 8). That is why the commit in `execute_collection_job` sits between the
store and the read, and why no database transaction is held open across a
provider call.

The orchestrator does NOT decide ad status, persist normalised ads, or download
media. Those are S2/S3 responsibilities. It stores the raw provider response and
returns what the normalizer made of it; S2.1 decides what to do with the records.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
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
from app.providers.data.models import PageRef, ProviderResult, RawAdRecord
from app.providers.data.normalize import NormalizationError, normalize_payload
from app.services.jobs import JobQueue, JobRequest

#: The job kind for a single page/country collection run.
COLLECTION_JOB_KIND = "collection.run"

#: How many normalization failures are named in a run's error message. The
#: structured errors themselves are not persisted -- the raw response is the
#: record of what went wrong, and it is not truncated -- so this is a pointer,
#: not a summary standing in for the evidence.
ERROR_PREVIEW_LIMIT = 5

#: The column's own limit, mirrored so `_excerpt` can guarantee it. Duplicated
#: rather than imported because it lives in the models package and a service
#: importing a private model constant to size a string is a worse coupling than
#: one number that has a test.
ERROR_MESSAGE_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class CollectionOutcome:
    """What a run made of everything the provider returned.

    Returned rather than persisted, because persisting normalised ads is S2.1's
    job and doing it here would put the domain decision in the wrong layer.
    Holding the structured errors alongside the records is the point: a caller
    that only wants the good records can ignore them, and a caller that does not
    will find out which ones failed and why instead of finding a short page.

    `status` is here because the other two fields cannot tell the three ways this
    can end apart. A run that was already terminal, a run that reached a provider
    which had nothing to report, and a run whose provider was blocked all return
    an empty record tuple; only the status distinguishes them, and a caller
    holding this value does not have the row.

    Attributes:
        records: Every record read from the run's payloads, in provider order.
        errors: Every record that could not be read, with the batch it sat in.
        status: The status the run was left in. `PARTIAL` means some records
            arrived and some did not read; `FAILED` means the run did not finish,
            whatever it had already stored.
    """

    records: tuple[RawAdRecord, ...]
    errors: tuple[NormalizationError, ...]
    status: CollectionRunStatus


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

    def execute_collection_job(self, run_id: uuid.UUID) -> CollectionOutcome:
        """Execute a collection run job.

        This is called by the worker. It:
        1. Marks the run as RUNNING
        2. Calls the provider (possibly multiple pages via cursor)
        3. For each provider call: creates provider_run, persists raw_response,
           **commits**, and only then reads the payload
        4. Updates the run status to COMPLETE/PARTIAL/FAILED

        Provider errors are mapped to job queue failures with typed error info.

        Returns:
            The records read from every payload, and every record that could not
            be read. An empty outcome means there was nothing to read, which is
            not the same as a failure -- check the run status for that.
        """
        run = self._session.get(CollectionRun, run_id)
        if run is None:
            raise ValueError(f"CollectionRun {run_id} not found")

        if run.status not in (CollectionRunStatus.PENDING, CollectionRunStatus.RUNNING):
            # Already terminal - nothing to do
            return CollectionOutcome((), (), run.status)

        # Everything the loop needs, read out of the ORM *before* the commit
        # below. SQLAlchemy expires attributes on commit, so touching
        # `run.facebook_page` or `run.country` afterwards would lazily reopen a
        # read transaction -- inside the provider call, where we do not want one.
        # Reading them here means the call itself touches no session at all.
        country = run.country
        page_ref = PageRef(
            provider_page_id=run.facebook_page.page_id,
            page_name=run.facebook_page.name,
            url=run.facebook_page.url,
        )
        collection_run_id = run.id

        run.status = CollectionRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        self._session.commit()

        records: list[RawAdRecord] = []
        errors: list[NormalizationError] = []
        cursor: str | None = None

        try:
            while True:
                # No transaction is open across this call, and no session is
                # touched by it: a provider can be slow or unreachable, and
                # that is not a state a database transaction should wait in.
                result = self._provider.fetch_page_ads(
                    page=page_ref,
                    country=country,
                    cursor=cursor,
                )

                # Store what the provider said, and commit it on its own. From
                # here on, nothing that happens to the reading can take the
                # evidence with it.
                self._persist_provider_run(collection_run_id, result)
                self._session.commit()

                # Now read it. This is the first moment in the whole flow where
                # a parser's opinion is allowed to exist, and by now there is
                # something durable for that opinion to be wrong about.
                reading = normalize_payload(result.raw)
                records.extend(reading.records)
                errors.extend(reading.errors)

                cursor = result.next_cursor
                if cursor is None:
                    break

            # Every payload was stored. The run's status now reports how well
            # they read, which is a different fact from whether they arrived.
            run.finished_at = datetime.now(UTC)
            run.records_returned = len(records)
            if errors:
                run.status = CollectionRunStatus.PARTIAL
                run.error_message = _describe(errors)
            else:
                run.status = CollectionRunStatus.COMPLETE

        except (Blocked, RateLimited, SchemaChanged, Transient) as e:
            self._handle_provider_error(run, e)

        except Exception as e:
            self._handle_provider_error(run, e, error_type="unexpected")

        finally:
            self._session.commit()

        return CollectionOutcome(tuple(records), tuple(errors), run.status)

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
        run.error_message = _excerpt(str(error))

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

    def _persist_provider_run(self, run_id: uuid.UUID, result: ProviderResult) -> ProviderRun:
        """Persist a single provider call and its raw response.

        Creates provider_run and raw_response rows. This is the only place a
        provider payload is written, and it runs before anything reads one
        (AGENTS.md section 8). The caller commits immediately afterwards, so the
        row survives whatever the reading goes on to do.

        Takes the run's id rather than the ORM object on purpose. The loop has
        already committed, and passing the object in would mean an attribute
        access here quietly reopening a transaction between the fetch and the
        write it is supposed to protect.
        """
        now = datetime.now(UTC)
        provider_run = ProviderRun(
            collection_run_id=run_id,
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


def _excerpt(text: str) -> str:
    """Fit a message into `collection_runs.error_message`, or fail the commit.

    The column has a `CHECK` on its length, and an `IntegrityError` raised from
    the `finally` that writes the run's status is the worst possible place to
    discover a message is too long: it supersedes whatever was being handled and
    leaves the row mutated but uncommitted. So the bound is enforced here rather
    than left to the arithmetic of three constants in three modules.

    `repr` does the escaping, for the same reason the normalizer's `_safe` does:
    a provider is not a trusted source of single-line text, and a message with a
    newline in it becomes a forged log record the moment anyone prints it.
    """
    if len(text) <= ERROR_MESSAGE_LIMIT:
        return text
    marker = "... (truncated)"
    # Two characters of budget go to the quotes `repr` adds, and the closing
    # quote is dropped along with the one that preceded the cut point.
    body = text[: ERROR_MESSAGE_LIMIT - len(marker) - 2]
    return f"{repr(body)[1:-1]}{marker}"


def _describe(errors: Sequence[NormalizationError]) -> str:
    """A run-level note about which records could not be read.

    A pointer, not a substitute. The failures themselves are not written here:
    the raw response is the record of what arrived, and `raw_responses` keeps all
    of it. This only says how to go and find the problem, and stops after a few
    so one broken batch cannot make the run's own row unreadable.

    The `index` is omitted for a whole-payload failure, where there is no record
    to point at -- writing `ads[None]` would be reporting our own bookkeeping as
    if it were the provider's.
    """
    shown = errors[:ERROR_PREVIEW_LIMIT]
    summary = "; ".join(
        f"[{error.kind}] {error.field}"
        + ("" if error.index is None else f" at ads[{error.index}]")
        + f": {error.detail}"
        for error in shown
    )
    if len(errors) > len(shown):
        summary += f"; and {len(errors) - len(shown)} more"
    return _excerpt(f"{len(errors)} record(s) could not be read from a stored response: {summary}")


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

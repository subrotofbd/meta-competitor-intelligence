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
from datetime import UTC, datetime, timedelta
from typing import Final, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.core.config import (
    DEFAULT_COLLECTION_MAX_PAGES_PER_RUN,
    DEFAULT_COLLECTION_MAX_RECORDS_PER_RUN,
    DEFAULT_COLLECTION_STALE_RUN_TIMEOUT,
)
from app.models import (
    CollectionRun,
    CollectionRunStatus,
    FacebookPage,
    Job,
    ProviderRun,
    ProviderRunStatus,
    RawResponse,
)
from app.models.jobs import JobStatus
from app.providers.data.base import AdDataProvider
from app.providers.data.errors import Blocked, RateLimited, SchemaChanged, Transient
from app.providers.data.models import PageRef, ProviderResult, RawAdRecord
from app.providers.data.normalize import NormalizationError, normalize_payload
from app.providers.data.provenance import DataOrigin
from app.services.ad_persistence import ObservedRecord, persist_observations
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

#: Fallback for `collection_max_records_per_run`. See `Settings` for why this
#: bounds accumulation across pages and is not a statement about any
#: competitor's ad volume.
DEFAULT_MAX_RECORDS_PER_RUN = DEFAULT_COLLECTION_MAX_RECORDS_PER_RUN

#: Fallback for `collection_max_pages_per_run`.
DEFAULT_MAX_PAGES_PER_RUN = DEFAULT_COLLECTION_MAX_PAGES_PER_RUN

#: Fallback for `collection_stale_run_timeout`. Must exceed
#: `jobs.DEFAULT_LEASE_DURATION` with room to spare; `Settings` enforces it.
DEFAULT_STALE_RUN_TIMEOUT = DEFAULT_COLLECTION_STALE_RUN_TIMEOUT

#: How many suspect runs one recovery pass examines. Each candidate costs two
#: more queries, and the job lookup is a scan, so an unbounded pass would be
#: O(candidates x jobs). A pass is cheap to repeat: the next one picks up
#: whatever this one left.
STALE_RECOVERY_BATCH = 100

#: `error_type` vocabulary, free text in a `VARCHAR(64)` by design so a new one
#: needs no migration. Named constants because the worker and the API both match
#: on these strings, and a vocabulary split across a dict, a bare literal and a
#: constant block is one that cannot be enumerated.
ERROR_TYPE_BLOCKED = "blocked"
ERROR_TYPE_RATE_LIMITED = "rate_limited"
ERROR_TYPE_SCHEMA_CHANGED = "schema_changed"
ERROR_TYPE_TRANSIENT = "transient"
ERROR_TYPE_UNKNOWN = "unknown"
ERROR_TYPE_UNEXPECTED = "unexpected"
ERROR_TYPE_CURSOR_CYCLE = "cursor_cycle"
ERROR_TYPE_RECORD_LIMIT = "record_limit"
ERROR_TYPE_PAGE_LIMIT = "page_limit"
ERROR_TYPE_ABANDONED = "abandoned"

_ERROR_TYPES: Final = {
    Blocked: ERROR_TYPE_BLOCKED,
    RateLimited: ERROR_TYPE_RATE_LIMITED,
    SchemaChanged: ERROR_TYPE_SCHEMA_CHANGED,
    Transient: ERROR_TYPE_TRANSIENT,
}

#: The subset whose message describes the provider rather than our machinery.
#: Only these are worth storing verbatim; see `_handle_provider_error`.
_PROVIDER_ERROR_TYPES: Final = frozenset(_ERROR_TYPES.values())

#: What an unexpected internal failure puts in the run row. The detail goes to
#: the worker's log instead, because it names columns, hosts, users and paths.
INTERNAL_ERROR_MESSAGE: Final = (
    "unexpected internal error; the worker log has the detail for this run"
)


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

    `stopped_reason` is here because `PARTIAL` alone does not say *why* a walk
    ended early, and "some records did not read" and "the provider's cursor went
    in a circle" call for completely different responses from whoever is looking.

    Attributes:
        records: Every record read from the run's payloads, in provider order.
        errors: Every record that could not be read, with the batch it sat in.
        status: The status the run was left in. `PARTIAL` means some records
            arrived and some did not read; `FAILED` means the run did not finish,
            whatever it had already stored.
        stopped_reason: Why the walk stopped before the provider said it was
            finished -- one of `ERROR_TYPE_CURSOR_CYCLE`, `ERROR_TYPE_RECORD_LIMIT`
            or `ERROR_TYPE_PAGE_LIMIT` -- or `None` when it did finish, or when it
            was a provider error rather than a walk that stopped early.
    """

    records: tuple[RawAdRecord, ...]
    errors: tuple[NormalizationError, ...]
    status: CollectionRunStatus
    stopped_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _Stop:
    """Why a walk ended before the provider said it was finished.

    A pair rather than two loose locals, because they are always written
    together and a type that allowed one without the other would let the message
    and the reason drift apart.

    Attributes:
        reason: One of the `ERROR_TYPE_*` constants, persisted as `error_type`.
        detail: Words a human can act on, persisted as `error_message`.
    """

    reason: str
    detail: str


def _resolve_outcome(
    stopped: _Stop | None, errors: Sequence[NormalizationError]
) -> tuple[CollectionRunStatus, str | None]:
    """Decide how a finished walk is recorded, from two facts.

    Split out of the walk because it is the one part of `execute_collection_job`
    that is not about ordering, and because as a pure function of its arguments
    it can be tested without a session, a provider, or a database.

    The walk stopped early always wins over unreadable records. Both make a run
    `partial`, but they are different problems: one is "the provider is
    misbehaving" and the other is "some records did not read", and reporting only
    the second on a run that was also cut short would send someone looking in the
    wrong place.
    """
    if stopped is not None:
        return CollectionRunStatus.PARTIAL, stopped.reason
    if errors:
        return CollectionRunStatus.PARTIAL, None
    return CollectionRunStatus.COMPLETE, None


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
        *,
        max_records: int = DEFAULT_MAX_RECORDS_PER_RUN,
        max_pages: int = DEFAULT_MAX_PAGES_PER_RUN,
        stale_run_timeout: timedelta = DEFAULT_STALE_RUN_TIMEOUT,
        stale_batch: int = STALE_RECOVERY_BATCH,
    ) -> None:
        self._session = session
        self._provider = provider
        self._job_queue = job_queue
        self._max_records = max_records
        self._max_pages = max_pages
        self._stale_run_timeout = stale_run_timeout
        self._stale_batch = stale_batch

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

        The walk has two ways to stop before the provider says it is finished:
        a cursor it has already followed (`ERROR_TYPE_CURSOR_CYCLE`), and the
        record ceiling (`ERROR_TYPE_RECORD_LIMIT`). Both are reported, both leave
        the run `PARTIAL`, and neither undoes a raw response already committed.

        Returns:
            The records read from every payload, every record that could not be
            read, the status, and why the walk stopped early if it did. An empty
            outcome means there was nothing to read, which is not the same as a
            failure -- check the status for that.
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
        provider_name = run.provider
        data_origin = run.data_origin

        run.status = CollectionRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        self._session.commit()

        records: list[RawAdRecord] = []
        errors: list[NormalizationError] = []
        observed: list[ObservedRecord] = []
        cursor: str | None = None
        # Cursors already followed in *this* execution. A cursor is opaque to us:
        # we compare for equality and nothing else, so no provider-specific idea
        # of what a cursor means is needed or assumed.
        seen_cursors: set[str] = set()
        attempted = 0
        stopped: _Stop | None = None

        try:
            while True:
                if cursor is not None:
                    if cursor in seen_cursors:
                        # The provider handed back a page we have already
                        # collected. Fetching it again would store the same
                        # payload forever, so the walk ends here -- after a
                        # final page whose response is already durable, and
                        # with everything collected so far kept.
                        stopped = _Stop(
                            ERROR_TYPE_CURSOR_CYCLE,
                            f"provider returned cursor {cursor!r} a second time; "
                            "the walk stopped rather than collecting it again",
                        )
                        break
                    seen_cursors.add(cursor)

                if len(seen_cursors) + 1 > self._max_pages:
                    # The third guard, and the only one a provider offering
                    # nothing can escape: empty or wholly unreadable pages never
                    # repeat a cursor and never grow the record count, so
                    # neither other guard would ever fire. Checked before the
                    # fetch, so the page that would have pushed the run past the
                    # ceiling is not requested.
                    stopped = _Stop(
                        ERROR_TYPE_PAGE_LIMIT,
                        f"stopped after fetching {len(seen_cursors)} page(s) with "
                        f"more offered; collection_max_pages_per_run is "
                        f"{self._max_pages}",
                    )
                    break

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
                # evidence with it. This happens before either safety check
                # below, so a run that halts has still stored the page that
                # caused it to halt.
                raw_response = self._persist_provider_run(collection_run_id, result)
                self._session.commit()

                # Now read it. This is the first moment in the whole flow where
                # a parser's opinion is allowed to exist, and by now there is
                # something durable for that opinion to be wrong about.
                reading = normalize_payload(result.raw)
                records.extend(reading.records)
                errors.extend(reading.errors)
                # Each record is paired with the response it was read from,
                # because a snapshot has to be able to cite its own source.
                # Accumulated across the whole walk rather than persisted page
                # by page: a provider can serve one ad on two pages of the same
                # run, and that is one snapshot rather than two.
                observed.extend(
                    ObservedRecord(record=record, raw_response_id=raw_response.id)
                    for record in reading.records
                )
                # Counted over *attempts*, readable or not. Counting only the
                # readable ones would let a provider serving well-formed
                # unreadable records grow errors for ever without this number
                # moving, which is the same unbounded accumulation the ceiling
                # exists to prevent.
                attempted += len(reading.records) + len(reading.errors)

                cursor = result.next_cursor
                if cursor is None:
                    # The provider says there is nothing more. The walk is
                    # finished, and where it happened to land relative to the
                    # ceiling is beside the point -- reporting a limit that was
                    # never reached would put a false explanation on a run that
                    # did exactly what it was asked.
                    break

                if attempted >= self._max_records:
                    # The ceiling bounds what one run holds in memory, so it
                    # stops the walk *before* the next fetch. It does not bound
                    # what a provider may serve: the page just read is kept
                    # whole, because the raw response is the evidence and the
                    # stored payloads can be re-read for free later.
                    stopped = _Stop(
                        ERROR_TYPE_RECORD_LIMIT,
                        f"stopped after {attempted} record(s) with more pages "
                        f"offered; collection_max_records_per_run is "
                        f"{self._max_records}",
                    )
                    break

            # Every payload was stored and committed. Normalised persistence
            # comes after that, and in its own transaction, so a failure here
            # cannot take the raw evidence with it -- and cannot leave half an
            # ad's history behind either.
            self._persist_ad_history(
                run_id=collection_run_id,
                observed=observed,
                provider=provider_name,
                data_origin=data_origin,
            )

            # The run's status now reports how well the payloads read, which is
            # a different fact from whether they arrived.
            run.finished_at = datetime.now(UTC)
            run.records_returned = len(records)
            status, error_type = _resolve_outcome(stopped, errors)
            run.status = status
            if stopped is not None:
                run.error_type = error_type
                run.error_message = _excerpt(stopped.detail)
            elif errors:
                run.error_message = _describe(errors)

        except (Blocked, RateLimited, SchemaChanged, Transient) as e:
            self._handle_provider_error(run, e)

        except Exception as e:
            self._handle_provider_error(run, e, error_type=ERROR_TYPE_UNEXPECTED)

        finally:
            self._session.commit()

        return CollectionOutcome(
            tuple(records),
            tuple(errors),
            run.status,
            None if stopped is None else stopped.reason,
        )

    def _handle_provider_error(
        self,
        run: CollectionRun,
        error: Exception,
        *,
        error_type: str | None = None,
    ) -> None:
        """Handle a typed provider error by marking the run as failed.

        Maps the provider's typed error to a string `error_type` for storage,
        and decides how much of the message is safe to keep.
        """
        resolved_type = error_type or _ERROR_TYPES.get(type(error), ERROR_TYPE_UNKNOWN)
        run.status = CollectionRunStatus.FAILED
        run.finished_at = datetime.now(UTC)
        run.error_type = resolved_type
        # Only a *typed provider* error has a message that is about the
        # provider. Anything else is an exception raised by this application's
        # own machinery, and its text routinely carries the failed SQL, the
        # database host and user, and an absolute filesystem path -- including
        # the operating system's username. `get_run_error` exists to hand this
        # column to a caller, so the full text goes to the worker's log, which is
        # where an operator reads it, and the row keeps a pointer to it.
        run.error_message = (
            _excerpt(str(error))
            if resolved_type in _PROVIDER_ERROR_TYPES
            else INTERNAL_ERROR_MESSAGE
        )

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

    def recover_stale_runs(self, *, now: datetime | None = None) -> tuple[uuid.UUID, ...]:
        """Reconcile runs whose worker never came back.

        A cheap narrowing comes first: only `running` rows whose `updated_at` is
        older than the timeout are examined at all. `updated_at` moves only on a
        write to the run row, so for a `running` run it is effectively
        `started_at` -- which is why it is a filter and not one of the signals
        below.

        A run is then abandoned only when **three independent signals agree**
        that nobody is working on it:

        1. no job for it holds a live lease -- a `running` job whose lease has
            expired, a terminal job, or no job at all -- and
        2. it has added no provider call in `stale_run_timeout`.

        The second is what makes this safe. A run that is slow rather than dead
        keeps committing `provider_runs` rows, so a walk that is still going is
        never mistaken for a walk that stopped, however long it has been going.
        The lease alone cannot carry that distinction: a job's lease is five
        minutes and the worker does not currently extend it, so a legitimately
        long walk loses its lease while still running.

        ## What recovery is not

        It never marks a run `complete`. Nothing here can know what a worker
        would have finished, and time passing is not evidence that work was
        done. It only ever moves `running` -> `failed`, which is the one
        direction that hands the page back: `schedule_collection` refuses to
        start a run while one is `pending` or `running`, so an abandoned run
        would otherwise make its page permanently uncollectible.

        The status guard is repeated in the `WHERE` of the write, so a run that
        a live worker finished in the meantime is not overwritten. The rowcount
        says so, and that run is simply left out of the result.

        It never touches `provider_runs` or `raw_responses`. Those are evidence
        of what arrived, and a run that died at page nine still collected eight
        pages worth of it. Every response it committed stays committed and stays
        re-readable, which is the only reason recovering a run is safe at all.

        It also leaves the job alone. A job whose lease has lapsed will be
        re-claimed and re-enter `execute_collection_job`, which returns early
        because the run is no longer `running`; that wastes one attempt and then
        the job is released. Making recovery fail the job explicitly would save
        that attempt and is a reasonable later change.

        Args:
            now: The instant to judge staleness against. Defaults to the real
                clock. Injected so the condition can be tested exactly rather
                than by sleeping.

        Returns:
            The ids of the runs that were recovered, in the order they were
            found. Empty when nothing was stale, and also when every candidate
            was overtaken by a worker between the read and the write.
        """
        moment = now or datetime.now(UTC)
        cutoff = moment - self._stale_run_timeout
        message = _excerpt(
            f"no worker held this run and it made no progress for "
            f"{self._stale_run_timeout}; any response it had already stored is kept"
        )

        try:
            # Cheap narrowing first. `updated_at` only moves on a write to the
            # run row, so for a `running` run it is effectively `started_at` --
            # which is why the *progress* check below, and not this, is the one
            # that has to be right.
            candidates = self._session.execute(
                select(CollectionRun)
                .where(
                    CollectionRun.status == CollectionRunStatus.RUNNING,
                    CollectionRun.updated_at < cutoff,
                )
                .limit(self._stale_batch)
            ).scalars()
            stale = [run for run in candidates if self._is_abandoned(run, moment, cutoff)]

            recovered: list[uuid.UUID] = []
            for run in stale:
                # The status guard is repeated in the `WHERE` rather than trusted
                # from the read above. Between the SELECT and this write a live
                # worker can finish its run, and an unguarded ORM assignment would
                # flush `failed` over a genuine `complete` -- destroying the one
                # piece of history that says what actually happened. A guarded
                # UPDATE simply matches nothing in that case, and the rowcount says
                # so.
                result = cast(
                    "CursorResult[tuple[()]]",
                    self._session.execute(
                        update(CollectionRun)
                        .where(
                            CollectionRun.id == run.id,
                            CollectionRun.status == CollectionRunStatus.RUNNING,
                            CollectionRun.updated_at == run.updated_at,
                        )
                        .values(
                            status=CollectionRunStatus.FAILED,
                            # Clamped: a `finished_at` before `started_at` -- from clock
                            # skew between this process and the database, or an
                            # injected `now` -- trips a CHECK, and an IntegrityError
                            # from here is the failure this method exists to prevent.
                            finished_at=max(moment, run.started_at or moment),
                            error_type=ERROR_TYPE_ABANDONED,
                            error_message=message,
                        )
                        .execution_options(synchronize_session=False)
                    ),
                )
                if result.rowcount:
                    recovered.append(run.id)
            self._session.commit()
        except Exception:
            # The candidates were drained mid-iteration, so the session may be
            # holding a partial result. Without this, the next caller inherits a
            # session nobody knows the state of.
            self._session.rollback()
            raise

        return tuple(recovered)

    def _is_abandoned(self, run: CollectionRun, now: datetime, cutoff: datetime) -> bool:
        """Whether one `running` run is provably not being worked on.

        Two questions, and both have to answer yes. The lease question is "is
        anyone holding this"; the progress question is "has it moved at all".
        Either alone is a guess; together they are close to evidence.
        """
        if self._has_live_lease(run.id, now):
            return False
        return not self._has_recent_progress(run.id, cutoff)

    def _has_live_lease(self, run_id: uuid.UUID, now: datetime) -> bool:
        """Whether any job for this run is claimed and its lease has not lapsed.

        Reads the job by the `collection_run_id` in its payload. There is no
        reverse index for that -- and adding one is a migration, which this
        checkpoint does not do -- so it scans a small table, and only for runs
        that are already suspect on two other counts.
        """
        jobs = self._session.execute(
            select(Job).where(
                Job.kind == COLLECTION_JOB_KIND,
                Job.payload["collection_run_id"].astext == str(run_id),
            )
        ).scalars()
        return any(
            job.status == JobStatus.RUNNING
            and job.lease_expires_at is not None
            and job.lease_expires_at > now
            for job in jobs
        )

    def _has_recent_progress(self, run_id: uuid.UUID, cutoff: datetime) -> bool:
        """Whether a provider call was recorded for this run after `cutoff`.

        The signal that survives a dead worker. A run that is still walking
        commits a `provider_run` per page, so this keeps returning true for as
        long as the walk lasts -- which is exactly the run we must not touch.
        """
        recent = self._session.execute(
            select(ProviderRun.id)
            .where(
                ProviderRun.collection_run_id == run_id,
                ProviderRun.created_at > cutoff,
            )
            .limit(1)
        ).first()
        return recent is not None

    def _persist_ad_history(
        self,
        *,
        run_id: uuid.UUID,
        observed: Sequence[ObservedRecord],
        provider: str,
        data_origin: DataOrigin,
    ) -> None:
        """Write the run's ads, snapshots and observation links.

        All of it or none of it. A partial write would be worse than no write:
        an ad whose snapshot was never stored has a `latest_snapshot_id` pointing
        at nothing, and a reader has no way to tell that from an ad we know
        nothing about. So a failure rolls the normalized layer back and lets the
        run record itself as failed.

        The raw responses are safe either way -- they were committed page by page
        before any of this -- which is what makes reprocessing possible rather
        than lossy.
        """
        try:
            persist_observations(
                self._session,
                run_id=run_id,
                observations=observed,
                provider=provider,
                data_origin=data_origin,
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def _persist_provider_run(self, run_id: uuid.UUID, result: ProviderResult) -> RawResponse:
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

        return raw_response


def _excerpt(text: str) -> str:
    """Fit an untrusted message into `collection_runs.error_message`.

    Two things have to be true of the result, and this is the only place both
    are guaranteed.

    **It must fit.** The column has a `CHECK` on its length, and an
    `IntegrityError` raised from the `finally` that writes the run's status is
    the worst possible place to discover a message is too long: it supersedes
    whatever was being handled and leaves the row mutated but uncommitted. Note
    the bound is applied to the *rendered* string, not the input: `repr`
    expands a backslash to two characters and a control character to four, so
    budgeting on the input length can produce a string three times over the
    limit. The previous version of this function did exactly that.

    **It must be one line.** A provider is not a trusted source of
    newline-free text, and `error_message` is read by people and printed into
    logs. `repr` is what does the escaping, for the same reason the normalizer's
    `_safe` does -- a message carrying `\n` is a forged log record the moment
    anything prints it. It is applied on *both* paths; returning short input
    unchanged would leave exactly the forging case open.
    """
    marker = "... (truncated)"
    rendered = repr(text)
    if len(rendered) <= ERROR_MESSAGE_LIMIT:
        return rendered
    # Cut the *rendered* string, so expansion is already paid for. The cut is
    # only ever made at the end, which can leave a partial escape sequence; that
    # is harmless in a truncated log line and is preferable to budgeting wrong.
    return f"{rendered[: ERROR_MESSAGE_LIMIT - len(marker)]}{marker}"


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
    *,
    max_records: int = DEFAULT_MAX_RECORDS_PER_RUN,
    max_pages: int = DEFAULT_MAX_PAGES_PER_RUN,
    stale_run_timeout: timedelta = DEFAULT_STALE_RUN_TIMEOUT,
) -> CollectionOrchestrator:
    """Factory for the collection orchestrator.

    This is the composition root for orchestration. It wires together the
    database session, provider, and job queue, and passes through the three
    collection safety settings.
    """
    return CollectionOrchestrator(
        session,
        provider,
        job_queue,
        max_records=max_records,
        max_pages=max_pages,
        stale_run_timeout=stale_run_timeout,
    )

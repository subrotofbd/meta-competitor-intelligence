"""Scheduling and running copy analysis: eligibility, dedupe, budget, persistence.

## The pipeline in one paragraph

A collection run offers us the snapshots it observed. We skip any whose
`copy_hash` is NULL (it predates S2.2 and cannot be traced, and `AGENTS.md`
section 7 requires every interpretation to name its words), skip any already
analysed at this `analysis_version` (**free** -- a duplicate costs nothing and
consumes no budget), stop once the per-run cap is spent, and enqueue the rest onto
the existing `jobs` queue. A worker claims a job, asks the provider, validates the
answer, and writes `ad_analysis` plus an `ai_jobs` call record in one
transaction.

## How the prompt reaches a provider

The protocol is one method taking a `CopyAnalysisRequest`, so the prompt cannot
be a second argument. It is therefore selected **by the request**, and the adapter
owns the wire format:

- no `corrective_error` -> `user_prompt(request)`
- a `corrective_error` -> `corrective_prompt(request, ...)`

Both live in `analysis_prompt`, so there is exactly one place prompts are written
and the decision of which one applies is a field on the input rather than a
branch scattered across adapters.

## Three rules that are load-bearing

**The budget counts analyses, and duplicates are free.** `ai_max_analyses_per_run`
is a cost guard, not a policy. A re-run over unchanged copy schedules nothing at
all, which is the single most important cost property in this module: without it,
every collection would re-bill every ad it had ever seen.

**Reaching the cap is not a failure.** No exception, no failed run, no error
recorded. The ads simply have not been analysed yet, and the next run picks them
up. Turning a budget into an error would teach an operator that a working
collection had broken.

**A call that did not produce a validated analysis produces no analysis.** Not a
partial row, not a fallback template, not the mock's fourteen nulls.
`ad_analysis` is written on exactly one path: a `CopyAnalysis` that Pydantic
accepted.

## Where the retry boundary is

`AGENTS.md` section 10 permits **one** corrective retry, and it is spent here, in
the handler, on an answer this schema cannot hold. The outer `jobs` retry
mechanism is untouched and still decides what to do with a retryable failure
afterwards. The two are different things and are counted separately: the
corrective retry writes a second `ai_jobs` row against the same job, while a job
retry writes more rows still. Worst case, one analysis costs ten provider calls,
which is accepted and recorded rather than optimised away.

## Concurrency is the database's job

The dedupe check and the enqueue are not atomic -- `PostgresJobQueue` opens its
own session and commits, so it cannot join ours -- and that race is accepted.
`UNIQUE(copy_hash, analysis_version)` absorbs it: a second worker that inserts the
same analysis does nothing, and no caller sees an error. Building a transaction
spanning both would mean bypassing the `JobQueue` Protocol, which is the seam
this project keeps replaceable.

## Nothing here can fabricate

No field is filled from a default, no absent value is replaced with a
placeholder, and no token or cost figure is computed. `ai_jobs` stores what the
provider reported or NULL. The provider never touches the database: it returns an
`AIResult` and this module persists it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.ads import AdSnapshot
from app.models.analysis import AdAnalysis, AIJob, AIJobCallKind, AIJobStatus
from app.providers.ai.base import AIProvider
from app.providers.ai.errors import AIError, InvalidResponse
from app.providers.ai.models import AIResult, CopyAnalysis, CopyAnalysisRequest
from app.services.analysis_prompt import (
    AI_ANALYSIS_JOB_KIND,
    ANALYSIS_VERSION,
    PROMPT_VERSION,
)
from app.services.jobs import JobQueue, JobRequest

#: The corrective retry budget. One, written down as a constant because it is a
#: rule rather than a tuning knob, and a tuning knob would get raised.
MAX_CORRECTIVE_RETRIES: int = 1

#: Ceiling on a provider's error text before it reaches `ai_jobs.error_message`.
#: Matches the `jobs` bound so an operator reading both tables reads one limit.
#: A provider's error body can quote back what it was sent, so it is truncated
#: rather than stored whole, and a prompt is never put in it at all.
MAX_ERROR_MESSAGE_CHARS: int = 2_000


@dataclass(frozen=True, slots=True)
class SchedulingReport:
    """What one scheduling pass decided.

    Attributes:
        scheduled: Job ids enqueued by this pass.
        skipped_duplicate: Already analysed at this version. Cost nothing, and
            consumed no budget.
        skipped_no_copy_hash: `copy_hash` is NULL; not analysable in S3.1.
        skipped_budget: The per-run cap was already spent.
    """

    scheduled: tuple[str, ...]
    skipped_duplicate: int
    skipped_no_copy_hash: int
    skipped_budget: int

    @property
    def considered(self) -> int:
        """Snapshots this pass looked at, whatever it decided about them."""
        return (
            len(self.scheduled)
            + self.skipped_duplicate
            + self.skipped_no_copy_hash
            + self.skipped_budget
        )


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    """What one job's provider calls produced.

    Attributes:
        analysis_id: The stored analysis, or `None` when nothing was stored --
            which happens when both calls failed validation, or when another
            worker had already analysed this copy.
        wrote_analysis: Whether this call created the row. `False` with an
            `analysis_id` means a concurrent worker won the race, which is a
            success and not an error.
        attempts: How many provider calls were made.
    """

    analysis_id: uuid.UUID | None
    wrote_analysis: bool
    attempts: int


def build_request(snapshot: AdSnapshot, *, country: str | None = None) -> CopyAnalysisRequest:
    """The exact payload handed to a provider, read out of one snapshot.

    `ad_snapshots.normalized` is the append-only evidence, so this is a read of
    what was observed rather than a reconstruction of it. The four copy fields
    stay **separate**: "Free shipping" as a headline and as body text are two
    different signals, and concatenating them would lose that -- which is also
    why `ARCHITECTURE.md`'s "all cards' text joined with markers" describes a
    capability that does not exist (only `bodies[0]` is ever read).

    `destination_url` is present in the JSON and deliberately **not** forwarded.
    `copy_hash` already covers it, so two ads with identical words but different
    landing pages still analyse separately, but the URL itself never reaches a
    model: one less untrusted string, and nothing for a model to reason about a
    link it cannot visit.

    `language_hint` is never set. It is documented as an operator's guess, and
    S3.1 has no operator input; guessing a language from the text would be
    inventing a field. The model reports `language` itself.
    """
    normalized = snapshot.normalized if isinstance(snapshot.normalized, dict) else {}

    def _text(key: str) -> str | None:
        value = normalized.get(key)
        return value if isinstance(value, str) else None

    return CopyAnalysisRequest(
        copy_hash=snapshot.copy_hash or "",
        analysis_version=ANALYSIS_VERSION,
        primary_text=_text("primary_text"),
        headline=_text("headline"),
        description=_text("description"),
        cta=_text("cta"),
        language_hint=None,
        country=country,
    )


def find_existing(session: Session, copy_hash: str, analysis_version: str) -> uuid.UUID | None:
    """The id of an analysis already stored for this copy at this version.

    One query. An earlier draft ran it twice and short-circuited on the first,
    which is the kind of thing that reads as an optimisation and behaves as a
    race.
    """
    return session.execute(
        select(AdAnalysis.id).where(
            AdAnalysis.copy_hash == copy_hash,
            AdAnalysis.analysis_version == analysis_version,
        )
    ).scalar_one_or_none()


def _already_analysed(session: Session, copy_hash: str, analysis_version: str) -> bool:
    """Whether this copy is already analysed at this version.

    A named seam around `find_existing` because the pre-insert check and the
    post-conflict lookup are **not** the same thing. The first is an optimisation
    that avoids a paid call; the second is correctness -- it must find the winning
    row after the conflict arm fires. Sharing one function let a test stub the
    optimisation away and take the lookup with it, which is exactly the kind of
    coupling that hides a bug until it is expensive.
    """
    return find_existing(session, copy_hash, analysis_version) is not None


def _job_request(*, snapshot_id: uuid.UUID, copy_hash: str, analysis_version: str) -> JobRequest:
    """The queued unit of work: ids and versions, and nothing else.

    Never the copy itself and never anything from settings. `jobs.payload` is a
    stored column, the snapshot already holds the copy one join away, and a
    credential has no business being written to a queue row.
    """
    return JobRequest(
        kind=AI_ANALYSIS_JOB_KIND,
        payload={
            "ad_snapshot_id": str(snapshot_id),
            "copy_hash": copy_hash,
            "analysis_version": analysis_version,
        },
    )


def schedule_for_run(
    session: Session,
    job_queue: JobQueue,
    *,
    snapshots: tuple[AdSnapshot, ...],
    max_analyses: int,
    analysis_version: str = ANALYSIS_VERSION,
    country: str | None = None,
) -> SchedulingReport:
    """Offer one collection run's snapshots for analysis.

    Args:
        session: The caller's session, used only for reads. The queue commits on
            its own, which is why the dedupe race below is accepted rather than
            closed.
        job_queue: The existing queue. No second queue is created.
        snapshots: Snapshots the run observed. Order is the caller's.
        max_analyses: The per-run budget, counting analyses this pass schedules.
        analysis_version: The analysis contract to schedule under.
        country: Market context, when known.

    Returns:
        What was scheduled and what was skipped, and why. Reaching the budget is
        reported, not raised -- it is a budget, not a failure.
    """
    scheduled: list[str] = []
    duplicate = no_hash = over_budget = 0

    for snapshot in snapshots:
        copy_hash = snapshot.copy_hash
        if not copy_hash:
            # Predates S2.2, or was written by something that computed no digest.
            # `AGENTS.md` section 7 requires an interpretation to name the copy it
            # came from, and there is nothing here to name.
            no_hash += 1
            continue

        # Free. A duplicate costs no tokens, so it must not consume budget, or a
        # re-run over unchanged copy would spend the whole cap finding nothing.
        if find_existing(session, copy_hash, analysis_version) is not None:
            duplicate += 1
            continue

        if len(scheduled) >= max_analyses:
            over_budget += 1
            continue

        scheduled.append(
            job_queue.enqueue(
                _job_request(
                    snapshot_id=snapshot.id,
                    copy_hash=copy_hash,
                    analysis_version=analysis_version,
                )
            )
        )

    return SchedulingReport(
        scheduled=tuple(scheduled),
        skipped_duplicate=duplicate,
        skipped_no_copy_hash=no_hash,
        skipped_budget=over_budget,
    )


def run_analysis_job(
    session: Session,
    provider: AIProvider,
    *,
    job_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    analysis_version: str = ANALYSIS_VERSION,
    configured_model: str | None = None,
    clock: datetime | None = None,
) -> AnalysisOutcome:
    """Do one claimed job: ask, validate, retry once, persist.

    Args:
        session: The caller's session. The analysis row and the call record share
            its transaction, so a failure between them stores neither.
        provider: An `AIProvider`. It never touches the database; it returns an
            `AIResult` and this module persists it.
        job_id: The queue row, for the `ai_jobs` attempt records.
        snapshot_id: The snapshot whose copy is analysed.
        analysis_version: The contract to produce.
        configured_model: Model name from settings, recorded on both rows.
        clock: Injected for a deterministic `duration_ms` in tests.

    Returns:
        What was stored.

    Raises:
        InvalidResponse: Both attempts produced something this schema cannot
            hold. Nothing is stored in `ad_analysis`.
        AIError: Whatever the provider raised, unchanged and unretried here.
    """
    snapshot = session.get(AdSnapshot, snapshot_id)
    if snapshot is None:
        raise InvalidResponse(
            f"analysis job {job_id} names a snapshot that does not exist",
            provider=getattr(provider, "name", "unknown"),
        )

    copy_hash = snapshot.copy_hash or ""
    started = clock or datetime.now(UTC)

    # Re-checked here, not only at scheduling. Another worker may have analysed
    # this copy in between; re-checking turns that race into a cheap no-op
    # instead of a paid call. The unique constraint still backs it up -- this is an
    # optimisation, not the guarantee, which is why it has its own name.
    if _already_analysed(session, copy_hash, analysis_version):
        return AnalysisOutcome(analysis_id=None, wrote_analysis=False, attempts=0)

    base_request = build_request(snapshot)
    last_error: str | None = None

    for attempt_no in range(1, MAX_CORRECTIVE_RETRIES + 2):
        is_retry = attempt_no > 1
        call_kind = AIJobCallKind.INVALID_JSON_RETRY if is_retry else AIJobCallKind.INITIAL

        try:
            result = provider.analyze_copy(
                base_request if not is_retry else _with_correction(base_request, last_error)
            )
        except AIError as error:
            # A provider that *raises* still made a call, and that call still cost
            # something. Recording it is the entire reason `ai_jobs` exists: a
            # failure with no row is a failure nobody can account for. The error
            # is re-raised unchanged, so `retryable` still decides what the outer
            # `jobs` mechanism does with it.
            _record_attempt(
                session,
                job_id=job_id,
                attempt_no=attempt_no,
                call_kind=call_kind,
                copy_hash=copy_hash,
                analysis_version=analysis_version,
                provider=error.provider,
                model=configured_model,
                status=AIJobStatus.FAILED,
                error_type=type(error).__name__,
                error_message=error.message,
                started_at=started,
            )
            raise

        failure = _validation_failure(result)

        if failure is not None:
            last_error = failure.detail or failure.message
            _record_attempt(
                session,
                job_id=job_id,
                attempt_no=attempt_no,
                call_kind=call_kind,
                copy_hash=copy_hash,
                analysis_version=analysis_version,
                provider=result.provider,
                model=result.model,
                status=AIJobStatus.INVALID_RESPONSE,
                # Usage is recorded even though the answer was unusable. The model
                # was billed for those tokens whether or not we could use the
                # reply, and discarding the figure would make `ai_jobs` understate
                # what S3.1 actually spent -- which is the one number it exists to
                # state accurately.
                prompt_tokens=None if result.usage is None else result.usage.prompt_tokens,
                completion_tokens=None if result.usage is None else result.usage.completion_tokens,
                total_tokens=None if result.usage is None else result.usage.total_tokens,
                error_type=type(failure).__name__,
                error_message=failure.message,
                started_at=started,
            )
            if is_retry:
                # Budget spent. The attempt is recorded, `ad_analysis` is not
                # written, and the outer `jobs` mechanism decides whether to try
                # the whole job again. No fabricated analysis, ever.
                raise InvalidResponse(
                    "model returned an unusable answer after the single permitted retry",
                    provider=result.provider,
                    detail=last_error,
                ) from failure
            continue

        _record_attempt(
            session,
            job_id=job_id,
            attempt_no=attempt_no,
            call_kind=call_kind,
            copy_hash=copy_hash,
            analysis_version=analysis_version,
            provider=result.provider,
            model=result.model,
            status=AIJobStatus.SUCCEEDED,
            prompt_tokens=None if result.usage is None else result.usage.prompt_tokens,
            completion_tokens=None if result.usage is None else result.usage.completion_tokens,
            total_tokens=None if result.usage is None else result.usage.total_tokens,
            started_at=started,
        )
        analysis_id = _store_analysis(
            session,
            snapshot=snapshot,
            copy_hash=copy_hash,
            analysis_version=analysis_version,
            result=result,
            configured_model=configured_model,
        )
        return AnalysisOutcome(analysis_id=analysis_id, wrote_analysis=True, attempts=attempt_no)

    raise AssertionError("unreachable: the final iteration either returns or raises")


def _with_correction(
    request: CopyAnalysisRequest, validation_error: str | None
) -> CopyAnalysisRequest:
    """The request that asks for the one corrective retry.

    Carries the specific failure rather than "try again", because the single
    permitted retry is the only chance to fix it and "try again" reliably
    produces the same answer.

    The error text comes from Pydantic, which names fields and value *types* and
    does not quote the offending input, so it cannot carry the competitor's copy
    back to the provider. That is asserted by a test rather than assumed.
    """
    return request.model_copy(
        update={"corrective_error": validation_error or "the answer did not match the schema"}
    )


def _validation_failure(result: AIResult) -> InvalidResponse | None:
    """Refuse anything this schema cannot hold, or return `None`.

    The `AIResult` contract already holds a validated `CopyAnalysis`, so this
    normally passes. It exists as a seam rather than as ceremony: the mock and
    every future adapter go through it, so an adapter that returns a different
    shape cannot skip validation by being convenient.
    """
    if not isinstance(result.analysis, CopyAnalysis):
        return InvalidResponse(
            "provider returned something that is not a CopyAnalysis",
            provider=result.provider,
            detail=f"got {type(result.analysis).__name__}",
        )
    return None


def _record_attempt(
    session: Session,
    *,
    job_id: uuid.UUID,
    attempt_no: int,
    call_kind: str,
    copy_hash: str,
    analysis_version: str,
    provider: str,
    model: str | None,
    status: str,
    started_at: datetime,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Write one provider call's record.

    **No cost is written here.** The provider contract returns usage, not price,
    and S3.1 has no documented pricing table -- so `cost_amount`, `cost_currency`
    and `cost_method` stay NULL, which is the honest answer rather than a gap. A
    future checkpoint with a real price fills all three together, because the
    all-or-nothing CHECK refuses any two of them.

    `ON CONFLICT DO NOTHING` on `(job_id, attempt_no)`: a reprocessed job
    re-states a call rather than adding a second row for it.
    """
    finished = datetime.now(UTC)
    started = started_at if started_at.tzinfo is not None else started_at.replace(tzinfo=UTC)
    session.execute(
        insert(AIJob)
        .values(
            job_id=job_id,
            attempt_no=attempt_no,
            call_kind=call_kind,
            copy_hash=copy_hash,
            analysis_version=analysis_version,
            provider=provider,
            model=model,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            error_type=error_type,
            error_message=(
                error_message[:MAX_ERROR_MESSAGE_CHARS] if error_message is not None else None
            ),
            started_at=started,
            finished_at=finished,
            duration_ms=max(0, int((finished - started).total_seconds() * 1000)),
        )
        .on_conflict_do_nothing(constraint="uq_ai_jobs_job_attempt")
    )
    session.flush()


def _store_analysis(
    session: Session,
    *,
    snapshot: AdSnapshot,
    copy_hash: str,
    analysis_version: str,
    result: AIResult,
    configured_model: str | None,
) -> uuid.UUID:
    """Insert the validated analysis, losing a race harmlessly.

    `ON CONFLICT DO NOTHING` on `(copy_hash, analysis_version)`: a second worker
    that got here first keeps its row, and this one returns the winner's id rather
    than raising. Two paid calls for one analysis is the cost of losing a race;
    two stored interpretations of one copy would be a correctness failure.
    """
    analysis = result.analysis
    statement = (
        insert(AdAnalysis)
        .values(
            copy_hash=copy_hash,
            analysis_version=analysis_version,
            source_ad_id=snapshot.ad_id,
            source_ad_snapshot_id=snapshot.id,
            hook=analysis.hook,
            problem=analysis.problem,
            promise=analysis.promise,
            offer=analysis.offer,
            cta=analysis.cta,
            persona=analysis.persona,
            pain_point=analysis.pain_point,
            angle=analysis.angle,
            proof=analysis.proof,
            urgency=analysis.urgency,
            awareness_level=analysis.awareness_level,
            funnel_stage=analysis.funnel_stage,
            copy_structure=analysis.copy_structure,
            why_it_may_work=analysis.why_it_may_work,
            language=analysis.language,
            confidence=None if analysis.confidence is None else analysis.confidence.value,
            provider=result.provider,
            model=result.model if result.model is not None else configured_model,
            prompt_version=PROMPT_VERSION,
        )
        .on_conflict_do_nothing(constraint="uq_ad_analysis_copy_version")
        .returning(AdAnalysis.id)
    )
    session.flush()
    stored = session.execute(statement).scalar_one_or_none()
    if stored is not None:
        return stored

    # `RETURNING` yields nothing when the conflict arm fired, so another worker
    # inserted first. Its row is the analysis either way.
    existing = find_existing(session, copy_hash, analysis_version)
    if existing is None:  # pragma: no cover - unreachable while the constraint holds
        raise InvalidResponse(
            "analysis insert neither stored a row nor found a conflicting one",
            provider=result.provider,
        )
    return existing


__all__ = [
    "AI_ANALYSIS_JOB_KIND",
    "ANALYSIS_VERSION",
    "MAX_CORRECTIVE_RETRIES",
    "MAX_ERROR_MESSAGE_CHARS",
    "PROMPT_VERSION",
    "AIError",
    "AnalysisOutcome",
    "SchedulingReport",
    "build_request",
    "find_existing",
    "run_analysis_job",
    "schedule_for_run",
]

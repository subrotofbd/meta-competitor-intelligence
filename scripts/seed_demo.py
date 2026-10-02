"""Populate a safe, deterministic local demo dataset.

    uv run python scripts/seed_demo.py

Read-only against anything that is not the local development database, and
explicitly refused in production. Nothing here runs on import and nothing here runs
during application startup: the whole file is function bodies plus a `main()` behind
an `if __name__ == "__main__"` guard.

## Why this drives the real collection path

The tempting shortcut is to insert `Ad` and `AdSnapshot` rows directly and call it
demo data. That produces rows the product could never have produced: hashes nobody
computed, no `raw_responses` audit trail, no `provider_runs`, no status context, no
media links. It also quietly teaches the wrong lesson -- that a snapshot is a row you
insert.

So this script creates only two things itself, both of which are operator
configuration rather than collected data: a `Competitor` and a `FacebookPage`. Every
ad row is produced by `CollectionOrchestrator.execute_collection_job`, which is the
same entry point `python -m worker` calls. That path writes `collection_runs`,
`provider_runs`, `raw_responses` (with the trigger-computed `payload_hash`), `ads`,
`ad_snapshots` with real `content_hash` / `copy_hash` / `creative_hash`,
`seen_in_run`, `ad_status_by_context` via the S2.3 status evaluator, and
`media_assets` + `ad_snapshot_media`. None of that logic is duplicated here -- if it
were, this script would become a second implementation that drifts from the first.

The job is scheduled through the real `JobQueue` and claimed through the real
`queue.claim()`, exactly as the worker does, so the job-to-run linkage stays owned by
the queue rather than being reverse-engineered here.

## The corpus is provider-shaped, and that is the point

`build_mock_pages()` serves the sanitized corpus in
`backend/tests/fixtures/ad_provider/corpus.json`: three invented brands, `.invalid`
hostnames reserved by RFC 2606 so a fixture can never resolve to anything real, and
Hindi/Hinglish ad copy. Feeding that *through the production collection path* is what
turns provider-shaped fixtures into genuinely API-shaped rows. The alternative --
hand-authoring an `AdListItemOut` for the frontend -- would test the frontend against
a fiction that the backend never agreed to produce.

Every ad record in the corpus carries its own `targeted_countries`, and they span
**four** countries -- `IN`, `GB`, `IE` and `US` -- with only 6 of the 9 ads including
`IN` and two of the three pages not targeting it at all. The demo pages are therefore
created with country `IN` because the corpus *includes* `IN`, not because every ad
claims it.

That distinction is the product's, not the script's, and it is preserved rather than
smoothed over: `MockProvider.fetch_page_ads` ignores the requested country and serves
the batch, so `ad_status_by_context.country` records **the scope of the run that
observed the ad** (`IN`), while each ad's own `targeted_countries` stays in
`normalized` exactly as the provider reported it. An ad that targets only `GB` will
carry an `IN` context because that is where we saw it. Both facts are stored; neither
is derived from the other.

## Rerunning is safe, and it is the append-only design doing the work

`execute_collection_job` is called again, creating a second genuine collection run --
which is real history and exactly what a second run would do. Because
`persist_observations` dedupes on `content_hash`, an unchanged ad writes **no new
snapshot**, only a `seen_in_run` link. So rerunning cannot fabricate observation
history, and this script never deletes or resets anything to achieve that.

## What this deliberately does not do

**No `--with-ai` flag.** This was originally an *obstacle*, not a choice: the stored
mock analyses were keyed `mock-copy-hash-en-001` and friends, which
`ad_analysis.copy_hash`'s `CHECK (copy_hash ~ '^[0-9a-f]{64}$')` can never accept, so
`MockAIProvider` missed on every real digest and returned its all-null analysis --
writing rows that read as "analysed" and say nothing.

**S3.3 step 3 removed that obstacle**: `tests/fixtures/ai/analyses.json` is now keyed by
real digests computed with production `copy_hash_v1`, and 3 of the 8 seeded ads resolve
a stored analysis. The flag is still absent because adding it is a scope decision that
has not been authorised, not because the data is not ready.

**No invented performance data.** There is no spend, impressions, reach, clicks,
leads, conversions, CPM, revenue or ROAS column in this schema, so none can be
written -- the guarantee is structural rather than a matter of discipline. No verdict
is stored either: `duration` and the long-running signal are computed at read time
from stored timestamps by the existing `services/ad_duration` code.
"""

from __future__ import annotations

import argparse
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from app.composition import (
    build_collection_orchestrator,
    build_job_queue,
    build_mock_pages,
)
from app.core.config import AppEnv, Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import session_scope
from app.models.runs import CollectionRun, CollectionRunStatus
from app.models.tracking import Competitor, FacebookPage
from app.services.collection import COLLECTION_JOB_KIND

logger = logging.getLogger("seed_demo")

#: The competitor every demo page belongs to. One competitor, three Pages: the
#: directory then shows a nested shape rather than three unrelated entries, which is
#: the thing the S3.3 frontend has to render.
DEMO_COMPETITOR_NAME: Final = "Aurora Kitchen Studio (demo)"

#: The country the demo pages are collected under. It is read by
#: `schedule_collection` into `collection_runs.country` and from there into
#: `ad_status_by_context.country`, so it scopes *our observation* rather than
#: describing the ad. `IN` because the corpus includes it, not because every ad
#: claims it -- see the module docstring.
DEMO_COUNTRY: Final = "IN"

#: `tracking_frequency` is free text with no closed vocabulary. This value exists only
#: to satisfy `NOT NULL` and is never scheduled from by this script.
DEMO_TRACKING_FREQUENCY: Final = "manual"

#: The lease holder this script claims jobs under. Distinct from the worker's id so a
#: concurrent real worker cannot be mistaken for this one in `jobs.worker_id`.
SEED_WORKER_ID: Final = "seed-demo"

#: Jobs claimed per drain round. Deliberately small: the queue hands out work
#: oldest-first, so a batch is mostly foreign jobs on a shared development database,
#: and every one this script claims is leased by it until the lease expires. Draining
#: in small batches and stopping as soon as the demo's own job appears leases less than
#: asking for one large batch.
_CLAIM_LIMIT: Final = 5

#: How many rounds to drain before giving up. Bounded so a queue that keeps producing
#: foreign work cannot spin this script forever.
_MAX_DRAIN_ROUNDS: Final = 50

#: A run in one of these states has already been decided; executing it again is a no-op
#: that would report zero records and read as "the provider served nothing".
_TERMINAL_RUN_STATUSES: Final = frozenset(
    {
        CollectionRunStatus.COMPLETE,
        CollectionRunStatus.PARTIAL,
        CollectionRunStatus.FAILED,
    }
)


class SeedRefused(RuntimeError):
    """The seed was refused rather than attempted.

    Raised, not printed and continued, so a caller cannot accidentally treat a
    refusal as a successful run.
    """


@dataclass(frozen=True, slots=True)
class SeedReport:
    """What the seed did. Returned rather than printed from inside, so tests can
    assert on it without capturing stdout."""

    competitor_id: uuid.UUID
    page_ids: tuple[uuid.UUID, ...]
    run_ids: tuple[uuid.UUID, ...]
    ads_seen: int


# ============================================================
# Safety
# ============================================================


def refuse_in_production(settings: Settings) -> None:
    """Refuse to seed anything but a local database.

    This is the only guard between "a developer wanted demo data" and "a demo
    competitor was written into the record of a real business". It reads the same
    `app_env` the rest of the application trusts, and it runs before a single
    connection is opened.

    Raises:
        SeedRefused: `app_env` is `prod`.
    """
    if settings.app_env is AppEnv.PROD:
        raise SeedRefused(
            "refusing to seed demo data with APP_ENV=prod; this script writes rows "
            "to whatever database DATABASE_URL points at"
        )


# ============================================================
# Operator configuration -- the only rows written directly
# ============================================================


def _ensure_competitor(session: Session, name: str) -> Competitor:
    """The demo competitor, created once and reused thereafter.

    `Competitor.name` is deliberately **not** unique in the schema, so this matches by
    name and inserts only when nothing matches -- it does not lean on a constraint
    that does not exist, and it does not create a second demo competitor on a rerun.
    """
    existing = session.query(Competitor).filter(Competitor.name == name).one_or_none()
    if existing is not None:
        return existing
    row = Competitor(name=name)
    session.add(row)
    session.flush()
    return row


def _ensure_page(
    session: Session,
    *,
    competitor_id: uuid.UUID,
    provider_page_id: str,
    page_name: str | None,
    url: str | None,
) -> FacebookPage:
    """One demo Page per corpus entry, matched on the provider's own id.

    `facebook_pages.page_id` is globally unique, so this is the one lookup that can
    rely on a real constraint. Matching on `page_id` rather than the internal id is
    also what makes the script idempotent across a database that already has the page
    attached to some other competitor.
    """
    existing = (
        session.query(FacebookPage).filter(FacebookPage.page_id == provider_page_id).one_or_none()
    )
    if existing is not None:
        return existing
    row = FacebookPage(
        competitor_id=competitor_id,
        page_id=provider_page_id,
        name=page_name,
        url=url,
        country=DEMO_COUNTRY,
        tracking_frequency=DEMO_TRACKING_FREQUENCY,
        is_tracked=True,
    )
    session.add(row)
    session.flush()
    return row


# ============================================================
# Collection, through the production path
# ============================================================


def _run_id_of(job_payload: dict[str, object]) -> uuid.UUID:
    """The run a claimed job points at.

    The job's payload owns this linkage, and the worker reads it the same way
    (`worker/__main__.py::_execute_job`). Re-deriving it from a query here would be a
    second implementation of the same rule.
    """
    raw = job_payload.get("collection_run_id")
    if not raw:
        raise SeedRefused(f"claimed job has no collection_run_id: {job_payload!r}")
    return uuid.UUID(str(raw))


def _collect_page(page_id: uuid.UUID) -> tuple[uuid.UUID, int]:
    """Schedule one collection run for a Page and execute it.

    The sequence is the worker's: schedule, claim, read the run id out of the payload,
    execute, complete. Claiming rather than reading the run out of the database is
    deliberate -- it keeps the job-to-run linkage owned by the queue rather than
    reverse-engineered here, and it means a job this script did not schedule is
    *detected* instead of silently executed.

    **Foreign jobs are skipped, never touched.** The queue hands out work oldest-first,
    so a development database with pending jobs from elsewhere yields those first. They
    are left leased and untouched: this script will not execute, complete or fail
    somebody else's work, and the lease expires on its own. Only the run belonging to
    `page_id` is executed. So it claims in small batches and keeps draining until it
    finds its own, rather than asking for one huge batch and leasing the whole queue.

    Returns:
        The collection run id, and how many ad records it read.

    Raises:
        SeedRefused: No collection job for this page became claimable.
    """
    orchestrator, session = build_collection_orchestrator()
    queue = build_job_queue()

    orchestrator.schedule_collection(page_id)

    for _ in range(_MAX_DRAIN_ROUNDS):
        claimed = queue.claim(limit=_CLAIM_LIMIT, worker_id=SEED_WORKER_ID)
        if not claimed:
            break
        for job in claimed:
            if job.kind != COLLECTION_JOB_KIND:
                logger.debug("skipping job %s of kind %r", job.job_id, job.kind)
                continue
            try:
                run_id = _run_id_of(job.payload)
            except (ValueError, KeyError):
                # A payload that is not a run id. Left leased, not failed: this
                # script does not know what the job was for.
                logger.warning("skipping job %s: unusable payload %r", job.job_id, job.payload)
                continue
            run = session.get(CollectionRun, run_id)
            if run is None:
                logger.warning(
                    "skipping job %s: collection run %s no longer exists", job.job_id, run_id
                )
                continue
            if run.facebook_page_id != page_id:
                logger.debug("skipping job %s: run %s is not the demo page", job.job_id, run_id)
                continue
            if run.status in _TERMINAL_RUN_STATUSES:
                # `schedule_collection` is idempotent: if a PENDING or RUNNING run
                # already exists for this page it returns a `run-<id>` marker and
                # enqueues **nothing**. Draining the queue can therefore surface the
                # job of an earlier, already-finished run. Executing that is a no-op
                # that reports zero records, which would look exactly like a provider
                # that served nothing -- so terminal runs are skipped and the drain
                # continues.
                logger.debug(
                    "skipping job %s: run %s is already %s", job.job_id, run_id, run.status
                )
                continue

            outcome = orchestrator.execute_collection_job(run_id)
            queue.complete(job.job_id)
            return run_id, len(outcome.records)

    raise SeedRefused(
        f"no claimable collection job appeared for demo page {page_id}; the queue may "
        f"hold work this script must not touch, or a worker may hold the lease"
    )


# ============================================================
# Entry points
# ============================================================


def seed(*, settings: Settings | None = None) -> SeedReport:
    """Populate the demo dataset. Idempotent; safe to call repeatedly.

    Args:
        settings: Injected by tests. Defaults to the process settings.

    Returns:
        What was created or reused.

    Raises:
        SeedRefused: `app_env` is `prod`, or the queue yielded foreign work.
    """
    effective = settings or get_settings()
    refuse_in_production(effective)

    corpus = build_mock_pages()
    if not corpus:
        raise SeedRefused("the mock corpus is empty; there is nothing to seed")

    run_ids: list[uuid.UUID] = []
    ads_seen = 0

    # Two phases, and the order is not cosmetic. The competitor and Pages are written
    # and **committed** first, because collection opens its own session and cannot see
    # rows that are still in an uncommitted transaction -- scheduling a run for a page
    # that does not exist yet is not something the orchestrator can do.
    with session_scope() as session:
        competitor = _ensure_competitor(session, DEMO_COMPETITOR_NAME)
        page_ids = [
            _ensure_page(
                session,
                competitor_id=competitor.id,
                provider_page_id=provider_page_id,
                page_name=corpus[provider_page_id].page.page_name,
                url=str(corpus[provider_page_id].page.url)
                if corpus[provider_page_id].page.url
                else None,
            ).id
            for provider_page_id in sorted(corpus)
        ]

    for page_id in page_ids:
        run_id, count = _collect_page(page_id)
        run_ids.append(run_id)
        ads_seen += count

    logger.info(
        "seeded competitor %s with %d page(s); %d run(s) read %d ad record(s)",
        competitor.id,
        len(page_ids),
        len(run_ids),
        ads_seen,
    )
    return SeedReport(
        competitor_id=competitor.id,
        page_ids=tuple(page_ids),
        run_ids=tuple(run_ids),
        ads_seen=ads_seen,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the seed from the command line.

    Deliberately tiny. `--with-ai` is absent on purpose: see the module docstring for
    why invoking the analysis path today would write interpretations that say
    nothing.
    """
    parser = argparse.ArgumentParser(
        prog="seed_demo",
        description="Populate the local demo dataset through the real collection path.",
    )
    parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings)
    try:
        report = seed(settings=settings)
    except SeedRefused as refusal:
        # A refusal is a refusal, not a traceback: the user did nothing wrong and
        # should not be shown a stack for being told no.
        logger.error("seed refused: %s", refusal)
        return 1

    # Logged rather than printed, like `scripts/check_db.py`: one output channel for
    # the whole repository, in whatever shape `app.core.logging` configured. A script
    # that prints would bypass the structured handler this project relies on.
    logger.info(
        "seeded competitor=%s pages=%d runs=%d ad_records=%d",
        report.competitor_id,
        len(report.page_ids),
        len(report.run_ids),
        report.ads_seen,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - the process entrypoint
    raise SystemExit(main())

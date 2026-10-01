"""Deciding what we concluded about an ad, per Page + country context.

## The only thing this module is allowed to conclude from

The evidence chain, which S2.1 built and which this module never writes:

    raw_responses -> ad_snapshots -> seen_in_run -> collection_runs -> page/country

`ad_status_by_context` is a **projection** of that chain. Every value here can be
deleted and rebuilt, which is what makes it safe to update while `ad_snapshots` is
append-only and is not.

## The rules, and the mistakes each one prevents

**Only COMPLETE runs count.** `_resolve_outcome` in `services/collection.py`
already distinguishes `complete` from `partial` -- a walk that stopped early, or
that could not read a record, is `partial`. `AGENTS.md` section 8 forbids marking
an ad inactive after "a failed or partial run", and the way that is honoured here
is by filtering those runs out of the walk entirely. They are **invisible**: they
neither advance a streak nor reset one, so two complete runs either side of a
provider outage are still consecutive complete runs. A provider being down must
never make an ad look inactive.

**A complete run with zero ads is real evidence.** If the walk finished cleanly and
served nothing, then for every ad in that context the ad was genuinely absent from
that observation. Refusing to count it would mean an outage that returned an empty
page could never be distinguished from an outage that returned nothing at all.

**Streaks never cross a context boundary.** `ARCHITECTURE.md` defines the rule
per Page/country, and an ad present on page A says nothing about page B. Every
query here is scoped to one `(facebook_page_id, country)`, and the unique
constraint on that triple is what makes crossing impossible rather than merely
discouraged.

**Absence is a presumption, not a verdict.** `presumed_inactive` is named that way
because two consecutive absences is evidence, not proof: an ad can be delisted and
relisted, or simply missed. Recovery is therefore a normal transition, and
`not_seen_since` is emphatically not "stopped" (`AGENTS.md` section 8).

**A provider's words and our conclusion never merge.** `provider_active` is the
provider's assertion, normalised from a frozen token table; `current_status` is
ours. An absent run **clears** `provider_active` to `NULL`, because carrying a
stale `True` across a run in which the provider said nothing would assert evidence
that does not exist.

## Idempotence

`last_status_run_id` guards every write. An evaluation whose run is older than the
one already recorded is discarded, so a retried job or a replayed run cannot walk
a streak backwards -- which would be the one way this module could resurrect a
`presumed_inactive` that a newer run legitimately set.

## Where the boundary is drawn

This module reads evidence and writes one projection table. It does not touch
`ads`, does not touch `ad_snapshots`, does not create snapshots, and decides
nothing about ad *content*: a status change is not a content change, so it must
never move `content_hash` or `latest_snapshot_id` (`AGENTS.md` section 8, and the
S2.1 invariant that a snapshot is written only when `content_hash` differs).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.ad_status import (
    STATUS_NOT_SEEN_SINCE,
    STATUS_PRESUMED_INACTIVE,
    STATUS_SEEN,
    AdStatusByContext,
)
from app.models.ads import SeenInRun
from app.models.runs import CollectionRun, CollectionRunStatus

#: How many consecutive complete absences are required before an ad is presumed
#: inactive. **Fixed, and not configurable.** `AGENTS.md` section 8 states N = 2;
#: `ARCHITECTURE.md` called it a configurable default of 2, and that discrepancy
#: was settled in favour of the constant. Making it a setting would let a value
#: chosen to make a report look better, which is precisely the kind of tuning this
#: history exists to prevent.
INACTIVE_AFTER_MISSES: Final = 2

#: The provider's own vocabulary, and nothing else.
#:
#: Matched case-insensitively after stripping surrounding whitespace, and matched
#: **whole** -- never by substring or fuzzy comparison. A feed that said
#: "inactive_pending_review" is not a fact about this product, and reading it as
#: one would turn an unrecognised string into a status nobody reported.
#:
#: Anything not named here is `None`. That includes "paused", "deleted",
#: "withheld", and every future wording the provider invents: unrecognised is not
#: false, and the raw string is preserved untouched on `ad_snapshots.ad_status` so
#: nothing is lost by not understanding it here.
_PROVIDER_ACTIVE_TOKENS: Final[frozenset[str]] = frozenset({"active"})
_PROVIDER_INACTIVE_TOKENS: Final[frozenset[str]] = frozenset({"inactive"})


def provider_active_from(ad_status: str | None) -> bool | None:
    """The provider's explicit assertion, normalised, or `None`.

    Args:
        ad_status: The provider's raw wording exactly as stored on
            `ad_snapshots.ad_status`, or `None` when the provider reported no
            status at all.

    Returns:
        `True` for a recognised "active", `False` for a recognised "inactive", and
        `None` for anything else -- unknown wording, an empty string, or no status
        reported. **`None` is never rounded to `False`**: a provider that said
        nothing has made no assertion, and recording "not active" from silence
        would invent a finding.
    """
    if ad_status is None:
        return None
    token = ad_status.strip().lower()
    if token in _PROVIDER_ACTIVE_TOKENS:
        return True
    if token in _PROVIDER_INACTIVE_TOKENS:
        return False
    return None


@dataclass(frozen=True, slots=True)
class _RecentRun:
    """One complete run in the context, and whether it observed this ad.

    Built by a single query rather than one per candidate run: the streak walk is
    bounded, but a query per run would turn one evaluation into a round trip per
    absence.
    """

    run_id: uuid.UUID
    finished_at: datetime
    observed: bool


def evaluate_run_status(session: Session, run_id: uuid.UUID) -> tuple[AdStatusByContext, ...]:
    """Fold one finished COMPLETE run into the status of its context.

    Args:
        session: The caller's session. **The caller commits.**
        run_id: The run whose completion is being evaluated.

    Returns:
        The rows this evaluation created or advanced, newest evaluation first.

    Only a COMPLETE run has any effect. A FAILED or PARTIAL run returns an empty
    tuple and writes nothing at all -- not the status, not the provider assertion,
    not the absence boundary, not the idempotence marker. That is the whole point
    of the check, and it is why it is the first thing that happens.
    """
    run = session.get(CollectionRun, run_id)
    if run is None:
        raise ValueError(f"CollectionRun {run_id} not found")
    if run.status is not CollectionRunStatus.COMPLETE:
        return ()

    context = (run.facebook_page_id, run.country)

    rows = _rows_for_context(session, *context)
    touched: list[AdStatusByContext] = []

    for row in rows:
        # An older or replayed run must never rewind a conclusion a newer run
        # already established. Without this, reprocessing an old run would walk the
        # streak backwards and could clear a `presumed_inactive` that a later run
        # legitimately set.
        if not _is_newer_evaluation(row, run, session):
            continue

        recent = _current_recent_runs(
            session, ad_id=row.ad_id, page_id=context[0], country=context[1]
        )
        observed_here = any(
            candidate.run_id == run.id and candidate.observed for candidate in recent
        )

        if observed_here:
            _mark_seen(session, row, run)
        else:
            _advance_absence(session, row, run, recent)
        touched.append(row)

    return tuple(touched)


def _rows_for_context(
    session: Session, page_id: uuid.UUID, country: str
) -> list[AdStatusByContext]:
    """Every status row for one Page + country, oldest run evaluation last.

    Read first, because a complete run with **zero ads** is still evidence of
    absence for every ad in that context -- an evaluation that started from the
    run's own sightings would silently skip exactly the case that matters most.
    """
    return list(
        session.execute(
            select(AdStatusByContext).where(
                AdStatusByContext.facebook_page_id == page_id,
                AdStatusByContext.country == country,
            )
        ).scalars()
    )


def _is_newer_evaluation(row: AdStatusByContext, run: CollectionRun, session: Session) -> bool:
    """Whether `run` is a newer evaluation than the one already recorded.

    A row that has never been evaluated is always eligible. Otherwise the recorded
    run's `finished_at` decides, because two runs finishing in the same instant
    are not ordered by anything we store.
    """
    if row.last_status_run_id is None:
        return True
    recorded = session.get(CollectionRun, row.last_status_run_id)
    if recorded is None or recorded.finished_at is None or run.finished_at is None:
        return True
    return run.finished_at >= recorded.finished_at


def _current_recent_runs(
    session: Session, *, ad_id: uuid.UUID, page_id: uuid.UUID, country: str
) -> tuple[_RecentRun, ...]:
    """The most recent complete runs for this context, newest first, with a flag
    for whether each observed this ad.

    One query, because `EXISTS` beats a second round trip per run and the walk
    below is bounded. `seen_in_run` is the evidence; `ad_snapshots` is deliberately
    not consulted here, because it records observations across every context and
    cannot say which run in *this* context saw the ad.
    """
    observed = (
        select(func.count())
        .select_from(SeenInRun)
        .where(
            SeenInRun.collection_run_id == CollectionRun.id,
            SeenInRun.ad_id == ad_id,
        )
        .scalar_subquery()
    )
    rows = session.execute(
        select(CollectionRun.id, CollectionRun.finished_at, (observed > 0).label("observed"))
        .where(
            CollectionRun.facebook_page_id == page_id,
            CollectionRun.country == country,
            # The rule that keeps a provider outage from marking ads inactive.
            # FAILED and PARTIAL runs are not merely discounted here -- they are
            # invisible, so they can neither advance nor reset a streak.
            CollectionRun.status == CollectionRunStatus.COMPLETE,
            CollectionRun.finished_at.is_not(None),
        )
        .order_by(CollectionRun.finished_at.desc())
        # Bounded. Far more than N=2 needs: the walk normally stops at the run
        # that observed the ad, but an ad absent for a long time has no such run to
        # stop at, and an unbounded walk would read the whole run history per ad.
        .limit(_RECENT_RUN_WINDOW)
    ).all()

    return tuple(
        _RecentRun(run_id=row.id, finished_at=row.finished_at, observed=bool(row.observed))
        for row in rows
        if row.finished_at is not None
    )


#: How many complete runs back the absence walk looks. Only the first
#: `INACTIVE_AFTER_MISSES` matter; the rest is headroom for the common case where
#: the ad was observed recently and the walk stops almost immediately.
_RECENT_RUN_WINDOW: Final = 10


def _mark_seen(session: Session, row: AdStatusByContext, run: CollectionRun) -> None:
    """The ad was observed in this complete run: it is `seen`.

    `not_seen_since_at` is cleared because there is no absence to report. This is
    also the recovery path: an ad reappearing after `presumed_inactive` returns to
    `seen`, which is a normal transition and not an error. Absence was a
    presumption and a presumption that stops holding is simply dropped.
    """
    row.current_status = STATUS_SEEN
    row.not_seen_since_at = None
    row.last_status_run_id = run.id


def _advance_absence(
    session: Session,
    row: AdStatusByContext,
    run: CollectionRun,
    recent: tuple[_RecentRun, ...],
) -> None:
    """The ad was absent from this complete run. Count, and conclude.

    The streak counts *consecutive complete runs after the last one that observed
    the ad*, scanning `recent` newest-first and stopping at the first observation.
    Everything between that observation and now was an absence.

    `provider_active` is cleared to `None`: the provider made no assertion about
    this ad in this run, and carrying a previous `True` forward would claim
    provider evidence that no longer exists.
    """
    misses = 0
    last_observed_at: datetime | None = None

    for candidate in recent:
        if candidate.observed:
            last_observed_at = candidate.finished_at
            break
        misses += 1
        if misses >= INACTIVE_AFTER_MISSES:
            break

    if misses >= INACTIVE_AFTER_MISSES:
        row.current_status = STATUS_PRESUMED_INACTIVE
    else:
        row.current_status = STATUS_NOT_SEEN_SINCE

    # The boundary stays where it was: the last complete run that actually saw
    # this ad. Rewriting it to "now" on every absence would turn a date the user
    # reads into a clock that restarts, and would lose the only fact that says
    # *since when*.
    row.not_seen_since_at = last_observed_at or row.not_seen_since_at
    row.provider_active = None
    row.last_status_run_id = run.id


def record_observation(
    session: Session,
    *,
    ad_id: uuid.UUID,
    page_id: uuid.UUID,
    country: str,
    provider_active: bool | None,
    last_status_run_id: uuid.UUID,
) -> AdStatusByContext:
    """Create or update the status row for one ad observed in one run.

    Called for every sighting, so this is the path that establishes `seen` and
    carries the provider's assertion forward. Upserted rather than selected and
    inserted: two workers finishing overlapping runs would otherwise both miss the
    select and one would fail on the unique constraint, which is a worse outcome
    than either winning.

    A sighting always wins over an absence evaluation for the same run, because a
    sighting *is* the observation and an absence is only its absence.
    """
    statement = (
        insert(AdStatusByContext)
        .values(
            ad_id=ad_id,
            facebook_page_id=page_id,
            country=country,
            current_status=STATUS_SEEN,
            provider_active=provider_active,
            not_seen_since_at=None,
            last_status_run_id=last_status_run_id,
        )
        .on_conflict_do_update(
            constraint="uq_ad_status_by_context_ad_page_country",
            set_={
                "current_status": STATUS_SEEN,
                "provider_active": provider_active,
                # Cleared: there is no absence to report while the ad is being
                # observed. This is what lets an ad recover from
                # `presumed_inactive`.
                "not_seen_since_at": None,
                "last_status_run_id": last_status_run_id,
                "updated_at": func.now(),
            },
        )
        .returning(AdStatusByContext)
    )
    row: AdStatusByContext = session.execute(statement).scalar_one()
    return row

"""The status state machine, proven against PostgreSQL 16.

Every claim here is about which runs count and what the evaluator concludes from
them, and none of it is observable without a real database: a `WHERE status =
'complete'` filter, a `DISTINCT`, an upsert, and a partial index. A fake session
could show that a statement was issued; only a server can show that a FAILED run
was invisible to the streak.

    docker compose up -d
    uv run pytest backend/tests/test_status_evaluator.py -q

Writes are real and nothing is committed -- `db_session` binds every session to a
connection inside an outer transaction that is always rolled back.

## The mistakes these tests exist to catch

1. A FAILED or PARTIAL run advancing an absence streak. **A provider outage must
   never make an ad look inactive.**
2. Two contexts sharing a streak, so an ad seen on page A is judged absent
   because of page B.
3. `presumed_inactive` after one absence instead of two.
4. A stale `provider_active` carried across a run in which the provider said
   nothing.
5. A replayed older run rewinding a conclusion a newer run established.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ad_status import (
    STATUS_NOT_SEEN_SINCE,
    STATUS_PRESUMED_INACTIVE,
    STATUS_SEEN,
    AdStatusByContext,
)
from app.models.ads import Ad, AdSnapshot, SeenInRun
from app.models.runs import (
    CollectionRun,
    CollectionRunStatus,
    ProviderRun,
    ProviderRunStatus,
    RawResponse,
)
from app.providers.data.provenance import DataOrigin
from app.services.status_evaluator import evaluate_run_status, record_observation

pytestmark = pytest.mark.integration

BASE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
PROVIDER = "mock"


# ============================================================
# Building a context
# ============================================================


def _ad(session: Session, meta_ad_id: str = "ad-0001") -> Ad:
    """A real `ads` row. `ad_status_by_context.ad_id` holds a `RESTRICT` foreign
    key to it, so a test using a dangling UUID would be asserting about a row the
    database had already refused."""
    row = Ad(
        provider=PROVIDER,
        meta_ad_id=meta_ad_id,
        data_origin=DataOrigin.third_party,
        first_seen_at=BASE - timedelta(days=1),
        last_seen_at=BASE - timedelta(days=1),
    )
    session.add(row)
    session.flush()
    return row


def _run(
    session: Session,
    *,
    page_id: uuid.UUID,
    country: str = "IN",
    status: CollectionRunStatus = CollectionRunStatus.COMPLETE,
    finished_at: datetime | None = None,
) -> CollectionRun:
    """A `collection_runs` row.

    `finished_at` defaults to `BASE` so a sequence of runs built in order has
    increasing finish times, which is what the absence walk orders by.
    """
    row = CollectionRun(
        facebook_page_id=page_id,
        provider=PROVIDER,
        country=country,
        data_origin=DataOrigin.third_party,
        status=status,
        started_at=finished_at or BASE,
        finished_at=finished_at,
        records_returned=0,
    )
    session.add(row)
    session.flush()
    return row


def _sighting(session: Session, *, ad: Ad, run: CollectionRun) -> SeenInRun:
    """The evidence that a run observed an ad: a `seen_in_run` link row.

    `ad_status_by_context` is a projection of these links, so a test that skipped
    this would be evaluating against nothing. A real snapshot is built because
    `seen_in_run.snapshot_id` is a `RESTRICT` foreign key to `ad_snapshots` -- the
    link cannot exist without the observation it points at, which is the same
    traceability guarantee S2.1 built.
    """
    response = _response(session, run)
    snapshot = AdSnapshot(
        ad_id=ad.id,
        collection_run_id=run.id,
        raw_ref=response.id,
        content_hash="0" * 64,
        normalized={"external_ad_id": ad.meta_ad_id},
    )
    session.add(snapshot)
    session.flush()

    row = SeenInRun(ad_id=ad.id, collection_run_id=run.id, snapshot_id=snapshot.id)
    session.add(row)
    session.flush()
    return row


def _status(
    session: Session, *, ad: Ad, page_id: uuid.UUID, country: str = "IN"
) -> AdStatusByContext | None:
    """The one status row for a context, or `None` if it does not exist yet."""
    return session.execute(
        select(AdStatusByContext).where(
            AdStatusByContext.ad_id == ad.id,
            AdStatusByContext.facebook_page_id == page_id,
            AdStatusByContext.country == country,
        )
    ).scalar_one_or_none()


def _the_status(
    session: Session, *, ad: Ad, page_id: uuid.UUID, country: str = "IN"
) -> AdStatusByContext:
    """The status row for a context, which must exist.

    Every caller here has already established a sighting, so a missing row is a
    bug rather than a state worth asserting about -- and routing them through one
    helper means a missing row fails with a clear message instead of an
    `AttributeError` on `None` several lines later.
    """
    row = _status(session, ad=ad, page_id=page_id, country=country)
    assert row is not None, f"no status row for ad={ad.meta_ad_id} page={page_id} country={country}"
    return row


def _response(session: Session, run: CollectionRun) -> RawResponse:
    """A provider call and its raw response, so a snapshot can cite a source."""
    call = ProviderRun(
        collection_run_id=run.id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=run.started_at or BASE,
        finished_at=run.finished_at,
        request_meta={
            "provider": PROVIDER,
            "origin": DataOrigin.third_party.value,
            "country": run.country,
            "requested_at": (run.started_at or BASE).isoformat(),
            "cursor": None,
        },
        http_status=200,
    )
    session.add(call)
    session.flush()
    response = RawResponse(provider_run_id=call.id, payload={"ads": []})
    session.add(response)
    session.flush()
    return response


def _page(session: Session, page_id: str) -> uuid.UUID:
    """A `facebook_pages` row. `page_id` is globally unique, so two tests cannot
    share one."""
    from app.models.tracking import Competitor, FacebookPage

    competitor = Competitor(name=f"Acme {page_id[-3:]}")
    session.add(competitor)
    session.flush()
    page = FacebookPage(
        competitor_id=competitor.id,
        page_id=page_id,
        name="Acme India",
        url="https://www.facebook.com/acme",
        country="IN",
        tracking_frequency="daily",
        is_tracked=True,
    )
    session.add(page)
    session.flush()
    return page.id


# ============================================================
# The first observation
# ============================================================


def test_a_first_qualifying_observation_is_seen(db_session: Session) -> None:
    """A sighting establishes the status for its context.

    `record_observation` is the path a real collection run takes, because
    `ad_persistence._persist_one` calls it for every sighting.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000301")
    run = _run(db_session, page_id=page_id)

    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=run.id,
    )
    db_session.flush()

    row = _status(db_session, ad=ad, page_id=page_id)
    assert row is not None
    assert row.current_status == STATUS_SEEN
    assert row.not_seen_since_at is None
    assert row.provider_active is True
    assert row.last_status_run_id == run.id


def test_one_status_row_exists_per_ad_page_country_context(db_session: Session) -> None:
    """The uniqueness that makes an ambiguous status impossible."""
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000302")
    run = _run(db_session, page_id=page_id)

    for _ in range(2):
        record_observation(
            db_session,
            ad_id=ad.id,
            page_id=page_id,
            country="IN",
            provider_active=None,
            last_status_run_id=run.id,
        )
    db_session.flush()

    count = db_session.execute(
        text(
            "SELECT count(1) FROM ad_status_by_context "
            "WHERE ad_id = :ad AND facebook_page_id = :page"
        ),
        {"ad": ad.id, "page": page_id},
    ).scalar_one()
    assert count == 1, "an upsert created a second row for one context"


# ============================================================
# Context isolation -- B1
# ============================================================


def test_another_pages_sighting_does_not_end_this_pages_absence_streak(
    db_session: Session,
) -> None:
    """The context boundary, from the direction that actually discriminates.

    The other two-page tests would pass even if the streak walk ignored the page
    entirely, because a shared observation sits at the same depth in both walks
    and both reach the same conclusion. This one interleaves the pages so that
    leaking a context **changes the answer**:

        t0  page B  observes the ad
        t1  page B  absent          -> streak 1
        t2  page A  observes the ad  <- a different page entirely
        t3  page B  absent          -> streak 2 -> presumed_inactive

    If the walk did not filter by page, the observation at t2 would stop the walk
    and page B would read `not_seen_since` instead -- understating an absence by a
    whole cycle, and doing it for every ad on every page.
    """
    ad = _ad(db_session)
    page_a = _page(db_session, "100000000000327")
    page_b = _page(db_session, "100000000000328")

    b0 = _run(db_session, page_id=page_b, finished_at=BASE)
    _sighting(db_session, ad=ad, run=b0)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_b,
        country="IN",
        provider_active=None,
        last_status_run_id=b0.id,
    )

    b1 = _run(db_session, page_id=page_b, finished_at=BASE + timedelta(days=1))
    evaluate_run_status(db_session, b1.id)

    # A different page observes the ad while page B does not.
    a2 = _run(db_session, page_id=page_a, finished_at=BASE + timedelta(days=2))
    _sighting(db_session, ad=ad, run=a2)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_a,
        country="IN",
        provider_active=None,
        last_status_run_id=a2.id,
    )

    b3 = _run(db_session, page_id=page_b, finished_at=BASE + timedelta(days=3))
    evaluate_run_status(db_session, b3.id)
    db_session.flush()

    on_b = _status(db_session, ad=ad, page_id=page_b)
    assert on_b is not None
    assert on_b.current_status == STATUS_PRESUMED_INACTIVE, (
        "another page's sighting ended this page's absence streak"
    )
    # And page A is unaffected by page B's absences.
    assert _the_status(db_session, ad=ad, page_id=page_a).current_status == STATUS_SEEN


def test_one_ad_on_two_pages_has_two_independent_statuses(db_session: Session) -> None:
    """The property that forced a new table.

    One ad, present on page A and absent from page B. Both are true at once, so
    the rows must not be summed, OR-ed, or collapsed into one answer.
    """
    ad = _ad(db_session)
    page_a = _page(db_session, "100000000000303")
    page_b = _page(db_session, "100000000000304")

    first = _run(db_session, page_id=page_a, finished_at=BASE)
    _sighting(db_session, ad=ad, run=first)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_a,
        country="IN",
        provider_active=True,
        last_status_run_id=first.id,
    )

    # Page B sees it once, establishing a status row, then misses it twice.
    b_seen = _run(db_session, page_id=page_b, finished_at=BASE)
    _sighting(db_session, ad=ad, run=b_seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_b,
        country="IN",
        provider_active=True,
        last_status_run_id=b_seen.id,
    )
    for offset in (1, 2):
        absent = _run(db_session, page_id=page_b, finished_at=BASE + timedelta(days=offset))
        evaluate_run_status(db_session, absent.id)
    db_session.flush()

    on_a = _status(db_session, ad=ad, page_id=page_a)
    on_b = _status(db_session, ad=ad, page_id=page_b)

    assert on_a is not None and on_a.current_status == STATUS_SEEN
    assert on_b is not None and on_b.current_status == STATUS_PRESUMED_INACTIVE


def test_one_ad_in_two_countries_has_two_independent_statuses(db_session: Session) -> None:
    """Country is half the context, exactly as Page is.

    A run is per Page *and* country (`collection_runs` carries both), so the same
    page collected for two countries is two observation contexts.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000305")

    india = _run(db_session, page_id=page_id, country="IN", finished_at=BASE)
    _sighting(db_session, ad=ad, run=india)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=india.id,
    )

    abroad = _run(db_session, page_id=page_id, country="US", finished_at=BASE)
    _sighting(db_session, ad=ad, run=abroad)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="US",
        provider_active=True,
        last_status_run_id=abroad.id,
    )
    for offset in (1, 2):
        evaluate_run_status(
            db_session,
            _run(
                db_session,
                page_id=page_id,
                country="US",
                finished_at=BASE + timedelta(days=offset),
            ).id,
        )
    db_session.flush()

    in_india = _status(db_session, ad=ad, page_id=page_id, country="IN")
    in_us = _status(db_session, ad=ad, page_id=page_id, country="US")

    assert in_india is not None and in_india.current_status == STATUS_SEEN
    assert in_us is not None and in_us.current_status == STATUS_PRESUMED_INACTIVE


# ============================================================
# The absence streak
# ============================================================


def test_one_complete_absence_is_not_seen_since_and_not_yet_inactive(
    db_session: Session,
) -> None:
    """N is 2, so a single absence must not presume anything."""
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000306")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )

    absent = _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=1))
    evaluate_run_status(db_session, absent.id)
    db_session.flush()

    row = _status(db_session, ad=ad, page_id=page_id)
    assert row is not None
    assert row.current_status == STATUS_NOT_SEEN_SINCE
    assert row.current_status != STATUS_PRESUMED_INACTIVE


def test_two_consecutive_complete_absences_are_presumed_inactive(
    db_session: Session,
) -> None:
    """The rule itself."""
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000307")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )
    for offset in (1, 2):
        evaluate_run_status(
            db_session,
            _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=offset)).id,
        )
    db_session.flush()

    row = _status(db_session, ad=ad, page_id=page_id)
    assert row is not None
    assert row.current_status == STATUS_PRESUMED_INACTIVE


def test_an_ad_reappearing_after_presumed_inactive_is_seen_again(
    db_session: Session,
) -> None:
    """Absence is a presumption, and recovery is a normal transition.

    An ad can be delisted and relisted, or simply missed. `AGENTS.md` section 8 is
    explicit that a missing ad is not evidence it stopped, so a status that could
    never be recovered would be a verdict rather than an observation.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000308")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )
    for offset in (1, 2):
        evaluate_run_status(
            db_session,
            _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=offset)).id,
        )

    back = _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=3))
    _sighting(db_session, ad=ad, run=back)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=False,
        last_status_run_id=back.id,
    )
    db_session.flush()

    row = _status(db_session, ad=ad, page_id=page_id)
    assert row is not None
    assert row.current_status == STATUS_SEEN
    assert row.not_seen_since_at is None


# ============================================================
# Failed and partial runs are invisible
# ============================================================


@pytest.mark.parametrize(
    "status",
    [CollectionRunStatus.FAILED, CollectionRunStatus.PARTIAL],
)
def test_a_non_complete_run_changes_nothing_at_all(
    db_session: Session, status: CollectionRunStatus
) -> None:
    """The safety rule, stated as a byte-level no-op.

    `AGENTS.md` section 8: a failed or partial run must never let an ad be
    presumed inactive. Every column is checked, because advancing `last_status_run_id`
    without advancing the streak would corrupt the idempotence guard.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000309")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )
    db_session.flush()
    before = _status(db_session, ad=ad, page_id=page_id)
    assert before is not None
    snapshot = (
        before.current_status,
        before.not_seen_since_at,
        before.provider_active,
        before.last_status_run_id,
    )

    for offset in (1, 2, 3):
        evaluate_run_status(
            db_session,
            _run(
                db_session,
                page_id=page_id,
                status=status,
                finished_at=BASE + timedelta(days=offset),
            ).id,
        )
    db_session.flush()

    after = _status(db_session, ad=ad, page_id=page_id)
    assert after is not None
    assert (
        after.current_status,
        after.not_seen_since_at,
        after.provider_active,
        after.last_status_run_id,
    ) == snapshot, f"{status} advanced the status"


def test_a_failed_run_between_two_complete_runs_does_not_break_the_streak(
    db_session: Session,
) -> None:
    """A failed run is skipped, not counted.

    Two complete absences either side of an outage are still *consecutive
    complete* absences. The alternative -- an outage resetting the counter --
    would mean a provider being down could keep every ad alive for ever.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000310")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )

    first_absent = _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=1))
    evaluate_run_status(db_session, first_absent.id)

    evaluate_run_status(
        db_session,
        _run(
            db_session,
            page_id=page_id,
            status=CollectionRunStatus.FAILED,
            finished_at=BASE + timedelta(days=2),
        ).id,
    )

    second_absent = _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=3))
    evaluate_run_status(db_session, second_absent.id)
    db_session.flush()

    row = _status(db_session, ad=ad, page_id=page_id)
    assert row is not None
    assert row.current_status == STATUS_PRESUMED_INACTIVE


def test_a_partial_run_between_two_complete_runs_does_not_break_the_streak(
    db_session: Session,
) -> None:
    """Same rule for a partial walk, which is the more common of the two.

    `_resolve_outcome` marks a run `partial` when any record failed to read, so a
    single malformed record is enough. If partial runs reset the streak, one bad
    record would keep an ad alive indefinitely.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000311")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )
    evaluate_run_status(
        db_session,
        _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=1)).id,
    )
    evaluate_run_status(
        db_session,
        _run(
            db_session,
            page_id=page_id,
            status=CollectionRunStatus.PARTIAL,
            finished_at=BASE + timedelta(days=2),
        ).id,
    )
    evaluate_run_status(
        db_session,
        _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=3)).id,
    )
    db_session.flush()

    row = _status(db_session, ad=ad, page_id=page_id)
    assert row is not None
    assert row.current_status == STATUS_PRESUMED_INACTIVE


# ============================================================
# A complete run with no ads
# ============================================================


def test_a_complete_run_with_zero_ads_advances_absence(db_session: Session) -> None:
    """An empty but clean walk is evidence of absence.

    If it did not count, a provider returning an empty page could never be
    distinguished from a provider returning nothing at all, and an ad that had
    genuinely been delisted would stay `seen` for ever.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000312")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )

    for offset in (1, 2):
        empty = _run(
            db_session,
            page_id=page_id,
            finished_at=BASE + timedelta(days=offset),
            status=CollectionRunStatus.COMPLETE,
        )
        assert empty.records_returned == 0
        evaluate_run_status(db_session, empty.id)
    db_session.flush()

    row = _status(db_session, ad=ad, page_id=page_id)
    assert row is not None
    assert row.current_status == STATUS_PRESUMED_INACTIVE


# ============================================================
# Provider evidence
# ============================================================


def test_an_absent_run_clears_a_stale_provider_active_to_null(db_session: Session) -> None:
    """A previous `True` must not outlive the run that carried it.

    Carrying it forward would assert provider evidence that no longer exists -- the
    provider said nothing in this run, and a reader would see "the provider says
    this is active" about a run in which it said nothing.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000313")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )

    absent = _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=1))
    evaluate_run_status(db_session, absent.id)
    db_session.flush()

    row = _status(db_session, ad=ad, page_id=page_id)
    assert row is not None
    assert row.provider_active is None, "a stale provider assertion survived an absence"
    assert row.current_status == STATUS_NOT_SEEN_SINCE


def test_a_provider_claim_never_overrides_the_derived_status(db_session: Session) -> None:
    """Two facts, two columns, and neither wins.

    A provider saying "active" does not make an ad seen, and saying "inactive"
    does not make it unseen. Both stay recorded; the derived status is decided by
    the run history alone.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000314")

    # Provider says active, but the run did not observe it.
    absent = _run(db_session, page_id=page_id, finished_at=BASE)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=absent.id,
    )
    evaluate_run_status(db_session, absent.id)

    # Provider says inactive, but the run did observe it.
    present = _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=1))
    _sighting(db_session, ad=ad, run=present)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=False,
        last_status_run_id=present.id,
    )
    db_session.flush()

    row = _status(db_session, ad=ad, page_id=page_id)
    assert row is not None
    assert row.current_status == STATUS_SEEN
    assert row.provider_active is False, "the provider's own claim was discarded"


def test_provider_active_is_isolated_per_context(db_session: Session) -> None:
    """One context's provider assertion does not leak into another's.

    Same ad, same instant, two pages: the provider said something on one and
    nothing on the other, and the two answers are about different observations.
    """
    ad = _ad(db_session)
    page_a = _page(db_session, "100000000000315")
    page_b = _page(db_session, "100000000000316")

    on_a = _run(db_session, page_id=page_a, finished_at=BASE)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_a,
        country="IN",
        provider_active=True,
        last_status_run_id=on_a.id,
    )
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_b,
        country="IN",
        provider_active=None,
        last_status_run_id=_run(db_session, page_id=page_b, finished_at=BASE).id,
    )
    db_session.flush()

    assert _the_status(db_session, ad=ad, page_id=page_a).provider_active is True
    assert _the_status(db_session, ad=ad, page_id=page_b).provider_active is None


# ============================================================
# not_seen_since_at
# ============================================================


def test_not_seen_since_is_the_last_run_that_actually_observed_the_ad(
    db_session: Session,
) -> None:
    """Our own server-side boundary, and it does not move while absence continues.

    Stamped from the observing run's `finished_at` rather than from "now", so the
    date a user reads is a fact about an observation and not a clock that
    restarts on every collection.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000317")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )

    boundaries = []
    for offset in (1, 2):
        evaluate_run_status(
            db_session,
            _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=offset)).id,
        )
        db_session.flush()
        boundaries.append(_the_status(db_session, ad=ad, page_id=page_id).not_seen_since_at)

    assert boundaries == [BASE, BASE], "the boundary moved while absence continued"
    assert boundaries[0] == seen.finished_at


def test_a_sighting_clears_the_absence_boundary(db_session: Session) -> None:
    """Reappearing means there is no absence to report."""
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000318")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=None,
        last_status_run_id=seen.id,
    )
    evaluate_run_status(
        db_session, _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=1)).id
    )
    db_session.flush()
    assert _the_status(db_session, ad=ad, page_id=page_id).not_seen_since_at == BASE

    back = _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=2))
    _sighting(db_session, ad=ad, run=back)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=None,
        last_status_run_id=back.id,
    )
    db_session.flush()

    assert _the_status(db_session, ad=ad, page_id=page_id).not_seen_since_at is None


# ============================================================
# Idempotence
# ============================================================


def test_a_replayed_older_run_cannot_rewind_a_newer_conclusion(db_session: Session) -> None:
    """`last_status_run_id` is the guard, and this is what it prevents.

    A retried job or a replayed run would otherwise walk the streak backwards
    over newer evidence and clear a `presumed_inactive` that a later run
    legitimately established -- which is the one way this module could make an
    inactive ad look active again.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000319")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=None,
        last_status_run_id=seen.id,
    )
    for offset in (1, 2):
        evaluate_run_status(
            db_session,
            _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=offset)).id,
        )
    db_session.flush()
    established = _the_status(db_session, ad=ad, page_id=page_id)
    assert established.current_status == STATUS_PRESUMED_INACTIVE

    # Replay the *first* run, long after the fact.
    evaluate_run_status(db_session, seen.id)
    db_session.flush()

    row = _the_status(db_session, ad=ad, page_id=page_id)
    assert row.current_status == STATUS_PRESUMED_INACTIVE, "an old run rewound the status"
    assert row.last_status_run_id != seen.id
    db_session.flush()


def test_evaluating_the_same_run_twice_changes_nothing(db_session: Session) -> None:
    """Re-running an evaluation is a no-op, not a second absence."""
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000320")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=None,
        last_status_run_id=seen.id,
    )
    absent = _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=1))
    evaluate_run_status(db_session, absent.id)
    db_session.flush()

    evaluate_run_status(db_session, absent.id)
    evaluate_run_status(db_session, absent.id)
    db_session.flush()

    row = _the_status(db_session, ad=ad, page_id=page_id)
    assert row.current_status == STATUS_NOT_SEEN_SINCE, "one absence counted as two"


# ============================================================
# Invariants S2.3 must not break
# ============================================================


def test_status_evaluation_creates_no_snapshots(db_session: Session) -> None:
    """A status change is not a content change.

    `AGENTS.md` section 8: a snapshot is written only when `content_hash` differs,
    and `ad_status` is excluded from that digest. A module that reacted to status
    by writing a snapshot would manufacture a history of changes that never
    occurred.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000321")

    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=True,
        last_status_run_id=seen.id,
    )
    # Counted *after* the sighting, so this measures what evaluation itself writes
    # rather than the fixture's own snapshot.
    before = db_session.execute(text("SELECT count(1) FROM ad_snapshots")).scalar_one()

    for offset in (1, 2):
        evaluate_run_status(
            db_session,
            _run(db_session, page_id=page_id, finished_at=BASE + timedelta(days=offset)).id,
        )
    db_session.flush()

    after = db_session.execute(text("SELECT count(1) FROM ad_snapshots")).scalar_one()
    assert after == before, "status evaluation wrote an ad_snapshots row"


def test_status_evaluation_never_writes_ad_snapshots_even_to_update(db_session: Session) -> None:
    """The append-only trigger is still armed after S2.3.

    The projection table is updatable by design; the evidence table is not. This
    asserts the guard is still installed rather than trusting that nothing tried.
    """
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000322")
    seen = _run(db_session, page_id=page_id, finished_at=BASE)
    link = _sighting(db_session, ad=ad, run=seen)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=None,
        last_status_run_id=seen.id,
    )
    db_session.flush()

    # A *real* snapshot id: an UPDATE matching no row would raise nothing, and the
    # test would pass without the trigger ever firing.
    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text("UPDATE ad_snapshots SET ad_status = 'tampered' WHERE id = :id"),
            {"id": link.snapshot_id},
        )
    assert "append-only" in str(caught.value)
    db_session.rollback()


def test_ads_gained_no_status_column(db_session: Session) -> None:
    """Status lives in the context table, and `ads` is untouched.

    Adding a page foreign key or a global status to `ads` would undo the S2.1
    decision that an ad is not owned by a page, so the absence is asserted rather
    than assumed.
    """
    columns = {
        str(row[0])
        for row in db_session.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'ads'")
        )
    }

    assert "current_status" not in columns
    assert "provider_active" not in columns
    assert "not_seen_since_at" not in columns
    assert "facebook_page_id" not in columns
    assert "country" not in columns


# ============================================================
# Constraints
# ============================================================


def test_the_status_vocabulary_is_enforced_by_the_database(db_session: Session) -> None:
    """A frozen `CHECK`, so an unrecognised status cannot reach a report."""
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000323")

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                "INSERT INTO ad_status_by_context (id, ad_id, facebook_page_id, country, "
                "current_status) VALUES (:id, :ad, :page, 'IN', 'probably_fine')"
            ),
            {"id": uuid.uuid4(), "ad": ad.id, "page": page_id},
        )
    assert "current_status_vocabulary" in str(caught.value)
    db_session.rollback()


def test_the_database_refuses_a_second_row_for_one_context(db_session: Session) -> None:
    """Two contradictory conclusions about one observation cannot coexist."""
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000324")
    run = _run(db_session, page_id=page_id)
    record_observation(
        db_session,
        ad_id=ad.id,
        page_id=page_id,
        country="IN",
        provider_active=None,
        last_status_run_id=run.id,
    )
    db_session.flush()

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                "INSERT INTO ad_status_by_context (id, ad_id, facebook_page_id, country, "
                "current_status) VALUES (:id, :ad, :page, 'IN', 'seen')"
            ),
            {"id": uuid.uuid4(), "ad": ad.id, "page": page_id},
        )
    assert "uq_ad_status_by_context_ad_page_country" in str(caught.value)
    db_session.rollback()


def test_the_database_refuses_a_lowercase_country(db_session: Session) -> None:
    """A lowercase `in` and an uppercase `IN` would silently split one context in
    two, so the check is the same one `collection_runs` uses."""
    ad = _ad(db_session)
    page_id = _page(db_session, "100000000000325")

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                "INSERT INTO ad_status_by_context (id, ad_id, facebook_page_id, country, "
                "current_status) VALUES (:id, :ad, :page, 'in', 'seen')"
            ),
            {"id": uuid.uuid4(), "ad": ad.id, "page": page_id},
        )
    assert "country_iso_alpha2" in str(caught.value)
    db_session.rollback()

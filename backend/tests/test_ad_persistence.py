"""Turning normalized records into ad history, proven against PostgreSQL 16.

`app/services/ad_persistence.py` is where three questions are answered -- is this
the same ad, has it changed, which run saw it -- and the answers are written
permanently. A commercial ad that stops running is gone from Meta for good
(`DATA_ACCESS.md`), so the row this module decides to write, or not write, is
often the only copy of that observation that will ever exist.

That is why this file is `integration` and not `unit`. Every claim here is about
what a *database* did: an upsert resolving, a `UNIQUE` firing, a trigger refusing
an update, two `now()` calls agreeing by construction. A fake session can prove
the service issued a statement; only a real server can prove the statement did
what the docstring says.

    docker compose up -d
    uv run pytest backend/tests/test_ad_persistence.py -q

Writes are real and nothing is committed. The `db_session` fixture in
`conftest.py` binds every session to a connection inside an outer transaction
that is always rolled back, so there is no cleanup `DELETE` to get wrong and no
path by which a failing test can leave rows behind.

## What is deliberately not here

No test decides whether an ad is active, or whether its absence from a run means
anything. `provider_active` / `not_seen_since` / `presumed_inactive` is S2.3's
state machine, and `AGENTS.md` section 8 makes it depend on N *consecutive
complete* runs. A test written here would be a test of S2.3's rules, in S2.1,
where nothing computes a status.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Ad,
    AdSnapshot,
    CollectionRun,
    CollectionRunStatus,
    Competitor,
    FacebookPage,
    ProviderRun,
    ProviderRunStatus,
    RawResponse,
    SeenInRun,
)
from app.providers.data.models import AdFormat, MediaRef, RawAdRecord
from app.providers.data.provenance import DataOrigin
from app.services.ad_persistence import ObservedRecord, persist_observations
from app.services.content_hash import content_hash_v1

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
PROVIDER = "mock"


# ============================================================
# A valid chain to hang observations off
# ============================================================


def _chain(session: Session) -> tuple[CollectionRun, RawResponse]:
    """A flushed competitor -> page -> run -> call -> response.

    Every row here is a parent of the next and none of it is the thing under
    test, so the flushes are unconditional. A second raw response is worth
    having: a snapshot cites the response it was read from, so proving two
    snapshots of the same ad came from two different pages of a walk needs two
    sources to tell apart.
    """
    competitor = Competitor(name="Acme")
    session.add(competitor)
    session.flush()

    page = FacebookPage(
        competitor_id=competitor.id,
        page_id="100000000000001",
        name="Acme India",
        url="https://www.facebook.com/acme",
        country="IN",
        tracking_frequency="daily",
        is_tracked=True,
    )
    session.add(page)
    session.flush()

    run = CollectionRun(
        facebook_page_id=page.id,
        provider=PROVIDER,
        country="IN",
        data_origin=DataOrigin.third_party,
        status=CollectionRunStatus.COMPLETE,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=30),
    )
    session.add(run)
    session.flush()

    call = ProviderRun(
        collection_run_id=run.id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=2),
        request_meta={
            "provider": PROVIDER,
            "origin": DataOrigin.third_party.value,
            "country": "IN",
            "requested_at": NOW.isoformat(),
            "cursor": None,
        },
        http_status=200,
    )
    session.add(call)
    session.flush()

    response = RawResponse(provider_run_id=call.id, payload={"ads": []})
    session.add(response)
    session.flush()
    return run, response


def _another_run(session: Session, response: RawResponse) -> CollectionRun:
    """A second complete run for the same page, for the "later observation" cases.

    The whole point of the history model is comparison *across* runs, so a second
    run is the minimum a meaningful S2.1 test needs.
    """
    run = CollectionRun(
        facebook_page_id=response.provider_run.collection_run.facebook_page_id,
        provider=PROVIDER,
        country="IN",
        data_origin=DataOrigin.third_party,
        status=CollectionRunStatus.COMPLETE,
        started_at=NOW + timedelta(days=1),
        finished_at=NOW + timedelta(days=1, seconds=30),
    )
    session.add(run)
    session.flush()
    return run


def _record(**overrides: Any) -> RawAdRecord:
    fields: dict[str, Any] = {
        "external_ad_id": "ad-0001",
        "page_id": "100000000000001",
        "page_name": "Acme India",
        "platforms": ("facebook",),
        "countries": ("IN",),
        "ad_status": "active",
        "meta_delivery_start": datetime(2026, 1, 1, tzinfo=UTC),
        "primary_text": "Buy now",
        "headline": "Great offer",
        "cta": "SHOP_NOW",
        "destination_url": "https://example.invalid/offer",
        "display_format": AdFormat.IMAGE,
        "media": (MediaRef(provider_key="img-1"),),
    }
    fields.update(overrides)
    return RawAdRecord(**fields)


def _observed(record: RawAdRecord, response: RawResponse, **overrides: Any) -> ObservedRecord:
    fields: dict[str, Any] = {
        "record": record,
        "raw_response_id": response.id,
    }
    fields.update(overrides)
    return ObservedRecord(**fields)


def _persist(
    session: Session,
    run: CollectionRun,
    observations: list[ObservedRecord],
    *,
    provider: str = PROVIDER,
    data_origin: DataOrigin = DataOrigin.third_party,
) -> tuple[Any, ...]:
    """Write one run's observations, the way the orchestrator does.

    The commit is the caller's in production, so it is inlined here rather than
    hidden in a helper of its own -- the transaction boundary is part of what is
    under test.
    """
    results = persist_observations(
        session,
        run_id=run.id,
        observations=observations,
        provider=provider,
        data_origin=data_origin,
    )
    session.commit()
    return results


def _get[T](session: Session, model: type[T], key: uuid.UUID) -> T:
    """Fetch a row that must exist, and say so plainly if it does not.

    `Session.get` is typed `Model | None`, so every call site would otherwise
    need a `cast` or an `assert` purely to satisfy the checker. Routing them
    through one helper keeps the tests readable and turns a missing row into a
    clear failure message instead of an `AttributeError` on `None` several lines
    later -- which, in a test about what was written, is a much more useful
    place to find out.
    """
    row = session.get(model, key)
    assert row is not None, f"{getattr(model, '__tablename__', model)} {key} was not found"
    return row


def _count(session: Session, model: type[Any]) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


# ============================================================
# The first observation
# ============================================================


def test_a_first_observation_writes_one_ad_one_snapshot_and_one_link(
    db_session: Session,
) -> None:
    """The complete first pass, asserted on the rows rather than on the return value.

    All three tables or nothing: an ad whose snapshot was never stored would have
    a `latest_snapshot_id` pointing at nothing, and a reader could not tell that
    from an ad we know nothing about.
    """
    run, response = _chain(db_session)

    results = _persist(db_session, run, [_observed(_record(), response)])

    assert len(results) == 1
    assert _count(db_session, Ad) == 1
    assert _count(db_session, AdSnapshot) == 1
    assert _count(db_session, SeenInRun) == 1


def test_the_first_snapshot_is_linked_from_the_ad_and_cites_its_response(
    db_session: Session,
) -> None:
    """The two pointers, which are the whole audit trail.

    `ads.latest_snapshot_id` is how a reader finds the ad's current state;
    `ad_snapshots.raw_ref` is how a reader finds the evidence that state was read
    from. Asserted as values rather than as relationships, so a relationship that
    loads nothing cannot pass this.
    """
    run, response = _chain(db_session)

    result = _persist(db_session, run, [_observed(_record(), response)])[0]
    ad = _get(db_session, Ad, result.ad_id)
    snapshot = _get(db_session, AdSnapshot, result.snapshot_id)

    assert ad.latest_snapshot_id == snapshot.id
    assert snapshot.raw_ref == response.id
    assert snapshot.collection_run_id == run.id
    assert snapshot.ad_id == ad.id


def test_the_ad_records_the_providers_own_id_and_its_origin(
    db_session: Session,
) -> None:
    """Identity and provenance are stored once, on the row that owns them.

    `provider` and `meta_ad_id` are part of ad identity -- the same numeric id from
    two providers is two ads -- and `data_origin` answers how the values were
    obtained. `EvidenceClass` is absent by design: it is derived from the origin,
    and a stored copy could disagree with the derivation.
    """
    run, response = _chain(db_session)

    result = _persist(db_session, run, [_observed(_record(), response)])[0]
    ad = _get(db_session, Ad, result.ad_id)

    assert ad.provider == PROVIDER
    assert ad.meta_ad_id == "ad-0001"
    assert ad.data_origin is DataOrigin.third_party


def test_a_snapshot_stores_the_normalized_record_in_provider_order(
    db_session: Session,
) -> None:
    """What S1.3 read is stored as S1.3 read it.

    Provider order is preserved deliberately: this column is the evidence, and
    reordering it would make the stored reading disagree with what the provider
    said. `content_hash` is computed from the `RawAdRecord` rather than from this
    column precisely so that JSONB's key normalisation cannot move a digest.
    """
    run, response = _chain(db_session)
    record = _record(platforms=("instagram", "facebook"))

    result = _persist(db_session, run, [_observed(record, response)])[0]
    snapshot = _get(db_session, AdSnapshot, result.snapshot_id)

    assert snapshot.normalized["platforms"] == ["instagram", "facebook"]
    assert snapshot.content_hash == content_hash_v1(record)


def test_the_providers_own_words_are_stored_verbatim_on_the_snapshot(
    db_session: Session,
) -> None:
    """`ad_status` and `meta_delivery_start` are the provider's, untranslated.

    `ad_status` is not `provider_active` -- nothing derives a domain status until
    S2.3 -- and a provider that reports no status must not be given one. Both
    columns are nullable, and this asserts the values round-trip untouched.
    """
    run, response = _chain(db_session)

    result = _persist(db_session, run, [_observed(_record(ad_status="active"), response)])[0]
    snapshot = _get(db_session, AdSnapshot, result.snapshot_id)

    assert snapshot.ad_status == "active"
    assert snapshot.meta_delivery_start == datetime(2026, 1, 1, tzinfo=UTC)


def test_a_provider_reported_start_date_never_becomes_our_sighting_time(
    db_session: Session,
) -> None:
    """The specific error AGENTS.md section 8 names, proven against the database.

    The provider claims the ad began in January. We first saw it today. Those are
    two facts about two observers, and if the January date were allowed onto
    `first_seen_at` then "how long has this ad been running" would be answered
    from a provider's claim rather than from our own history.
    """
    run, response = _chain(db_session)
    long_ago = NOW - timedelta(days=300)

    result = _persist(
        db_session, run, [_observed(_record(meta_delivery_start=long_ago), response)]
    )[0]
    ad = _get(db_session, Ad, result.ad_id)
    snapshot = _get(db_session, AdSnapshot, result.snapshot_id)

    assert snapshot.meta_delivery_start == long_ago
    assert ad.first_seen_at > long_ago
    assert ad.first_seen_at.date() >= datetime.now(UTC).date() - timedelta(days=1)


def test_a_record_with_no_provider_status_or_start_date_is_storable(
    db_session: Session,
) -> None:
    """Absence is recorded as absence.

    `ad_status=None` and `meta_delivery_start=None` must round-trip as NULL
    rather than being filled with a plausible-looking substitute. A `CHECK` that
    rejected NULL would be a bug, and so would a default.
    """
    run, response = _chain(db_session)

    result = _persist(
        db_session,
        run,
        [_observed(_record(ad_status=None, meta_delivery_start=None), response)],
    )[0]
    snapshot = _get(db_session, AdSnapshot, result.snapshot_id)

    assert snapshot.ad_status is None
    assert snapshot.meta_delivery_start is None


# ============================================================
# Sighting times
# ============================================================


def test_the_sighting_times_are_ours_and_equal_the_observation_row(
    db_session: Session,
) -> None:
    """`first_seen_at`, `last_seen_at` and `seen_in_run.created_at` agree by
    construction, not by two clocks happening to be close.

    All three are stamped from the same `now()` in the same transaction, and
    PostgreSQL's `now()` is the *transaction* timestamp. So "when we first saw
    this ad" and "when the run recorded that sighting" cannot disagree -- which is
    a stronger property than them being approximately equal, and the reason the
    values are read from the database rather than from Python.
    """
    run, response = _chain(db_session)

    result = _persist(db_session, run, [_observed(_record(), response)])[0]
    ad = _get(db_session, Ad, result.ad_id)
    link = db_session.execute(select(SeenInRun).where(SeenInRun.ad_id == ad.id)).scalar_one()

    assert ad.first_seen_at == ad.last_seen_at
    assert ad.first_seen_at == link.created_at


def test_the_sighting_times_are_not_the_providers_delivery_date(
    db_session: Session,
) -> None:
    """A second reading of the same rule, from the other side.

    The first test shows the times agree with each other; this shows they do not
    come from the provider. Without it, a service that set both from
    `meta_delivery_start` would pass the equality test and fail the product's
    actual requirement.
    """
    run, response = _chain(db_session)
    provider_date = NOW - timedelta(days=90)

    result = _persist(
        db_session, run, [_observed(_record(meta_delivery_start=provider_date), response)]
    )[0]
    ad = _get(db_session, Ad, result.ad_id)

    assert ad.first_seen_at != provider_date
    assert ad.last_seen_at != provider_date


def test_the_sighting_times_are_aware(db_session: Session) -> None:
    """Timezone-aware, because they are compared against provider dates.

    A naive value would raise on comparison with `meta_delivery_start` in a later
    checkpoint rather than here, which is exactly the kind of bug that gets
    expensive.
    """
    run, response = _chain(db_session)

    result = _persist(db_session, run, [_observed(_record(), response)])[0]
    ad = _get(db_session, Ad, result.ad_id)

    assert ad.first_seen_at.tzinfo is not None
    assert ad.last_seen_at.tzinfo is not None


# ============================================================
# Unchanged content
# ============================================================


def test_an_unchanged_observation_in_a_later_run_writes_no_second_snapshot(
    db_session: Session,
) -> None:
    """The core rule, and the reason the history table is worth keeping small.

    A run that sees an ad exactly as it saw it before must not append a row. If it
    did, every daily run would mint a snapshot per ad and the table would grow
    without carrying any new information -- and `not_seen_since`'s "N consecutive
    complete runs" reasoning would have nothing to count.
    """
    first_run, first_response = _chain(db_session)
    _persist(db_session, first_run, [_observed(_record(), first_response)])

    second_run = _another_run(db_session, first_response)
    second_response = second_response_of(db_session, second_run)
    results = _persist(db_session, second_run, [_observed(_record(), second_response)])

    assert _count(db_session, Ad) == 1
    assert _count(db_session, AdSnapshot) == 1, "an unchanged ad appended a snapshot"
    assert _count(db_session, SeenInRun) == 2, "the second run's sighting is not linked"
    assert results[0].created_snapshot is False


def test_an_unchanged_observation_leaves_the_current_snapshot_pointer_where_it_was(
    db_session: Session,
) -> None:
    """`latest_snapshot_id` means "this is the ad's current state", and nothing
    about the state changed.

    Moving the pointer onto a snapshot that is byte-for-byte the same observation
    would be a lie about *when* the ad last changed -- the pointer is what a later
    `not_seen_since` calculation reads.
    """
    first_run, first_response = _chain(db_session)
    first = _persist(db_session, first_run, [_observed(_record(), first_response)])[0]

    second_run = _another_run(db_session, first_response)
    second_response = second_response_of(db_session, second_run)
    second = _persist(db_session, second_run, [_observed(_record(), second_response)])[0]

    ad = _get(db_session, Ad, first.ad_id)
    assert ad.latest_snapshot_id == first.snapshot_id
    assert second.snapshot_id == first.snapshot_id, (
        "an unchanged ad resolved to a different snapshot"
    )


def test_a_change_in_a_field_the_hash_ignores_still_writes_no_snapshot(
    db_session: Session,
) -> None:
    """The end-to-end consequence of the v1 exclusions.

    A provider status flip and a page rename are real changes and must not append
    a snapshot. This is the test that ties `test_content_hash.py`'s exclusions to
    the rows: a unit test on the digest proves the function, and this proves the
    function is what decides the rows.
    """
    first_run, first_response = _chain(db_session)
    _persist(db_session, first_run, [_observed(_record(), first_response)])

    second_run = _another_run(db_session, first_response)
    _persist(
        db_session,
        second_run,
        [
            _observed(
                _record(ad_status="inactive", page_name="Acme Renamed"),
                second_response_of(db_session, second_run),
            )
        ],
    )

    assert _count(db_session, AdSnapshot) == 1
    assert _count(db_session, SeenInRun) == 2


def test_a_change_in_provider_ordering_still_writes_no_snapshot(
    db_session: Session,
) -> None:
    """Provider reordering is not a change, end to end.

    The mock corpus already reorders its output (`REPOSITORY_RESEARCH.md:47`).
    If order mattered, every run would append a snapshot per ad for no reason at
    all, and the history table would be useless.
    """
    first_run, first_response = _chain(db_session)
    _persist(
        db_session,
        first_run,
        [_observed(_record(platforms=("facebook", "instagram")), first_response)],
    )

    second_run = _another_run(db_session, first_response)
    _persist(
        db_session,
        second_run,
        [
            _observed(
                _record(platforms=("instagram", "facebook")),
                second_response_of(db_session, second_run),
            )
        ],
    )

    assert _count(db_session, AdSnapshot) == 1


# ============================================================
# Changed content
# ============================================================


def test_a_changed_observation_appends_exactly_one_new_snapshot(
    db_session: Session,
) -> None:
    """Content changed, so history grows -- by one row, and only one.

    "Exactly one" matters as much as "at least one": a service that appended per
    sighting would satisfy a weaker assertion and turn a single changed ad into a
    run of duplicates.
    """
    first_run, first_response = _chain(db_session)
    first = _persist(db_session, first_run, [_observed(_record(), first_response)])[0]

    second_run = _another_run(db_session, first_response)
    second = _persist(
        db_session,
        second_run,
        [
            _observed(
                _record(primary_text="Buy now, today only"),
                second_response_of(db_session, second_run),
            )
        ],
    )[0]

    assert _count(db_session, Ad) == 1, "a changed ad became a second ad"
    assert _count(db_session, AdSnapshot) == 2
    assert second.created_snapshot is True
    assert second.snapshot_id != first.snapshot_id


def test_a_changed_observation_moves_the_pointer_to_the_new_snapshot(
    db_session: Session,
) -> None:
    """The pointer follows the newest observation, and the older one survives.

    The first snapshot is still readable, which is the point of the table: the
    ad's copy changed on a particular day and the earlier copy is the only record
    of what it said before.
    """
    first_run, first_response = _chain(db_session)
    first = _persist(db_session, first_run, [_observed(_record(), first_response)])[0]

    second_run = _another_run(db_session, first_response)
    second = _persist(
        db_session,
        second_run,
        [
            _observed(
                _record(headline="A different headline"),
                second_response_of(db_session, second_run),
            )
        ],
    )[0]

    ad = _get(db_session, Ad, first.ad_id)
    assert ad.latest_snapshot_id == second.snapshot_id
    assert _get(db_session, AdSnapshot, first.snapshot_id) is not None, (
        "appending a snapshot destroyed the previous one"
    )


def test_each_new_snapshot_cites_the_response_it_was_actually_read_from(
    db_session: Session,
) -> None:
    """`raw_ref` distinguishes the two observations, so the chain stays honest.

    The second snapshot was read from the second run's response. If it cited the
    first, the audit trail would point at a payload that never contained the new
    copy -- and a reader checking it would find nothing that justified the row.
    """
    first_run, first_response = _chain(db_session)
    first = _persist(db_session, first_run, [_observed(_record(), first_response)])[0]

    second_run = _another_run(db_session, first_response)
    second_raw = second_response_of(db_session, second_run)
    second = _persist(
        db_session,
        second_run,
        [_observed(_record(cta="LEARN_MORE"), second_raw)],
    )[0]

    first_snapshot = _get(db_session, AdSnapshot, first.snapshot_id)
    second_snapshot = _get(db_session, AdSnapshot, second.snapshot_id)

    assert first_snapshot.raw_ref == first_response.id
    assert second_snapshot.raw_ref == second_raw.id
    assert second_snapshot.raw_ref != first_snapshot.raw_ref


def test_a_changed_observation_keeps_the_first_sighting_time_and_advances_the_last(
    db_session: Session,
) -> None:
    """`first_seen_at` never moves. That is what "first" means.

    Only `last_seen_at` advances, and only forward. A service that refreshed both
    would erase the fact that we have known about this ad since the first run --
    which is the thing a longevity display would eventually be built on.
    """
    first_run, first_response = _chain(db_session)
    _persist(db_session, first_run, [_observed(_record(), first_response)])
    ad_before = _the_ad(db_session)

    second_run = _another_run(db_session, first_response)
    _persist(
        db_session,
        second_run,
        [
            _observed(
                _record(primary_text="Changed"),
                second_response_of(db_session, second_run),
            )
        ],
    )
    db_session.expire_all()
    ad_after = _the_ad(db_session)

    assert ad_after.first_seen_at == ad_before.first_seen_at
    assert ad_after.last_seen_at >= ad_before.last_seen_at


# ============================================================
# The same ad more than once in one run
# ============================================================


def test_one_ad_served_three_times_in_a_run_writes_one_snapshot(
    db_session: Session,
) -> None:
    """The cardinality rule, end to end.

    The committed corpus does exactly this. Three sightings are one observation,
    and writing three snapshots would claim the ad changed twice within a walk
    that took seconds.
    """
    run, response = _chain(db_session)
    record = _record()

    results = _persist(
        db_session,
        run,
        [_observed(record, response) for _ in range(3)],
    )

    assert len(results) == 1, "one ad produced more than one result"
    assert _count(db_session, Ad) == 1
    assert _count(db_session, AdSnapshot) == 1
    assert _count(db_session, SeenInRun) == 1


def test_repeated_sightings_resolve_to_the_last_record_in_provider_order(
    db_session: Session,
) -> None:
    """Which sighting wins, and why it is the last.

    The order available is the provider's own array order, and nothing in the
    contract says it is chronological. "Last in the run's own order" is therefore
    not a claim about which sighting is newer -- it is the only deterministic rule
    available, and determinism is what the snapshot rule needs.
    """
    run, response = _chain(db_session)

    results = _persist(
        db_session,
        run,
        [
            _observed(_record(primary_text="first sighting"), response),
            _observed(_record(primary_text="second sighting"), response),
            _observed(_record(primary_text="third sighting"), response),
        ],
    )

    assert len(results) == 1
    snapshot = _get(db_session, AdSnapshot, results[0].snapshot_id)
    assert snapshot.normalized["primary_text"] == "third sighting"
    assert results[0].content_hash == content_hash_v1(_record(primary_text="third sighting"))


def test_the_ad_order_follows_first_appearance_not_the_winning_sighting(
    db_session: Session,
) -> None:
    """Collapsing sightings must not reorder the ads.

    The result order is what a caller logs and asserts on, so it must depend on
    the order the ads first appeared and not on which sighting of each happened
    to win.
    """
    run, response = _chain(db_session)

    results = _persist(
        db_session,
        run,
        [
            _observed(_record(external_ad_id="ad-A", primary_text="a1"), response),
            _observed(_record(external_ad_id="ad-B", primary_text="b1"), response),
            _observed(_record(external_ad_id="ad-A", primary_text="a2"), response),
        ],
    )

    assert [result.meta_ad_id for result in results] == ["ad-A", "ad-B"]
    assert _count(db_session, Ad) == 2
    assert _count(db_session, AdSnapshot) == 2


def test_sightings_across_different_responses_in_one_run_make_one_snapshot(
    db_session: Session,
) -> None:
    """The same ad on two pages of one walk, cited to one snapshot.

    A provider can serve one ad on two pages of the same run. That is one
    observation of one ad, so it is one snapshot -- and the pointer ends up naming
    whichever response the winning sighting came from.
    """
    run, first_response = _chain(db_session)
    second_response = second_response_of(db_session, run)

    _persist(
        db_session,
        run,
        [
            _observed(_record(primary_text="from page one"), first_response),
            _observed(_record(primary_text="from page two"), second_response),
        ],
    )

    assert _count(db_session, AdSnapshot) == 1
    snapshot = db_session.execute(select(AdSnapshot)).scalar_one()
    assert snapshot.normalized["primary_text"] == "from page two"
    assert snapshot.raw_ref == second_response.id


# ============================================================
# Idempotence
# ============================================================


def test_reprocessing_the_same_run_adds_nothing(db_session: Session) -> None:
    """Reprocessing must be safe, because it will happen.

    A parser bug in a later checkpoint means re-reading stored payloads. If that
    re-read appended snapshots, fixing a bug would manufacture a history of
    changes that never occurred -- so identity is an upsert, an unchanged digest
    writes nothing, and the link is an upsert.
    """
    run, response = _chain(db_session)
    record = _record()

    first = _persist(db_session, run, [_observed(record, response)])
    second = _persist(db_session, run, [_observed(record, response)])

    assert _count(db_session, Ad) == 1
    assert _count(db_session, AdSnapshot) == 1
    assert _count(db_session, SeenInRun) == 1
    assert first[0].ad_id == second[0].ad_id
    assert first[0].snapshot_id == second[0].snapshot_id
    assert first[0].created_snapshot is True
    assert second[0].created_snapshot is False


def test_reprocessing_a_run_does_not_move_the_observation_time(
    db_session: Session,
) -> None:
    """The link's `created_at` is the first time *this run* observed the ad, so a
    second sighting within the run must not move it.

    This is the one column that is explicitly absent from the upsert's `SET` list.
    If it moved, the observation clock would drift forward every reprocess and
    would stop being a record of when we saw the ad.
    """
    run, response = _chain(db_session)
    record = _record()

    _persist(db_session, run, [_observed(record, response)])
    before = db_session.execute(select(SeenInRun.created_at)).scalar_one()

    _persist(db_session, run, [_observed(record, response)])
    after = db_session.execute(select(SeenInRun.created_at)).scalar_one()

    assert after == before


def test_a_second_run_sees_the_same_ad_and_gets_its_own_link(
    db_session: Session,
) -> None:
    """Idempotence is per run, not global.

    Two runs observing one unchanged ad is one ad, one snapshot, and two links --
    because "this run saw it" is a per-run fact and the pair is unique.
    """
    first_run, first_response = _chain(db_session)
    _persist(db_session, first_run, [_observed(_record(), first_response)])

    second_run = _another_run(db_session, first_response)
    second_response = second_response_of(db_session, second_run)
    _persist(db_session, second_run, [_observed(_record(), second_response)])

    links = db_session.execute(select(SeenInRun)).scalars().all()

    assert _count(db_session, Ad) == 1
    assert _count(db_session, AdSnapshot) == 1
    assert len(links) == 2
    assert {link.collection_run_id for link in links} == {first_run.id, second_run.id}


def test_the_same_ad_id_from_two_providers_is_two_ads(
    db_session: Session,
) -> None:
    """Ad identity is the pair, so the providers' scopes cannot collide.

    `meta_ad_id` alone would be ambiguous the moment a second provider is
    registered, and the two providers would overwrite each other's ad rows -- each
    one destroying the other's history rather than failing loudly.
    """
    run, response = _chain(db_session)
    record = _record(external_ad_id="shared-1234")

    _persist(db_session, run, [_observed(record, response)], provider="mock")
    _persist(
        db_session,
        run,
        [_observed(record, response)],
        provider="other",
        data_origin=DataOrigin.public_ui,
    )

    ads = db_session.execute(select(Ad)).scalars().all()
    assert len(ads) == 2, "two providers' ids were merged into one ad"
    assert {ad.provider for ad in ads} == {"mock", "other"}
    assert {ad.meta_ad_id for ad in ads} == {"shared-1234"}
    assert {ad.data_origin for ad in ads} == {DataOrigin.third_party, DataOrigin.public_ui}
    assert _count(db_session, AdSnapshot) == 2


def test_the_same_ad_id_from_one_provider_is_still_one_ad(
    db_session: Session,
) -> None:
    """The negative control for the pair above.

    Without it, the previous test would also pass if identity were the *pair*
    `(provider, meta_ad_id)` reversed into something that never matched anything.
    """
    first_run, first_response = _chain(db_session)
    _persist(db_session, first_run, [_observed(_record(), first_response)])

    second_run = _another_run(db_session, first_response)
    _persist(
        db_session,
        second_run,
        [_observed(_record(), second_response_of(db_session, second_run))],
        provider=PROVIDER,
    )

    assert _count(db_session, Ad) == 1


# ============================================================
# Append-only, and what the database refuses
# ============================================================


def test_a_snapshot_cannot_be_updated(db_session: Session) -> None:
    """The rule AGENTS.md section 8 states, enforced by the database.

    An update to a snapshot would be a deletion dressed as a correction: the
    earlier reading of the ad is gone, and for a commercial ad that stopped
    running it is gone for good. The rule lives in the schema rather than in
    application discipline because a rule only the application respects is a rule
    one careless refactor breaks silently.
    """
    run, response = _chain(db_session)
    result = _persist(db_session, run, [_observed(_record(), response)])[0]

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text("UPDATE ad_snapshots SET ad_status = 'rewritten' WHERE id = :id"),
            {"id": result.snapshot_id},
        )

    assert "append-only" in str(caught.value)
    db_session.rollback()


def test_a_snapshot_cannot_be_deleted(db_session: Session) -> None:
    """The other half of the same rule.

    `test_the_refusal_is_transitive_down_the_whole_chain` covers the `RESTRICT`
    on a snapshot's parents. This is different: nothing references a snapshot's
    row content, so only the trigger can refuse this delete.
    """
    run, response = _chain(db_session)
    result = _persist(db_session, run, [_observed(_record(), response)])[0]

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text("DELETE FROM ad_snapshots WHERE id = :id"),
            {"id": result.snapshot_id},
        )

    assert "append-only" in str(caught.value)
    db_session.rollback()


def test_a_snapshot_row_survives_untouched_after_a_later_run(db_session: Session) -> None:
    """The practical consequence: history accumulates, it is never rewritten.

    Three runs, one of which saw a changed ad. The first snapshot's stored
    reading still says what it said, and its `updated_at` never moved -- which
    *is* the signal that nothing wrote to history, since the column is otherwise
    inert on an append-only table.
    """
    first_run, first_response = _chain(db_session)
    first = _persist(db_session, first_run, [_observed(_record(), first_response)])[0]
    original = _get(db_session, AdSnapshot, first.snapshot_id)
    original_updated = original.updated_at

    second_run = _another_run(db_session, first_response)
    _persist(
        db_session,
        second_run,
        [_observed(_record(primary_text="v2"), second_response_of(db_session, second_run))],
    )
    third_run = _another_run(db_session, first_response)
    _persist(
        db_session,
        third_run,
        [_observed(_record(primary_text="v2"), second_response_of(db_session, third_run))],
    )

    db_session.expire_all()
    survivor = _get(db_session, AdSnapshot, first.snapshot_id)

    assert _count(db_session, AdSnapshot) == 2
    assert survivor.normalized["primary_text"] == "Buy now"
    assert survivor.updated_at == original_updated
    assert survivor.content_hash == first.content_hash


def test_a_link_row_may_be_corrected_which_is_the_point_of_it_not_being_append_only(
    db_session: Session,
) -> None:
    """`seen_in_run` is a link, so the second sighting corrects it.

    Append-only is scoped to `ad_snapshots` because a snapshot is a claim about
    what the ad looked like and rewriting one destroys evidence. A link says "this
    run saw this ad, and here is the snapshot it resolved to" -- and the honest
    answer when a later sighting in the same run points at a different snapshot is
    to correct the link, not to add a second row claiming the same thing happened
    twice.
    """
    run, response = _chain(db_session)

    results = _persist(
        db_session,
        run,
        [
            _observed(_record(primary_text="v1"), response),
            _observed(_record(primary_text="v2"), response),
            _observed(_record(primary_text="v3"), response),
        ],
    )

    links = db_session.execute(select(SeenInRun)).scalars().all()

    assert len(links) == 1, "three sightings of one ad produced three link rows"
    # The single link points at the snapshot the *winning* sighting produced, so
    # the run is recorded as having seen the ad in its final observed state.
    assert links[0].snapshot_id == results[0].snapshot_id
    assert _count(db_session, AdSnapshot) == 1


def test_a_link_points_at_the_snapshot_the_run_actually_resolved_to(
    db_session: Session,
) -> None:
    """The link's `snapshot_id` is the observation, not merely "some snapshot".

    When an ad is unchanged since an earlier run, the link names the *earlier*
    run's snapshot -- the observation the run resolved to, not one the run
    created. That is what makes the link a record of what the run saw rather than
    a record of what the run wrote.
    """
    first_run, first_response = _chain(db_session)
    first = _persist(db_session, first_run, [_observed(_record(), first_response)])[0]

    second_run = _another_run(db_session, first_response)
    second_raw = second_response_of(db_session, second_run)
    second = _persist(db_session, second_run, [_observed(_record(), second_raw)])[0]

    second_link = db_session.execute(
        select(SeenInRun).where(SeenInRun.collection_run_id == second_run.id)
    ).scalar_one()

    assert second.created_snapshot is False
    assert second_link.snapshot_id == first.snapshot_id
    # And the pointer the second run left is that same snapshot.
    assert second_link.snapshot_id == second.snapshot_id


# ============================================================
# Constraints the database enforces
# ============================================================


def test_the_database_refuses_a_duplicate_sighting_pair(db_session: Session) -> None:
    """`UNIQUE (ad_id, collection_run_id)` is installed, not merely declared.

    Asserted by writing the row the service would refuse to write, so the
    constraint is proven live rather than read off the metadata -- which
    `test_ads.py` already does for the declaration.
    """
    run, response = _chain(db_session)
    result = _persist(db_session, run, [_observed(_record(), response)])[0]
    snapshot = _get(db_session, AdSnapshot, result.snapshot_id)

    duplicate = SeenInRun(
        ad_id=result.ad_id,
        collection_run_id=run.id,
        snapshot_id=snapshot.id,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "uq_seen_in_run_ad_run" in str(caught.value)
    db_session.rollback()


def test_the_database_refuses_a_second_snapshot_for_one_ad_in_one_run(
    db_session: Session,
) -> None:
    """`UNIQUE (ad_id, collection_run_id)` on `ad_snapshots` as well.

    The service collapses repeated sightings before writing, so this is the
    backstop: it makes the cardinality rule impossible to get wrong rather than
    merely discouraged.
    """
    run, response = _chain(db_session)
    result = _persist(db_session, run, [_observed(_record(), response)])[0]

    duplicate = AdSnapshot(
        ad_id=result.ad_id,
        collection_run_id=run.id,
        raw_ref=response.id,
        content_hash="0" * 64,
        normalized={"external_ad_id": "ad-0001"},
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "uq_ad_snapshots_ad_run" in str(caught.value)
    db_session.rollback()


def test_the_database_refuses_a_digest_that_is_not_a_sha256(db_session: Session) -> None:
    """`ck_ad_snapshots_content_hash_is_sha256_hex` is installed.

    A malformed digest would not fail loudly. It would make every future
    comparison unequal, so no snapshot would ever be written again -- a silent,
    permanent loss of the ability to detect change, which is why the shape is
    checked at the database rather than trusted from Python.
    """
    run, response = _chain(db_session)

    snapshot = AdSnapshot(
        ad_id=uuid.uuid4(),
        collection_run_id=run.id,
        raw_ref=response.id,
        content_hash="not-a-digest",
        normalized={"external_ad_id": "ad-0001"},
    )
    db_session.add(snapshot)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "content_hash_is_sha256_hex" in str(caught.value)
    db_session.rollback()


def test_a_snapshot_must_name_a_response_that_exists(db_session: Session) -> None:
    """`raw_ref` is `NOT NULL` and real: a snapshot that cannot name its source
    is an assertion with nothing behind it.

    Checked in the direction the service cannot reach, because the service always
    has a response in hand. The orphan is what a future caller could produce.

    The other two parents are given real rows, so the constraint that fires is
    provably `raw_ref`'s rather than whichever of the three happened to be
    checked first.
    """
    first_run, first_response = _chain(db_session)
    ad = _an_ad(db_session, first_run, first_response)
    # A second run, so the orphan is not merely a duplicate of the pair
    # `(ad, first_run)` that `_an_ad` legitimately wrote.
    run = _another_run(db_session, first_response)

    orphan = AdSnapshot(
        ad_id=ad.id,
        collection_run_id=run.id,
        raw_ref=uuid.uuid4(),
        content_hash="0" * 64,
        normalized={"external_ad_id": "ad-0001"},
    )
    db_session.add(orphan)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "fk_ad_snapshots_raw_ref" in str(caught.value)
    db_session.rollback()


def test_a_snapshot_must_name_a_run_that_exists(db_session: Session) -> None:
    """The other parent, so the same reasoning applies to `collection_run_id`."""
    run, response = _chain(db_session)
    ad = _an_ad(db_session, run, response)
    other_response = second_response_of(db_session, run)

    orphan = AdSnapshot(
        ad_id=ad.id,
        collection_run_id=uuid.uuid4(),
        raw_ref=other_response.id,
        content_hash="0" * 64,
        normalized={"external_ad_id": "ad-0001"},
    )
    db_session.add(orphan)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "fk_ad_snapshots_collection_run_id" in str(caught.value)
    db_session.rollback()


def test_a_snapshot_must_name_an_ad_that_exists(db_session: Session) -> None:
    """The third parent, completing the three.

    Without this, the two above would pass even if `ad_id` carried no constraint
    at all -- the other two would fire first and the gap would never show.
    """
    run, response = _chain(db_session)

    orphan = AdSnapshot(
        ad_id=uuid.uuid4(),
        collection_run_id=run.id,
        raw_ref=response.id,
        content_hash="0" * 64,
        normalized={"external_ad_id": "ad-0001"},
    )
    db_session.add(orphan)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "fk_ad_snapshots_ad_id" in str(caught.value)
    db_session.rollback()


def test_the_ad_itself_cannot_be_deleted_while_a_snapshot_exists(
    db_session: Session,
) -> None:
    """`RESTRICT`, one level up from the append-only trigger.

    The trigger refuses the snapshot's own row; this refuses the ad that the
    snapshot belongs to. Both are needed -- without the trigger an update would
    succeed, and without this a delete would take the ad with its history.
    """
    run, response = _chain(db_session)
    result = _persist(db_session, run, [_observed(_record(), response)])[0]

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(text("DELETE FROM ads WHERE id = :id"), {"id": result.ad_id})

    assert "fk_ad_snapshots_ad_id" in str(caught.value)
    db_session.rollback()


def test_a_link_must_name_a_snapshot_that_exists(db_session: Session) -> None:
    """A link pointing at nothing is indistinguishable from a run that saw an ad
    with no snapshot, so the database refuses it.

    The third of the three `seen_in_run` parents, and the one a caller could most
    plausibly get wrong by trusting a returned id without checking.
    """
    run, response = _chain(db_session)
    result = _persist(db_session, run, [_observed(_record(), response)])[0]
    db_session.execute(text("DELETE FROM seen_in_run WHERE ad_id = :id"), {"id": result.ad_id})

    orphan = SeenInRun(
        ad_id=result.ad_id,
        collection_run_id=run.id,
        snapshot_id=uuid.uuid4(),
    )
    db_session.add(orphan)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "fk_seen_in_run_snapshot_id" in str(caught.value)
    db_session.rollback()


# ============================================================
# An empty run
# ============================================================


def test_a_run_that_read_no_ad_writes_nothing(db_session: Session) -> None:
    """Zero observations is a real outcome, not an error.

    A provider that serves nothing is a result the product has to be able to
    record, and a run with no ads must not manufacture an ad row to hold a
    timestamp. This is also the shape a walk that ended `partial` on a wholly
    unreadable page takes.
    """
    run, _response = _chain(db_session)

    results = _persist(db_session, run, [])

    assert results == ()
    assert _count(db_session, Ad) == 0
    assert _count(db_session, AdSnapshot) == 0
    assert _count(db_session, SeenInRun) == 0


# ============================================================
# Helpers needing the whole file
# ============================================================


def test_a_new_snapshot_carries_both_s22_digests(db_session: Session) -> None:
    """The two S2.2 columns are written at INSERT, by the real hash functions.

    Read straight off the stored row and compared with the functions themselves,
    so a change to either hash contract surfaces here rather than as a duplicate
    report that quietly finds nothing.
    """
    from app.services.copy_hash import copy_hash_v1
    from app.services.creative_hash import creative_hash_v1

    run, response = _chain(db_session)
    record = _record()

    result = _persist(db_session, run, [_observed(record, response)])[0]
    snapshot = _get(db_session, AdSnapshot, result.snapshot_id)

    assert snapshot.copy_hash == copy_hash_v1(record)
    assert snapshot.creative_hash == creative_hash_v1(record)
    # And the frozen S2.1 digest is still there, still v1, untouched.
    assert snapshot.content_hash == content_hash_v1(record)
    assert len(snapshot.content_hash) == 64


def test_a_pre_s22_snapshot_keeps_null_digests_and_is_never_backfilled(
    db_session: Session,
) -> None:
    """`NULL` means "recorded before S2.2", permanently.

    The table is append-only, so a row that predates the columns can never be
    given a digest -- an `UPDATE` is refused by the trigger. That is the same
    trade S2.1 made for `content_hash`, and asserting it here is what stops a
    later session from adding a backfill that would either fail on the trigger or
    fabricate a value nobody observed.
    """
    run, response = _chain(db_session)
    ad = _an_ad(db_session, run, response)
    later_run = _another_run(db_session, response)
    later_response = second_response_of(db_session, later_run)

    legacy = AdSnapshot(
        ad_id=ad.id,
        collection_run_id=later_run.id,
        raw_ref=later_response.id,
        content_hash="0" * 64,
        normalized={"external_ad_id": "ad-0001"},
    )
    db_session.add(legacy)
    db_session.flush()

    assert legacy.copy_hash is None
    assert legacy.creative_hash is None

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text("UPDATE ad_snapshots SET copy_hash = :digest WHERE id = :id"),
            {"digest": "1" * 64, "id": legacy.id},
        )
    assert "append-only" in str(caught.value)
    db_session.rollback()


def test_a_changed_creative_with_unchanged_copy_appends_a_snapshot(
    db_session: Session,
) -> None:
    """The proof that the new split is actually used rather than decorative.

    Identical words, different media. `content_hash` v1 covers words *and*
    assets, so the change decision is already made by the existing S2.1 rule --
    no second comparison was added, and none should be, because two comparisons
    that could disagree would be worse than one. This asserts the end-to-end
    consequence: a creative-only change is caught, and the new `creative_hash`
    column records the difference the old one absorbed.
    """
    first_run, first_response = _chain(db_session)
    first = _persist(
        db_session,
        first_run,
        [_observed(_record(media=(MediaRef(provider_key="img-1"),)), first_response)],
    )[0]

    second_run = _another_run(db_session, first_response)
    second_raw = second_response_of(db_session, second_run)
    second = _persist(
        db_session,
        second_run,
        [
            _observed(
                _record(media=(MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2"))),
                second_raw,
            )
        ],
    )[0]

    original = _get(db_session, AdSnapshot, first.snapshot_id)
    updated = _get(db_session, AdSnapshot, second.snapshot_id)

    assert _count(db_session, AdSnapshot) == 2
    assert second.created_snapshot is True
    assert updated.id != original.id
    # The copy did not change, so its digest did not...
    assert updated.copy_hash == original.copy_hash
    # ...and the creative did, so its digest did. That asymmetry is the whole
    # reason the two columns exist.
    assert updated.creative_hash != original.creative_hash


def test_a_changed_copy_with_unchanged_creative_appends_a_snapshot(
    db_session: Session,
) -> None:
    """The mirror image, from the copy side."""
    first_run, first_response = _chain(db_session)
    first = _persist(db_session, first_run, [_observed(_record(), first_response)])[0]

    second_run = _another_run(db_session, first_response)
    second_raw = second_response_of(db_session, second_run)
    second = _persist(
        db_session,
        second_run,
        [_observed(_record(primary_text="Different words"), second_raw)],
    )[0]

    original = _get(db_session, AdSnapshot, first.snapshot_id)
    updated = _get(db_session, AdSnapshot, second.snapshot_id)

    assert _count(db_session, AdSnapshot) == 2
    assert updated.copy_hash != original.copy_hash
    assert updated.creative_hash == original.creative_hash


def test_unchanged_content_still_writes_no_snapshot_and_no_digests(
    db_session: Session,
) -> None:
    """S2.1's core rule is unchanged by the two new columns.

    A re-observation of identical content must still write no snapshot -- and so
    must write no new digests, because the digests live on the snapshot. If a
    session started persisting them on the ad or on the link row instead, an
    unchanged ad would accumulate a row per run, which is the bloat
    `content_hash` was introduced to prevent.
    """
    first_run, first_response = _chain(db_session)
    _persist(db_session, first_run, [_observed(_record(), first_response)])

    second_run = _another_run(db_session, first_response)
    second_raw = second_response_of(db_session, second_run)
    _persist(db_session, second_run, [_observed(_record(), second_raw)])

    assert _count(db_session, AdSnapshot) == 1
    assert _count(db_session, SeenInRun) == 2


def test_the_latest_snapshot_pointer_moves_for_a_creative_only_change(
    db_session: Session,
) -> None:
    """S2.1's pointer rule, exercised through the new split.

    A creative-only change is a content change, so `latest_snapshot_id` must move
    onto the new snapshot exactly as it would for a copy change. The pointer means
    "this is the ad's current state", and the current state's assets changed.
    """
    first_run, first_response = _chain(db_session)
    first = _persist(
        db_session,
        first_run,
        [_observed(_record(media=(MediaRef(provider_key="img-1"),)), first_response)],
    )[0]

    second_run = _another_run(db_session, first_response)
    second_raw = second_response_of(db_session, second_run)
    second = _persist(
        db_session,
        second_run,
        [
            _observed(
                _record(media=(MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2"))),
                second_raw,
            )
        ],
    )[0]

    ad = _get(db_session, Ad, first.ad_id)

    assert ad.latest_snapshot_id == second.snapshot_id
    assert ad.latest_snapshot_id != first.snapshot_id


def _the_ad(db_session: Session) -> Ad:
    return db_session.execute(select(Ad)).scalar_one()


def _an_ad(db_session: Session, run: CollectionRun, response: RawResponse) -> Ad:
    """One real ad, written the way the service writes one.

    Used by the orphan-FK tests: each of the three parents needs a real value so
    that the constraint under test is the only one that can fire. Asserting on
    `fk_ad_snapshots_raw_ref` while passing a random UUID for `ad_id` would pass
    for the wrong reason whenever `ad_id` is checked first.

    Takes the existing chain rather than building another, because
    `facebook_pages.page_id` is globally unique -- a second `_chain` in one test
    would collide on the page before reaching the assertion.
    """
    result = _persist(db_session, run, [_observed(_record(), response)])[0]
    return _get(db_session, Ad, result.ad_id)


def test_reprocessing_a_run_with_changed_content_is_refused(db_session: Session) -> None:
    """The conditional half of the idempotence contract, pinned.

    Identical input is idempotent -- that is
    `test_reprocessing_the_same_run_adds_nothing` above. This is the other half,
    and it is the half that is *refused* rather than absorbed.

    The run below is reprocessed with a record whose copy has changed, so the
    digest differs from the snapshot already stored for that `(ad, run)` pair.
    `uq_ad_snapshots_ad_run` refuses the second row.

    ## Why the refusal is correct, and must not be "fixed"

    One collection run is one observation of an ad, so `(ad, run)` *is* the
    identity of that observation and admits exactly one snapshot. A run that
    yields two different readings of the same ad is not a re-processing of one
    observation -- it is two observations wearing one run's identity, and the
    honest record of that is a new run, not a second snapshot inside the first.

    The cost of allowing it is concrete: the per-run history stops being a record
    of a walk and becomes a record of a reading, so a run could claim an ad
    changed several times within seconds. And S2.3's `not_seen_since` reasoning
    counts *consecutive complete runs*, which is only meaningful if one run
    contributes one observation per ad.

    Re-processing exists to fix a parser bug, and a fixed parser reads the same
    stored bytes to the same digest -- so this path is not reached by the use case
    idempotence was introduced for. It is reached when the *reader* changed, which
    is exactly the case worth refusing loudly rather than silently recording as
    history.

    A future checkpoint that decides two snapshots per run are warranted should
    change this deliberately, with a migration, and a reason -- not by catching
    this `IntegrityError` and retrying.
    """
    run, response = _chain(db_session)
    first = _persist(db_session, run, [_observed(_record(primary_text="v1"), response)])

    with pytest.raises(IntegrityError) as caught:
        _persist(db_session, run, [_observed(_record(primary_text="v2"), response)])

    assert "uq_ad_snapshots_ad_run" in str(caught.value)
    db_session.rollback()

    # The first observation survives the refusal: the failed attempt rolled back
    # rather than corrupting what the run had already recorded.
    db_session.expire_all()
    assert _count(db_session, Ad) == 1
    assert _count(db_session, AdSnapshot) == 1
    survivor = _get(db_session, AdSnapshot, first[0].snapshot_id)
    assert survivor.normalized["primary_text"] == "v1"


def second_response_of(db_session: Session, run: CollectionRun) -> RawResponse:
    """A fresh provider call and raw response belonging to `run`.

    Written inline rather than reused from `_chain` because a later run needs its
    *own* call: two responses on one call would not distinguish which one a
    snapshot was read from, and the whole claim of this helper is that the
    `raw_ref` names the right source.
    """
    # `started_at` is read defensively because `CollectionRun.started_at` is
    # nullable -- a pending run has no start time. Every run that reaches this
    # helper was created by `_another_run`, which always sets it, but the type
    # is honest about the column and the fallback keeps the helper usable on a
    # run that has not started.
    requested_at = run.started_at or NOW

    call = ProviderRun(
        collection_run_id=run.id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=requested_at,
        finished_at=run.finished_at,
        request_meta={
            "provider": PROVIDER,
            "origin": DataOrigin.third_party.value,
            "country": "IN",
            "requested_at": requested_at.isoformat(),
            "cursor": None,
        },
        http_status=200,
    )
    db_session.add(call)
    db_session.flush()

    response = RawResponse(provider_run_id=call.id, payload={"ads": []})
    db_session.add(response)
    db_session.flush()
    return response

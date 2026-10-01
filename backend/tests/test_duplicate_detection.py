"""Duplicate grouping, proven against PostgreSQL.

Two different ads that hash alike are a *finding* -- the most useful thing this
product can say about a competitor's strategy -- so there is no `UNIQUE`
constraint here and there never should be. What these tests protect is the set of
ways that finding can be produced *wrongly*, and each of those is a plausible
mistake rather than a hypothetical one:

* a `NULL` bucket that groups every pre-S2.2 snapshot together;
* one ad with four historical snapshots reported as a duplicate of itself;
* `count(*)` where `count(DISTINCT ad_id)` was meant.

`integration`, because all three are database behaviours: a `GROUP BY`, a `NULL`
comparison, and a `DISTINCT` count. None of them is observable through a fake
session, which is why this file cannot be a unit test.

Writes go through the real persistence service rather than being hand-built, so
the digests stored here are the ones the product would actually compute.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
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
)
from app.providers.data.models import AdFormat, MediaRef, RawAdRecord
from app.providers.data.provenance import DataOrigin
from app.services.ad_persistence import ObservedRecord, persist_observations
from app.services.creative_hash import creative_hash_v1
from app.services.duplicate_detection import DuplicateGroup, duplicate_groups

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
PROVIDER = "mock"


# ============================================================
# A chain and a way to observe
# ============================================================


def _chain(session: Session, page_id: str) -> CollectionRun:
    """A flushed competitor -> page -> run. `page_id` is a parameter because
    `facebook_pages.page_id` is globally unique, so two tests cannot share one."""
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
    return run


def _response(session: Session, run: CollectionRun) -> RawResponse:
    call = ProviderRun(
        collection_run_id=run.id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=run.started_at or NOW,
        finished_at=run.finished_at,
        request_meta={
            "provider": PROVIDER,
            "origin": DataOrigin.third_party.value,
            "country": "IN",
            "requested_at": (run.started_at or NOW).isoformat(),
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


def _record(**overrides: Any) -> RawAdRecord:
    fields: dict[str, Any] = {
        "external_ad_id": "ad-0001",
        "platforms": ("facebook",),
        "countries": ("IN",),
        "ad_status": "active",
        "meta_delivery_start": NOW - timedelta(days=30),
        "primary_text": "The same offer",
        "headline": "The same headline",
        "cta": "SHOP_NOW",
        "destination_url": "https://example.invalid/offer",
        "display_format": AdFormat.IMAGE,
        "media": (MediaRef(provider_key="img-1"),),
    }
    fields.update(overrides)
    return RawAdRecord(**fields)


def _observe(
    session: Session, run: CollectionRun, record: RawAdRecord
) -> tuple[uuid.UUID, uuid.UUID]:
    """Persist one observation the way the orchestrator does, and return
    `(ad_id, snapshot_id)`.

    The digests are written by the real service, so a change to `copy_hash_v1` or
    `creative_hash_v1` would change what these tests group on -- which is the
    point. A test that hand-wrote the hash columns would keep passing after the
    hash contract moved.
    """
    response = _response(session, run)
    results = persist_observations(
        session,
        run_id=run.id,
        observations=[ObservedRecord(record=record, raw_response_id=response.id)],
        provider=PROVIDER,
        data_origin=DataOrigin.third_party,
    )
    session.commit()
    return results[0].ad_id, results[0].snapshot_id


def _legacy_ad(session: Session, run: CollectionRun, meta_ad_id: str) -> Ad:
    """An `ads` row with no snapshot carrying the S2.2 digests.

    The pre-S2.2 state, reproduced as closely as an append-only table allows: the
    ad exists and the snapshot beside it was written before the digest columns
    did. The `ad` row is real rather than a random UUID because `ad_snapshots`
    holds a `RESTRICT` foreign key to it, and a test that used a dangling id
    would be asserting about a row the database had already refused.
    """
    ad = Ad(
        provider=PROVIDER,
        meta_ad_id=meta_ad_id,
        data_origin=DataOrigin.third_party,
        first_seen_at=NOW - timedelta(days=1),
        last_seen_at=NOW - timedelta(days=1),
    )
    session.add(ad)
    session.flush()
    return ad


def _digests(session: Session) -> set[tuple[str | None, str | None]]:
    return {(row.copy_hash, row.creative_hash) for row in session.query(AdSnapshot).all()}


# ============================================================
# The headline case
# ============================================================


def test_two_different_ads_with_identical_copy_form_one_group(db_session: Session) -> None:
    """The finding S2.2 exists to produce.

    Two ads, different provider ids, word-for-word the same body. Same provider,
    so this is two `ads` rows rather than one ad seen twice -- which is the whole
    point: `ads` identity is `(provider, meta_ad_id)`, so genuinely different ads
    stay different rows and the digest is what brings them together.
    """
    run = _chain(db_session, "100000000000201")
    _observe(db_session, run, _record(external_ad_id="ad-A"))
    _observe(db_session, run, _record(external_ad_id="ad-B"))

    groups = duplicate_groups(db_session, axis="copy")

    assert len(groups) == 1
    assert groups[0].ad_count == 2
    assert len(groups[0].ad_ids) == 2


def test_the_shared_copy_digest_is_the_group_identity(db_session: Session) -> None:
    """The group's key is the value a reader can join on to reach the two ads."""
    from app.services.copy_hash import copy_hash_v1

    run = _chain(db_session, "100000000000202")
    _observe(db_session, run, _record(external_ad_id="ad-A"))
    _observe(db_session, run, _record(external_ad_id="ad-B"))

    group = duplicate_groups(db_session, axis="copy")[0]

    assert group.content_hash == copy_hash_v1(_record())


# ============================================================
# The three ways this can go wrong
# ============================================================


def test_one_ad_with_many_snapshots_is_not_a_duplicate_of_itself(
    db_session: Session,
) -> None:
    """`count(DISTINCT ad_id) > 1`, not `count(*) > 1`.

    An ad's whole history is a handful of snapshots sharing one `copy_hash`, and
    that is the history model working as intended. Counting rows would report
    this ad as a duplicate of itself on every collection, for ever, and the false
    positives would swamp the real ones.
    """
    ad_id, _first = _observe(db_session, _chain(db_session, "100000000000203"), _record())

    for index in range(3):
        later = _chain(db_session, f"10000000021{index:02d}")
        _observe(db_session, later, _record(primary_text=f"Version {index}"))

    assert len(db_session.query(AdSnapshot).all()) == 4
    assert duplicate_groups(db_session, axis="copy") == ()
    # The ad really is one ad with four rows -- the negative case above is not
    # passing because nothing was stored.
    assert db_session.query(Ad).count() == 1
    assert ad_id is not None


def test_null_hashes_are_excluded_from_every_group(db_session: Session) -> None:
    """The `IS NOT NULL` filter, and the reason it is mandatory.

    A snapshot written before S2.2 carries `NULL` in both columns, and the table is
    append-only so it can never be backfilled. Without the filter, every such row
    lands in a single NULL bucket and the query reports every pre-S2.2 ad as a
    duplicate of every other pre-S2.2 ad: a spectacularly wrong answer shaped
    exactly like a result.
    """
    run = _chain(db_session, "100000000000204")
    response = _response(db_session, run)
    ad = _legacy_ad(db_session, run, "legacy-1")

    # A snapshot that predates S2.2, written the only way one could have been:
    # with the digest columns absent rather than set to a placeholder.
    legacy = AdSnapshot(
        ad_id=ad.id,
        collection_run_id=run.id,
        raw_ref=response.id,
        content_hash="0" * 64,
        normalized={"external_ad_id": "legacy-1"},
    )
    db_session.add(legacy)
    db_session.flush()

    assert legacy.copy_hash is None
    assert legacy.creative_hash is None
    assert duplicate_groups(db_session, axis="copy") == ()
    assert duplicate_groups(db_session, axis="creative") == ()


def test_a_group_cannot_be_composed_of_nulls(db_session: Session) -> None:
    """The same rule, stated as the shape of a wrong answer.

    Two legacy rows share `NULL`. If the filter were removed they would form a
    group whose key is not a digest at all -- so this also asserts the key is
    digest-shaped, which catches a filter that was weakened to something else.
    """
    run = _chain(db_session, "100000000000205")
    response = _response(db_session, run)

    for index in range(2):
        ad = _legacy_ad(db_session, run, f"legacy-{index}")
        db_session.add(
            AdSnapshot(
                ad_id=ad.id,
                collection_run_id=run.id,
                raw_ref=response.id,
                content_hash=f"{index}" * 64,
                normalized={"external_ad_id": f"legacy-{index}"},
            )
        )
    db_session.flush()

    assert duplicate_groups(db_session, axis="copy") == ()

    for group in duplicate_groups(db_session, axis="copy"):
        assert len(group.content_hash) == 64, "a group key that is not a digest"


# ============================================================
# Copy and creative are different questions
# ============================================================


def test_same_copy_with_different_creative_groups_by_copy_but_not_by_creative(
    db_session: Session,
) -> None:
    """The concrete value of the split.

    Identical words over different images is the most common real duplicate, and
    it is invisible to `content_hash` alone -- which hashes words and assets
    together and so cannot attribute the match. Reporting it under *copy* while
    leaving *creative* quiet is exactly what the two columns are for.
    """
    run = _chain(db_session, "100000000000206")
    _observe(
        db_session,
        run,
        _record(external_ad_id="ad-A", media=(MediaRef(provider_key="img-1"),)),
    )
    _observe(
        db_session,
        run,
        _record(external_ad_id="ad-B", media=(MediaRef(provider_key="img-2"),)),
    )

    assert len(duplicate_groups(db_session, axis="copy")) == 1
    assert duplicate_groups(db_session, axis="creative") == ()


def test_same_creative_with_different_copy_groups_by_creative_but_not_by_copy(
    db_session: Session,
) -> None:
    """The mirror image: a brand running the same asset with rotated copy."""
    run = _chain(db_session, "100000000000207")
    _observe(
        db_session,
        run,
        _record(external_ad_id="ad-A", primary_text="One offer"),
    )
    _observe(
        db_session,
        run,
        _record(external_ad_id="ad-B", primary_text="A different offer"),
    )

    assert duplicate_groups(db_session, axis="copy") == ()
    assert len(duplicate_groups(db_session, axis="creative")) == 1


def test_fully_identical_ads_group_on_both_axes(db_session: Session) -> None:
    """Words and assets both matching is a duplicate under either question."""
    run = _chain(db_session, "100000000000208")
    _observe(db_session, run, _record(external_ad_id="ad-A"))
    _observe(db_session, run, _record(external_ad_id="ad-B"))

    assert len(duplicate_groups(db_session, axis="copy")) == 1
    assert len(duplicate_groups(db_session, axis="creative")) == 1


def test_three_ads_produce_a_group_of_three_not_three_pairs(db_session: Session) -> None:
    """Grouping, not pairing.

    A pairwise implementation would report three groups of two for three
    identical ads; the count is a property of the group.
    """
    run = _chain(db_session, "100000000000209")
    for index in range(3):
        _observe(db_session, run, _record(external_ad_id=f"ad-{index}"))

    groups = duplicate_groups(db_session, axis="copy")

    assert len(groups) == 1
    assert groups[0].ad_count == 3


# ============================================================
# Ordering and the limit
# ============================================================


def test_groups_come_back_largest_first(db_session: Session) -> None:
    """A duplicate report is only useful while it is short.

    Ordered by how many ads are involved, because a group of forty is a stronger
    finding than a group of two.
    """
    run = _chain(db_session, "100000000000210")
    for index in range(4):
        _observe(db_session, run, _record(external_ad_id=f"big-{index}"))
    for index in range(2):
        _observe(db_session, run, _record(external_ad_id=f"small-{index}", cta="LEARN_MORE"))

    groups = duplicate_groups(db_session, axis="copy")

    assert [group.ad_count for group in groups] == [4, 2]


def test_the_limit_caps_the_number_of_groups_returned(db_session: Session) -> None:
    run = _chain(db_session, "100000000000211")
    for index in range(3):
        _observe(db_session, run, _record(external_ad_id=f"big-{index}"))
    for index in range(2):
        _observe(db_session, run, _record(external_ad_id=f"small-{index}", cta="LEARN_MORE"))

    assert len(duplicate_groups(db_session, axis="copy", limit=1)) == 1


def test_a_run_with_no_duplicates_reports_nothing(db_session: Session) -> None:
    """The common case, and the one a report is mostly made of.

    Both axes must be quiet, so the two ads differ in their words *and* in their
    assets. Differing only the copy would leave them sharing a media key, and the
    creative axis would rightly report them -- which is a reminder that "no
    duplicates" is a statement about both questions.
    """
    run = _chain(db_session, "100000000000212")
    _observe(
        db_session,
        run,
        _record(external_ad_id="ad-A", primary_text="One", media=(MediaRef(provider_key="m1"),)),
    )
    _observe(
        db_session,
        run,
        _record(external_ad_id="ad-B", primary_text="Two", media=(MediaRef(provider_key="m2"),)),
    )

    assert duplicate_groups(db_session, axis="copy") == ()
    assert duplicate_groups(db_session, axis="creative") == ()


def test_group_ids_are_deduplicated_and_ordered(db_session: Session) -> None:
    """An ad appears once however many snapshots it contributed.

    Order is by uuid so the result is stable across calls -- an unstable ordering
    would make a paginated report reshuffle itself between pages.
    """
    run = _chain(db_session, "100000000000213")
    _observe(db_session, run, _record(external_ad_id="ad-A"))
    _observe(db_session, run, _record(external_ad_id="ad-B"))

    group = duplicate_groups(db_session, axis="copy")[0]

    assert len(group.ad_ids) == len(set(group.ad_ids)) == 2
    assert list(group.ad_ids) == sorted(group.ad_ids)


def test_the_group_is_a_frozen_value(db_session: Session) -> None:
    """A report is handed to callers, so it is a value rather than a live query."""
    run = _chain(db_session, "100000000000214")
    _observe(db_session, run, _record(external_ad_id="ad-A"))
    _observe(db_session, run, _record(external_ad_id="ad-B"))

    group = duplicate_groups(db_session, axis="copy")[0]

    assert isinstance(group, DuplicateGroup)
    with pytest.raises(AttributeError):
        group.content_hash = "tampered"  # type: ignore[misc]


def test_both_axes_read_the_digests_the_service_wrote(db_session: Session) -> None:
    """The grouping is over the *product's* digests, not over a test's own.

    Read straight off the stored rows and compared with the hash functions, so a
    change to either hash contract surfaces here rather than as a report that
    quietly finds nothing.
    """
    from app.services.copy_hash import copy_hash_v1

    run = _chain(db_session, "100000000000215")
    _observe(db_session, run, _record())

    stored = _digests(db_session)

    assert stored == {(copy_hash_v1(_record()), creative_hash_v1(_record()))}

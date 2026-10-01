"""S2.4 creative references: schema, persistence, integrity and security.

Every claim here is about what is *recorded*, not about bytes -- because S2.4
acquires none. `AGENTS.md` section 12 forbids media byte downloads in S0-S3, so the
interesting properties are about identity, sharing, idempotence and the meaning of
a NULL.

`integration`, because most of it is a database question: an upsert resolving, a
unique constraint firing, a `CHECK` refusing, a foreign key refusing an orphan, and
a rollback unwinding a link written alongside a snapshot.

Writes are real and nothing is committed -- `db_session` binds every session to a
connection inside an outer transaction that is always rolled back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models.ads import Ad, AdSnapshot, SeenInRun
from app.models.media import AdSnapshotMedia, MediaAsset
from app.models.runs import (
    CollectionRun,
    CollectionRunStatus,
    ProviderRun,
    ProviderRunStatus,
    RawResponse,
)
from app.providers.data.models import AdFormat, MediaRef, RawAdRecord
from app.providers.data.provenance import DataOrigin
from app.services.ad_persistence import ObservedRecord, persist_observations
from app.services.content_hash import content_hash_v1
from app.services.creative_hash import creative_hash_v1
from app.services.media_references import link_snapshot_media

pytestmark = pytest.mark.integration

BASE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
PROVIDER = "mock"


# ============================================================
# Building a chain
# ============================================================


def _ad(session: Session, meta_ad_id: str) -> Ad:
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


def _run(session: Session, page_id: uuid.UUID, *, offset_days: int = 0) -> CollectionRun:
    """A complete run. `offset_days` moves its finish time so a sequence of runs is
    ordered, which is what `last_seen_at` and the creative walk depend on."""
    at = BASE + timedelta(days=offset_days)
    row = CollectionRun(
        facebook_page_id=page_id,
        provider=PROVIDER,
        country="IN",
        data_origin=DataOrigin.third_party,
        status=CollectionRunStatus.COMPLETE,
        started_at=at,
        finished_at=at + timedelta(seconds=30),
    )
    session.add(row)
    session.flush()
    return row


def _observe(
    session: Session,
    *,
    run: CollectionRun,
    page_id: uuid.UUID,
    record: RawAdRecord,
) -> tuple[Ad, AdSnapshot]:
    """Persist one observation exactly as the orchestrator does.

    Goes through the real `persist_observations`, so the media rows under test are
    written by the production write path and not by a test's own arrangement of
    them. A test that built the rows itself would pass even if the write path were
    never called.
    """
    call = ProviderRun(
        collection_run_id=run.id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=run.started_at,
        finished_at=run.finished_at,
        request_meta={
            "provider": PROVIDER,
            "origin": DataOrigin.third_party.value,
            "country": "IN",
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

    result = persist_observations(
        session,
        run_id=run.id,
        observations=[ObservedRecord(record=record, raw_response_id=response.id)],
        provider=PROVIDER,
        data_origin=DataOrigin.third_party,
        page_id=page_id,
        country="IN",
    )[0]
    session.commit()
    ad = session.get(Ad, result.ad_id)
    snapshot = session.get(AdSnapshot, result.snapshot_id)
    # Both were just written by the call above, so a `None` here means the write
    # path did not do what it claims -- worth failing on rather than typing past.
    assert ad is not None and snapshot is not None
    return ad, snapshot


def _record(**overrides: Any) -> RawAdRecord:
    fields: dict[str, Any] = {
        "external_ad_id": "ad-0001",
        "platforms": ("facebook",),
        "countries": ("IN",),
        "ad_status": "active",
        "primary_text": "Buy now",
        "display_format": AdFormat.IMAGE,
        "media": (
            MediaRef(
                provider_key="mock-media-0001-a",
                source_url="https://cdn.example.invalid/a.png",
                mime="image/png",
                width=1080,
                height=1080,
            ),
        ),
    }
    fields.update(overrides)
    return RawAdRecord(**fields)


def _assets(session: Session) -> list[MediaAsset]:
    """Every asset, by key. Expired first, so a read is never a stale cached object.

    SQLAlchemy returns the *existing* identity-mapped instance for a `select` and
    does not refresh attributes it has already loaded. Without this, a test that
    re-observed an asset and then read it back would see the pre-write values --
    and would pass while asserting nothing at all.
    """
    session.expire_all()
    return list(session.execute(select(MediaAsset).order_by(MediaAsset.provider_key)).scalars())


def _links(session: Session) -> list[AdSnapshotMedia]:
    """Every link, in provider order (`position`). Expired first, as above."""
    session.expire_all()
    return list(
        session.execute(select(AdSnapshotMedia).order_by(AdSnapshotMedia.position)).scalars()
    )


def _page(session: Session, page_id: str) -> uuid.UUID:
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
# Schema
# ============================================================


def test_one_asset_per_provider_key_pair(db_session: Session) -> None:
    """The identity is the pair, and two references to it share one row.

    This is the sharing case the corpus proves: `mock-media-shared-01` is referenced
    by two different ads. An ad-owned asset table would have to duplicate it or lie
    about ownership.
    """
    page_id = _page(db_session, "100000000000401")
    shared = MediaRef(provider_key="mock-media-shared-01")

    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(external_ad_id="ad-A", media=(shared,)),
    )
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=1),
        page_id=page_id,
        record=_record(external_ad_id="ad-B", media=(shared,)),
    )

    assets = _assets(db_session)
    assert len(assets) == 1, "a shared asset was duplicated"
    assert assets[0].provider_key == "mock-media-shared-01"
    assert len(_links(db_session)) == 2, "each observation needs its own link"


def test_the_same_key_from_two_providers_is_two_assets(db_session: Session) -> None:
    """A bare `provider_key` would let one provider overwrite another's asset."""
    ad = _ad(db_session, "ad-0001")

    for provider in ("mock", "other"):
        db_session.execute(
            text(
                "INSERT INTO media_assets (id, provider, provider_key, first_seen_at, "
                "last_seen_at) VALUES (:id, :provider, 'shared-key', :now, :now)"
            ),
            {"id": uuid.uuid4(), "provider": provider, "now": BASE},
        )
    db_session.flush()

    providers = {asset.provider for asset in _assets(db_session)}
    assert providers == {"mock", "other"}
    assert ad.id is not None


def test_the_database_refuses_a_duplicate_provider_key_pair(db_session: Session) -> None:
    """The unique constraint, proven by writing rather than by reading metadata."""
    _run(db_session, page_id=_page(db_session, "100000000000403"), offset_days=0)
    first = MediaAsset(
        provider=PROVIDER,
        provider_key="dup-key",
        first_seen_at=BASE,
        last_seen_at=BASE,
    )
    db_session.add(first)
    db_session.flush()

    with pytest.raises(IntegrityError) as caught:
        db_session.add(
            MediaAsset(
                provider=PROVIDER,
                provider_key="dup-key",
                first_seen_at=BASE,
                last_seen_at=BASE,
            )
        )
        db_session.flush()

    assert "uq_media_assets_provider_key" in str(caught.value)
    db_session.rollback()


def test_a_null_storage_key_is_accepted(db_session: Session) -> None:
    """The S2.4 state, and the reason the column exists at all.

    NULL means *a reference is held, the bytes have not been acquired*. It is not
    "unknown", not "pending", not zero -- and it is the only honest value, because
    `AGENTS.md` section 12 forbids acquiring the bytes in S0-S3.
    """
    page_id = _page(db_session, "100000000000404")
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(),
    )

    asset = _assets(db_session)[0]
    assert asset.storage_key is None
    assert asset.byte_size is None


def test_every_asset_written_by_s24_has_a_null_storage_key(db_session: Session) -> None:
    """Asserted across the write path, not just one row.

    A future writer that filled `storage_key` without bytes would be filing a
    digest for content it does not have, and every later comparison would be a
    comparison of lies.
    """
    page_id = _page(db_session, "100000000000405")
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(
            media=(
                MediaRef(provider_key="m-1"),
                MediaRef(provider_key="m-2", source_url="https://cdn.example.invalid/2.png"),
            )
        ),
    )

    assert _assets(db_session)
    assert all(asset.storage_key is None for asset in _assets(db_session))


def test_a_valid_content_key_is_accepted(db_session: Session) -> None:
    """The `CHECK` must permit a real 64-hex key for a future byte-acquisition
    checkpoint, or the column would have to be dropped and re-added then."""
    db_session.execute(
        text(
            "INSERT INTO media_assets (id, provider, provider_key, storage_key, "
            "first_seen_at, last_seen_at) VALUES (:id, 'mock', 'k', :key, :now, :now)"
        ),
        {"id": uuid.uuid4(), "key": "a" * 64, "now": BASE},
    )
    db_session.flush()
    assert len(_assets(db_session)) == 1, "a valid content key was not accepted"


@pytest.mark.parametrize(
    "key",
    [
        "A" * 64,  # uppercase: content_key is lowercase hex only
        "a" * 63,  # too short
        "a" * 65,  # too long
        "z" * 64,  # not hex
        "../../etc/passwd",  # a path, which content_key() refuses
        "https://example.invalid/a.png",
        "",
    ],
)
def test_an_invalid_storage_key_is_refused(db_session: Session, key: str) -> None:
    """The same shapes `services/media.py::content_key` refuses.

    `content_key` is the only place a caller-supplied string becomes a path, and
    the constraint here mirrors it at the database so a malformed key cannot be
    stored even if a future writer computes one wrongly.
    """
    with pytest.raises((IntegrityError, DataError)) as caught:
        db_session.execute(
            text(
                "INSERT INTO media_assets (id, provider, provider_key, storage_key, "
                "first_seen_at, last_seen_at) VALUES (:id, 'mock', :key, :bad, :now, :now)"
            ),
            {"id": uuid.uuid4(), "key": f"k-{len(key)}-{key[:8]}", "bad": key, "now": BASE},
        )
    # A value longer than 64 characters is refused by the column type before the
    # `CHECK` is reached, so `DataError` is the honest expectation there; every
    # other shape is refused by the constraint itself.
    if len(key) != 65:
        assert "storage_key_is_content_key" in str(caught.value)
    db_session.rollback()


def test_duration_seconds_accepts_an_exact_decimal(db_session: Session) -> None:
    """NUMERIC, matching `MediaRef` and the value S2.1 stores in `normalized`.

    JSONB has no decimal type, so the snapshot keeps the exact string. A float here
    could no longer be said to be the provider's measurement -- 12.50 and 12.5 would
    be indistinguishable.
    """
    page_id = _page(db_session, "100000000000406")
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=(MediaRef(provider_key="vid-1", duration_seconds=Decimal("12.50")),)),
    )

    asset = _assets(db_session)[0]
    assert asset.duration_seconds == Decimal("12.50")
    assert str(asset.duration_seconds) == "12.50", "the exact decimal form was lost"


def test_a_link_cannot_duplicate_its_pair(db_session: Session) -> None:
    """One snapshot references one asset once."""
    page_id = _page(db_session, "100000000000407")
    _ad_row, snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(),
    )
    asset = _assets(db_session)[0]

    db_session.add(AdSnapshotMedia(ad_snapshot_id=snapshot.id, media_asset_id=asset.id))
    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "uq_ad_snapshot_media_snapshot_asset" in str(caught.value)
    db_session.rollback()


@pytest.mark.parametrize("position", [None, 0, 1, 32767])
def test_a_valid_position_is_accepted(db_session: Session, position: int | None) -> None:
    """NULL, zero, and the top of the `SMALLINT` range.

    Uses a *second* asset, because the write path has already linked the snapshot's
    first one and the pair is unique -- inserting the same pair again would prove
    the uniqueness constraint rather than the position check.
    """
    page_id = _page(db_session, "100000000000408")
    _ad_row, snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(),
    )
    extra = MediaAsset(
        provider=PROVIDER,
        provider_key=f"pos-probe-{position}",
        first_seen_at=BASE,
        last_seen_at=BASE,
    )
    db_session.add(extra)
    db_session.flush()

    db_session.execute(
        text(
            "INSERT INTO ad_snapshot_media (id, ad_snapshot_id, media_asset_id, position) "
            "VALUES (:id, :snap, :asset, :pos)"
        ),
        {"id": uuid.uuid4(), "snap": snapshot.id, "asset": extra.id, "pos": position},
    )
    db_session.flush()


def test_a_negative_position_is_refused(db_session: Session) -> None:
    """A position below zero would mean nothing -- it indexes from zero."""
    page_id = _page(db_session, "100000000000409")
    _ad_row, snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(),
    )
    asset = _assets(db_session)[0]

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                "INSERT INTO ad_snapshot_media (id, ad_snapshot_id, media_asset_id, position) "
                "VALUES (:id, :snap, :asset, -1)"
            ),
            {"id": uuid.uuid4(), "snap": snapshot.id, "asset": asset.id},
        )
    assert "position_non_negative" in str(caught.value)
    db_session.rollback()


def test_both_link_foreign_keys_enforce_restrict(db_session: Session) -> None:
    """An orphan on either side is refused, and the deletion is refused too."""
    _run(db_session, page_id=_page(db_session, "100000000000410"), offset_days=0)
    asset = MediaAsset(
        provider=PROVIDER, provider_key="lonely", first_seen_at=BASE, last_seen_at=BASE
    )
    db_session.add(asset)
    db_session.flush()

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                "INSERT INTO ad_snapshot_media (id, ad_snapshot_id, media_asset_id) "
                "VALUES (:id, :snap, :asset)"
            ),
            {"id": uuid.uuid4(), "snap": uuid.uuid4(), "asset": asset.id},
        )
    assert "fk_ad_snapshot_media_ad_snapshot_id" in str(caught.value)
    db_session.rollback()

    page_id = _page(db_session, "100000000000411")
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(),
    )
    linked = _assets(db_session)[0]

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(text("DELETE FROM media_assets WHERE id = :id"), {"id": linked.id})
    assert "fk_ad_snapshot_media_media_asset_id" in str(caught.value)
    db_session.rollback()


def test_an_asset_cannot_be_deleted_while_a_snapshot_references_it(db_session: Session) -> None:
    """RESTRICT, not CASCADE: a delete would take the observation relationship away."""
    page_id = _page(db_session, "100000000000412")
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(),
    )
    asset = _assets(db_session)[0]

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(text("DELETE FROM media_assets WHERE id = :id"), {"id": asset.id})
    assert "fk_ad_snapshot_media_media_asset_id" in str(caught.value)
    db_session.rollback()


# ============================================================
# Persistence
# ============================================================


def test_provider_metadata_survives_onto_the_asset(db_session: Session) -> None:
    """Reported dimensions land on the asset, as reported.

    A hand-edited row claiming a zero-pixel or negative-length asset would be a
    measurement nobody reported, so both are checked as well.
    """
    page_id = _page(db_session, "100000000000413")
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(
            media=(
                MediaRef(
                    provider_key="m-meta",
                    source_url="https://cdn.example.invalid/m.png",
                    mime="image/png",
                    width=640,
                    height=480,
                ),
            )
        ),
    )

    asset = _assets(db_session)[0]
    assert asset.mime == "image/png"
    assert (asset.width, asset.height) == (640, 480)
    assert asset.source_url == "https://cdn.example.invalid/m.png"

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO media_assets (id, provider, provider_key, width, first_seen_at, "
                "last_seen_at) VALUES (:id, 'mock', 'zero-w', 0, :now, :now)"
            ),
            {"id": uuid.uuid4(), "now": BASE},
        )
    db_session.rollback()


def test_last_seen_advances_and_first_seen_does_not(db_session: Session) -> None:
    """The two observation times behave differently on purpose.

    `first_seen_at` is never rewritten: it means first, and an upsert that refreshed
    it would erase the fact that we have known about this asset since a specific
    moment.
    """
    page_id = _page(db_session, "100000000000414")
    ref = MediaRef(provider_key="recurring")

    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(external_ad_id="ad-A", media=(ref,)),
    )
    first_before = _assets(db_session)[0].first_seen_at

    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=1),
        page_id=page_id,
        record=_record(external_ad_id="ad-B", media=(ref,)),
    )
    asset = _assets(db_session)[0]

    assert asset.first_seen_at == first_before, "first_seen_at moved"
    assert asset.last_seen_at >= first_before


def test_a_changed_provider_key_creates_a_distinct_asset(db_session: Session) -> None:
    """Two keys might be the same bytes; without the bytes, merging them is a guess.

    Guessing would be a fabricated finding. They stay separate, and that is
    *consistent* rather than contradictory: `creative_hash` v1 hashed provider keys,
    and the provider key did change.
    """
    page_id = _page(db_session, "100000000000415")
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=(MediaRef(provider_key="key-v1"),)),
    )
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=1),
        page_id=page_id,
        record=_record(media=(MediaRef(provider_key="key-v2"),)),
    )

    assert {a.provider_key for a in _assets(db_session)} == {"key-v1", "key-v2"}


def test_an_ad_with_no_media_writes_nothing(db_session: Session) -> None:
    """Zero media is a real observation, not a missing one.

    Two of the nine corpus ads carry no media at all. Manufacturing a row for them
    would invent a creative nobody reported.
    """
    page_id = _page(db_session, "100000000000416")
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=()),
    )

    assert _assets(db_session) == []
    assert _links(db_session) == []


def _positions(session: Session) -> dict[str, int | None]:
    """`provider_key -> position`, read with a join rather than by zipping two lists.

    Zipping the asset list against the link list pairs rows *by position in two
    independently ordered queries*, which silently means the wrong thing the
    moment the two orders disagree -- and they disagree exactly when this
    checkpoint's behaviour is interesting. The join cannot be wrong that way.
    """
    session.expire_all()
    rows = session.execute(
        select(MediaAsset.provider_key, AdSnapshotMedia.position).join(
            AdSnapshotMedia, AdSnapshotMedia.media_asset_id == MediaAsset.id
        )
    ).all()
    return {str(key): position for key, position in rows}


def test_first_seen_at_survives_a_deliberately_wrong_value(db_session: Session) -> None:
    """`first_seen_at` is never rewritten, proven by trying to rewrite it.

    A test that only compares two `now()` values cannot detect an upsert that
    refreshes the column: both writes land in the same clock second, so the
    mutation is invisible. Planting a sentinel from the past and checking it
    survives makes the property observable, which is the only kind of assertion
    that actually pins it.
    """
    page_id = _page(db_session, "100000000000425")
    ref = MediaRef(provider_key="sentinel")
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=(ref,)),
    )

    sentinel = BASE - timedelta(days=900)
    asset = _assets(db_session)[0]
    asset.first_seen_at = sentinel
    db_session.flush()
    db_session.commit()

    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=1),
        page_id=page_id,
        record=_record(media=(ref,)),
    )

    db_session.expire_all()
    assert _assets(db_session)[0].first_seen_at == sentinel, "first_seen_at was rewritten"
    assert _assets(db_session)[0].last_seen_at >= BASE, "last_seen_at did not advance"


def test_a_provider_reorder_does_not_rewrite_an_existing_position(db_session: Session) -> None:
    """A reordered media tuple must NOT move the positions of an existing snapshot.

    This is the case that decides whether `position` can be re-derived at all.
    `content_hash` v1 **sorts** media keys, so a provider that reshuffles its media
    tuple produces an identical digest and therefore **the same snapshot** -- no new
    evidence row is warranted, because the ad genuinely did not change.

    That is exactly why `position` must be frozen. `ad_snapshots.normalized` is
    append-only and still holds the order the snapshot was created with; re-deriving
    `position` from a later, reordered observation would leave two tables making
    contradictory claims about one immutable snapshot. The snapshot's own stored
    order wins, so the link must agree with it.
    """
    page_id = _page(db_session, "100000000000426")
    forward = (MediaRef(provider_key="ord-a"), MediaRef(provider_key="ord-b"))

    _first_ad, first_snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=forward),
    )
    captured = _positions(db_session)
    assert captured == {"ord-a": 0, "ord-b": 1}

    _second_ad, second_snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=1),
        page_id=page_id,
        # Same keys, reversed provider order. Same digests, same snapshot.
        record=_record(media=tuple(reversed(forward))),
    )

    assert second_snapshot.id == first_snapshot.id, "a reorder minted a new snapshot"
    assert _positions(db_session) == captured, "a later observation rewrote position"
    assert len(_links(db_session)) == 2, "the reorder duplicated links"


def test_position_agrees_with_the_normalized_json_of_its_own_snapshot(db_session: Session) -> None:
    """The relational ordinal and the stored JSON describe the same thing.

    Read as the invariant it is: for every link, `position` is the index of that
    asset's `provider_key` inside its snapshot's own `normalized` media tuple. If
    this ever fails, one of the two has been written from a different observation
    than the other, and the snapshot's evidence has become ambiguous.
    """
    page_id = _page(db_session, "100000000000427")
    media = (
        MediaRef(provider_key="consist-c"),
        MediaRef(provider_key="consist-a"),
        MediaRef(provider_key="consist-b"),
    )

    _ad, snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=media),
    )

    stored_order = [entry["provider_key"] for entry in snapshot.normalized["media"]]
    assert stored_order == ["consist-c", "consist-a", "consist-b"], (
        "the snapshot did not store provider order verbatim"
    )

    # Deliberately not provider_key order, so this can only pass if `position`
    # really is the stored order rather than something alphabetically similar.
    db_session.expire_all()
    rows = db_session.execute(
        select(AdSnapshotMedia.position, MediaAsset.provider_key)
        .join(MediaAsset, MediaAsset.id == AdSnapshotMedia.media_asset_id)
        .where(AdSnapshotMedia.ad_snapshot_id == snapshot.id)
        .order_by(AdSnapshotMedia.position)
    ).all()
    assert [key for _position, key in rows] == stored_order
    assert [position for position, _key in rows] == [0, 1, 2]


def test_position_is_written_once_and_never_rewritten(db_session: Session) -> None:
    """The locked rule, pinned at the public boundary.

    `link_snapshot_media` is called again for a snapshot that already has links,
    carrying a different provider order -- the shape a re-entrant or otherwise
    conflicting write would take. The existing `position` must survive it.

    This is deliberately a second line of defence rather than a restatement of the
    previous test. Gating the link write on `snapshot_created` already prevents a
    later *observation* from reaching the link at all, so with that gate in place
    the conflict arm of the upsert is unreachable in production. It is kept because
    the rule is stronger than "the caller behaves": one row, one position, written
    once. This test is what stops that second defence from being quietly removed,
    which the observation-level tests above would not notice.
    """
    page_id = _page(db_session, "100000000000429")
    forward = (MediaRef(provider_key="once-a"), MediaRef(provider_key="once-b"))

    _ad, snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=forward),
    )
    captured = _positions(db_session)
    assert captured == {"once-a": 0, "once-b": 1}

    link_snapshot_media(
        db_session,
        provider=PROVIDER,
        ad_snapshot_id=snapshot.id,
        media=tuple(reversed(forward)),
        snapshot_created=True,
    )
    db_session.flush()

    assert _positions(db_session) == captured, "a second link write rewrote position"
    assert len(_links(db_session)) == 2, "the second write duplicated links"


def test_an_unchanged_observation_manufactures_no_link_for_a_pre_s24_snapshot(
    db_session: Session,
) -> None:
    """A snapshot from before S2.4 gains asset recency but never a backfilled link.

    The snapshot here is built by hand with the *real* `content_hash` for the record
    the next observation will carry, so that observation matches it and resolves to
    this pre-existing snapshot. That is the case the "links only when a snapshot is
    created" gate exists for: manufacturing links for a snapshot nobody re-created
    would write history S2.4 was told not to write, and would attach an order taken
    from a *later* observation to a snapshot whose own `normalized` order came from
    an earlier one.

    The asset row still appears, because the asset genuinely was observed again.
    """
    page_id = _page(db_session, "100000000000430")
    ad = _ad(db_session, "pre-s24-ad")
    record = _record(external_ad_id="pre-s24-ad", media=(MediaRef(provider_key="pre-s24-media"),))
    run = _run(db_session, page_id=page_id, offset_days=0)

    call = ProviderRun(
        collection_run_id=run.id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=run.started_at,
        finished_at=run.finished_at,
        request_meta={
            "provider": PROVIDER,
            "origin": DataOrigin.third_party.value,
            "country": "IN",
            "requested_at": (run.started_at or BASE).isoformat(),
            "cursor": None,
        },
        http_status=200,
    )
    db_session.add(call)
    db_session.flush()
    response = RawResponse(provider_run_id=call.id, payload={"ads": []})
    db_session.add(response)
    db_session.flush()

    # A snapshot exactly as S2.1 would have written it, before S2.4 existed.
    legacy = AdSnapshot(
        ad_id=ad.id,
        collection_run_id=run.id,
        raw_ref=response.id,
        content_hash=content_hash_v1(record),
        copy_hash=None,
        creative_hash=None,
        normalized=record.model_dump(mode="json"),
    )
    db_session.add(legacy)
    db_session.flush()
    ad.latest_snapshot_id = legacy.id
    db_session.add(SeenInRun(ad_id=ad.id, collection_run_id=run.id, snapshot_id=legacy.id))
    db_session.flush()
    db_session.commit()

    # Re-observe the identical record in a later run.
    _observed_ad, observed_snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=1),
        page_id=page_id,
        record=record,
    )

    assert observed_snapshot.id == legacy.id, "an identical record minted a new snapshot"
    assert _links(db_session) == [], "a link was manufactured for a pre-S2.4 snapshot"
    assert len(_assets(db_session)) == 1, "asset recency should still be recorded"
    assert _assets(db_session)[0].last_seen_at is not None


def test_a_changed_key_set_makes_a_new_snapshot_which_takes_new_positions(
    db_session: Session,
) -> None:
    """Adding a key moves `content_hash`, so S2.1 writes a new snapshot and new ordinals.

    The counterpart to the reorder case: a genuinely different media set is a
    different creative and gets its own evidence row, so its positions are captured
    fresh rather than being frozen onto the old snapshot.
    """
    page_id = _page(db_session, "100000000000428")
    two = (MediaRef(provider_key="set-a"), MediaRef(provider_key="set-b"))

    _ad_one, first_snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=two),
    )
    assert _positions(db_session) == {"set-a": 0, "set-b": 1}

    _ad_two, second_snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=1),
        page_id=page_id,
        # A new key at the front: the set changed, so the digest must change.
        record=_record(media=(MediaRef(provider_key="set-new"), *two)),
    )

    assert second_snapshot.id != first_snapshot.id, "a new key did not make a snapshot"
    assert _positions(db_session) == {"set-a": 1, "set-b": 2, "set-new": 0}


def test_provider_order_is_preserved_in_position(db_session: Session) -> None:
    """`position` records provider order, and never feeds a digest.

    `creative_hash` v1 *sorts* the keys before hashing, so order cannot affect it --
    and this asserts both halves: the positions match the provider order, and the
    digest is unchanged by a reorder.
    """
    page_id = _page(db_session, "100000000000417")
    forward = (MediaRef(provider_key="z-last"), MediaRef(provider_key="a-first"))

    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=forward),
    )
    positions = [link.position for link in _links(db_session)]

    assert positions == [0, 1]
    keys = [asset.provider_key for asset in _assets(db_session)]
    assert keys == ["a-first", "z-last"], "assets are ordered by key, position by provider order"
    # And the digest is order-independent, which is why position cannot move it.
    assert creative_hash_v1(_record(media=forward)) == creative_hash_v1(
        _record(media=tuple(reversed(forward)))
    )


def test_an_unchanged_ad_seen_again_still_refreshes_its_asset(db_session: Session) -> None:
    """The write path runs on *every* observation, not only on a new snapshot.

    An unchanged ad seen again is a fresh observation of its assets, and
    `last_seen_at` has to move. Gating media on `created_snapshot` would make an
    asset's recency a fact about when the copy last changed.

    Note **one** link, not two. The content did not change, so S2.1 correctly wrote
    no second snapshot, and both runs therefore resolved to the *same* snapshot --
    which is precisely why the link is keyed on (snapshot, asset). The record of
    "run 2 observed this asset" lives in `seen_in_run`; the link records what the
    snapshot contained. Asserted here because the alternative reading -- two
    observations must mean two links -- would have put the link table in conflict
    with S2.1's snapshot cardinality rule.
    """
    page_id = _page(db_session, "100000000000418")
    ref = MediaRef(provider_key="seen-again")

    first_ad, first_snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=(ref,)),
    )
    before = _assets(db_session)[0].last_seen_at

    second_ad, second_snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=1),
        page_id=page_id,
        record=_record(media=(ref,)),
    )

    assert second_snapshot.id == first_snapshot.id, "unchanged content made a new snapshot"
    assert second_ad.id == first_ad.id
    assert len(_assets(db_session)) == 1
    assert len(_links(db_session)) == 1, "one snapshot references one asset once"
    assert _assets(db_session)[0].last_seen_at >= before
    # And the second run *did* record its sighting, which is where that lives.
    sightings = db_session.execute(
        text("SELECT count(1) FROM seen_in_run WHERE ad_id = :ad"), {"ad": first_ad.id}
    ).scalar_one()
    assert sightings == 2, "the second observation was not recorded at all"


def test_reprocessing_the_same_run_is_idempotent(db_session: Session) -> None:
    """Case C: a reprocessed run adds no duplicate asset and no duplicate link."""
    page_id = _page(db_session, "100000000000419")
    run = _run(db_session, page_id=page_id, offset_days=0)
    record = _record(media=(MediaRef(provider_key="idem-1"), MediaRef(provider_key="idem-2")))

    _observe(db_session, run=run, page_id=page_id, record=record)
    first_counts = (len(_assets(db_session)), len(_links(db_session)))

    call = ProviderRun(
        collection_run_id=run.id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=run.started_at,
        finished_at=run.finished_at,
        request_meta={
            "provider": PROVIDER,
            "origin": DataOrigin.third_party.value,
            "country": "IN",
            "requested_at": (run.started_at or BASE).isoformat(),
            "cursor": None,
        },
        http_status=200,
    )
    db_session.add(call)
    db_session.flush()
    response = RawResponse(provider_run_id=call.id, payload={"ads": []})
    db_session.add(response)
    db_session.flush()

    result = persist_observations(
        db_session,
        run_id=run.id,
        observations=[ObservedRecord(record=record, raw_response_id=response.id)],
        provider=PROVIDER,
        data_origin=DataOrigin.third_party,
        page_id=page_id,
        country="IN",
    )[0]
    db_session.commit()

    assert (len(_assets(db_session)), len(_links(db_session))) == first_counts
    assert _link_for_snapshot(db_session, result.snapshot_id) is not None


def _link_for_snapshot(session: Session, snapshot_id: uuid.UUID) -> AdSnapshotMedia | None:
    return (
        session.execute(
            select(AdSnapshotMedia).where(AdSnapshotMedia.ad_snapshot_id == snapshot_id)
        )
        .scalars()
        .first()
    )


# ============================================================
# Integrity with the append-only evidence
# ============================================================


def test_media_rows_never_change_the_snapshot_count(db_session: Session) -> None:
    """S2.4 writes two new tables and adds no `ad_snapshots` row."""
    page_id = _page(db_session, "100000000000420")
    before = db_session.execute(text("SELECT count(1) FROM ad_snapshots")).scalar_one()

    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=(MediaRef(provider_key="counted"),)),
    )

    after = db_session.execute(text("SELECT count(1) FROM ad_snapshots")).scalar_one()
    assert after == before + 1, "exactly the snapshot the observation created"
    assert len(_assets(db_session)) == 1


def test_a_rolled_back_media_write_takes_the_snapshot_with_it(db_session: Session) -> None:
    """A failed link write rolls back the asset row with it, not just the link.

    The asset row, the link and the snapshot are one transaction, so a failure
    anywhere in the media write must leave no trace of any of them. A dangling
    link is impossible by foreign key; a *surviving asset* whose link was rolled
    back is the subtler failure, and it is what this asserts.

    Driven by a real constraint violation rather than a synthetic exception: an
    orphan `ad_snapshot_id` is exactly what a media persistence failure looks
    like to the database, and it fires before any test-invented error could.
    """
    snapshot_count = db_session.execute(text("SELECT count(1) FROM ad_snapshots")).scalar_one()

    doomed = MediaAsset(
        provider=PROVIDER,
        provider_key="doomed",
        first_seen_at=BASE,
        last_seen_at=BASE,
    )
    db_session.add(doomed)
    db_session.flush()
    assert len(_assets(db_session)) == 1, "the asset exists before the failure"

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                "INSERT INTO ad_snapshot_media (id, ad_snapshot_id, media_asset_id) "
                "VALUES (:id, :snap, :asset)"
            ),
            {"id": uuid.uuid4(), "snap": uuid.uuid4(), "asset": doomed.id},
        )
    assert "fk_ad_snapshot_media_ad_snapshot_id" in str(caught.value)

    db_session.rollback()

    assert (
        db_session.execute(text("SELECT count(1) FROM ad_snapshots")).scalar_one() == snapshot_count
    ), "a snapshot survived a rolled-back media write"
    assert _assets(db_session) == [], "an asset row outlived its rolled-back link"
    assert _links(db_session) == [], "a dangling link survived"


def test_the_append_only_trigger_is_untouched_by_s24(db_session: Session) -> None:
    """The evidence table is still protected after S2.4.

    S2.4 adds tables beside the evidence, not to it -- and this asserts the guard is
    still armed rather than trusting that nothing tried.
    """
    page_id = _page(db_session, "100000000000422")
    _ad_row, snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=_record(media=(MediaRef(provider_key="guarded"),)),
    )

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text("UPDATE ad_snapshots SET ad_status = 'tampered' WHERE id = :id"),
            {"id": snapshot.id},
        )
    assert "append-only" in str(caught.value)
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.execute(text("DELETE FROM ad_snapshots WHERE id = :id"), {"id": snapshot.id})
    db_session.rollback()


def test_media_writes_leave_the_persisted_hashes_byte_for_byte_unchanged(
    db_session: Session,
) -> None:
    """The digests *stored on the snapshot* survive the S2.4 media writes untouched.

    An earlier version of this test recomputed the three digests from the same
    immutable `RawAdRecord` before and after the writes. That could not fail for
    any reason: the hash functions are pure and the record is frozen, so the
    assertion was true no matter what the media path did. It is replaced here by
    the claim actually worth making -- the values **persisted in the
    `ad_snapshots` row** are unchanged after media rows are written and the ad is
    re-observed.

    Reading the row back is what makes it a real test: a future writer that
    recomputed a digest from the current observation, or that updated a snapshot
    while touching media, would be caught here and would not have been caught
    before.
    """
    page_id = _page(db_session, "100000000000423")
    record = _record(media=(MediaRef(provider_key="hashed"),))

    _ad, snapshot = _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=0),
        page_id=page_id,
        record=record,
    )

    def stored_hashes() -> tuple[str, str | None, str | None]:
        """The three digests as they exist in the database right now."""
        db_session.expire_all()
        row = db_session.get(AdSnapshot, snapshot.id)
        assert row is not None
        return row.content_hash, row.copy_hash, row.creative_hash

    before = stored_hashes()
    assert all(before), "the snapshot stored no digests to protect"

    # Re-observe the same ad in a later run: asset recency advances, no new
    # snapshot is written, and this is the path most likely to touch a row.
    _observe(
        db_session,
        run=_run(db_session, page_id=page_id, offset_days=1),
        page_id=page_id,
        record=record,
    )

    assert stored_hashes() == before, "a media write changed a persisted digest"
    assert len(_assets(db_session)) == 1, "the media rows this run should still exist"


# ============================================================
# Historical
# ============================================================


def test_the_migration_backfilled_nothing(db_session: Session) -> None:
    """A snapshot with media in its `normalized` JSON and no links predates S2.4.

    This is the state a real database would be in: history collected before the
    revision, with every media reference present in the stored JSONB and no
    `ad_snapshot_media` row. The migration did not -- and could not -- manufacture
    links, because `ad_snapshots` is append-only.
    """
    page_id = _page(db_session, "100000000000424")
    ad = _ad(db_session, "legacy-ad")
    run = _run(db_session, page_id=page_id, offset_days=0)
    call = ProviderRun(
        collection_run_id=run.id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=run.started_at,
        finished_at=run.finished_at,
        request_meta={
            "provider": PROVIDER,
            "origin": DataOrigin.third_party.value,
            "country": "IN",
            "requested_at": (run.started_at or BASE).isoformat(),
            "cursor": None,
        },
        http_status=200,
    )
    db_session.add(call)
    db_session.flush()
    response = RawResponse(provider_run_id=call.id, payload={"ads": []})
    db_session.add(response)
    db_session.flush()

    legacy = AdSnapshot(
        ad_id=ad.id,
        collection_run_id=run.id,
        raw_ref=response.id,
        content_hash="0" * 64,
        copy_hash=None,
        creative_hash=None,
        # The media reference is right here, exactly as S2.1 stored it.
        normalized={
            "external_ad_id": "legacy-ad",
            "media": [{"provider_key": "legacy-media-1", "source_url": None}],
        },
    )
    db_session.add(legacy)
    db_session.flush()
    db_session.add(SeenInRun(ad_id=ad.id, collection_run_id=run.id, snapshot_id=legacy.id))
    db_session.flush()

    assert _assets(db_session) == [], "the migration manufactured an asset row"
    assert _links(db_session) == [], "the migration manufactured a link row"

    stored = db_session.get(AdSnapshot, legacy.id)
    assert stored is not None, "the pre-S2.4 snapshot went missing"
    assert stored.normalized["media"][0]["provider_key"] == "legacy-media-1", (
        "the historical normalized JSON was rewritten"
    )
    assert stored.copy_hash is None and stored.creative_hash is None

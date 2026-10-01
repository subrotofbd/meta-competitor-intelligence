"""Turning `RawAdRecord.media` into rows, when a new snapshot is written.

## What this does and, more importantly, what it does not

It writes two tables: `media_assets` and `ad_snapshot_media`. It is called from
`ad_persistence._persist_one` immediately after a new snapshot is flushed, inside
the **same transaction**, so a link can never exist without the snapshot it points
at and a failed media write rolls the snapshot back with it.

It downloads nothing. It calls no `MediaStore`. There are no bytes in S2.4 --
`AGENTS.md` section 12 forbids acquiring them in S0-S3 -- so there is nothing for a
content-addressed store to hold. `storage_key` and `byte_size` are written as NULL
and mean exactly one thing: *a reference is held, the bytes have not been acquired*.

`source_url` is stored as the provider gave it and is **never requested**. Not
here, not later in this checkpoint, not by a helper that looks like it might.

## Idempotence, in all five cases

- **Same `(provider, provider_key)` in many snapshots** -> one `media_assets` row,
  `last_seen_at` advancing; one link row per snapshot.
- **Same key on two different ads** -> one `media_assets` row, two links. The
  corpus has exactly this case (`mock-media-shared-01`).
- **A reprocessed run** -> no duplicate asset row, no duplicate link row. Both
  writes are upserts on a unique constraint, so reprocessing is safe rather than
  merely tolerated.
- **A changed `provider_key`** -> a *different* asset row. Two keys might name the
  same bytes; without the bytes there is no way to know, and merging them on a
  guess would be a fabricated finding.
- **An ad with no media** -> nothing written at all. Zero media is a real
  observation, not a missing one, and it must not manufacture a row.

## First seen is preserved, last seen advances

`first_seen_at` is set once, on insert, and is **never** rewritten. `last_seen_at`
moves forward only -- `greatest(last_seen_at, now())` -- so reprocessing an old
run cannot rewind an asset's history, which is the same rule `ads` follows for
`last_seen_at` in S2.1.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.media import AdSnapshotMedia, MediaAsset
from app.providers.data.models import MediaRef


@dataclass(frozen=True, slots=True)
class LinkedAsset:
    """One asset as a snapshot referenced it.

    Attributes:
        media_asset_id: The shared asset row, not a per-snapshot copy.
        provider_key: Echoed for logs and assertions.
        position: The index in the record's media tuple, in provider order.
    """

    media_asset_id: uuid.UUID
    provider_key: str
    position: int


def link_snapshot_media(
    session: Session,
    *,
    provider: str,
    ad_snapshot_id: uuid.UUID,
    media: tuple[MediaRef, ...],
) -> tuple[LinkedAsset, ...]:
    """Persist one snapshot's media references and their links.

    Args:
        session: The caller's session -- the same one that wrote the snapshot, so
            the whole thing shares a transaction. **The caller commits.**
        provider: The provider that issued the keys. Part of asset identity.
        ad_snapshot_id: The snapshot that referenced these assets.
        media: The record's media tuple, in provider order. Empty is normal and
            writes nothing.

    Returns:
        One `LinkedAsset` per reference, in provider order.

    Nothing here is derived from a digest and nothing here changes a digest.
    `creative_hash` v1 hashes provider keys and is computed by S2.2 before this
    runs; a media row appearing or changing cannot move it.
    """
    linked: list[LinkedAsset] = []

    # Provider order is preserved deliberately: `position` is the record of which
    # asset was presented where, and reordering would misreport what the provider
    # actually served.
    for position, reference in enumerate(media):
        asset_id = _resolve_asset(session, provider=provider, reference=reference)
        _link(session, ad_snapshot_id=ad_snapshot_id, asset_id=asset_id, position=position)
        linked.append(
            LinkedAsset(
                media_asset_id=asset_id,
                provider_key=reference.provider_key,
                position=position,
            )
        )

    return tuple(linked)


def _resolve_asset(session: Session, *, provider: str, reference: MediaRef) -> uuid.UUID:
    """Find or create the asset for one provider key.

    An upsert on `(provider, provider_key)` rather than a select followed by an
    insert: two workers observing the same shared asset would otherwise both miss
    the select and one would fail on the unique constraint -- and a shared asset is
    exactly the case where two workers are likely to meet, because the same image
    appears on many ads.

    The descriptive columns follow the provider's latest word, because a provider
    correcting a width or a mime is reporting the truth about an asset we already
    hold. `first_seen_at` is explicitly **not** in the update set: it means first,
    and an upsert that refreshed it would erase the fact that we have known about
    this asset since a specific moment.
    """
    statement = (
        insert(MediaAsset)
        .values(
            provider=provider,
            provider_key=reference.provider_key,
            source_url=reference.source_url,
            mime=reference.mime,
            width=reference.width,
            height=reference.height,
            duration_seconds=reference.duration_seconds,
            # Deliberately NULL. A content key is the SHA-256 of bytes, and there
            # are no bytes in S2.4 -- so this is not "unknown", it is the honest
            # state. See the module docstring in `models/media.py`.
            storage_key=None,
            byte_size=None,
            first_seen_at=func.now(),
            last_seen_at=func.now(),
        )
        .on_conflict_do_update(
            constraint=MEDIA_ASSET_IDENTITY,
            set_={
                "source_url": reference.source_url,
                "mime": reference.mime,
                "width": reference.width,
                "height": reference.height,
                "duration_seconds": reference.duration_seconds,
                # Never backwards, whatever order runs are processed in.
                "last_seen_at": func.greatest(MediaAsset.last_seen_at, func.now()),
                "updated_at": func.now(),
            },
        )
        .returning(MediaAsset.id)
    )
    return session.execute(statement).scalar_one()


#: The two upsert conflict targets, named as constants rather than inlined strings
#: because the write path and the migration both have to agree on them. A mismatch
#: would surface as an `IntegrityError` at the first real observation rather than at
#: build time, which is the worst moment to discover it.
MEDIA_ASSET_IDENTITY: Final = "uq_media_assets_provider_key"
LINK_IDENTITY: Final = "uq_ad_snapshot_media_snapshot_asset"


def _link(
    session: Session, *, ad_snapshot_id: uuid.UUID, asset_id: uuid.UUID, position: int
) -> None:
    """Record that a snapshot referenced an asset, and where.

    Upserted on `(ad_snapshot_id, media_asset_id)`, so a reprocessed run re-states
    a fact rather than adding a second copy of it.

    `position` *is* in the update set. That looks inconsistent with the "never
    revise an observation" rule that governs the snapshot itself, but it is not the
    same thing: this column records where the asset sat in the record's media tuple,
    and a second observation of the same snapshot legitimately reports that
    ordering again. Revising it would be correcting a claim about *this
    snapshot's* content, which is exactly what the append-only table forbids
    elsewhere -- so the difference is that the snapshot's own bytes never change,
    while this column is a projection of them and is re-derived on every write.
    """
    session.execute(
        insert(AdSnapshotMedia)
        .values(ad_snapshot_id=ad_snapshot_id, media_asset_id=asset_id, position=position)
        .on_conflict_do_update(
            constraint=LINK_IDENTITY,
            set_={"position": position, "updated_at": func.now()},
        )
    )

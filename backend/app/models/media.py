"""Creative assets as a provider described them, and where they were seen.

## S2.4 stores references, not bytes

This is the whole of the checkpoint. `AGENTS.md` section 12 forbids media byte
downloads in S0-S3, so nothing here has ever fetched an asset, and the columns that
would record a download -- `bytes`, `downloaded_at`, `sha256` -- are **absent by
design** rather than present and empty. A column that can never be truthfully
populated invites the next reader to fill it with a plausible-looking value.

What exists is the other half: a durable identity for a creative, and the
relationship from the observations that mention it.

## `provider_key` is an identity hint, not proof

`MediaRef.provider_key` is the provider's own id for an asset, and it is treated
here as a **hint**. It is the best identity available without bytes, and it is what
`creative_hash` v1 hashes -- but nothing verifies that a provider keeps its keys
stable, and no real provider has ever been run against this product. If a provider
rotates a key for an asset it is still serving, that becomes a second row here.

**They are deliberately not merged.** Two different `provider_key` values produce
two `MediaAsset` rows, and guessing that they are the same underlying bytes would
be a fabricated finding -- exactly what the provenance rules forbid. The cost is
that `creative_hash` v1 sees them as different, which is *consistent* rather than
contradictory: v1 hashed provider keys, and the provider keys did change. When a
byte-acquisition checkpoint fills `storage_key`, byte-based hashing becomes
`creative_hash` **v2**, and no stored v1 value is reinterpreted.

## `storage_key` is a future column, designed now

`storage_key` is a 64-character lowercase hex content key -- the SHA-256 of the
bytes, which is what `services/media.py::content_key` defines. **It is NULL on
every row S2.4 creates**, and that NULL carries exactly one meaning:

    a reference is held; the bytes have not been acquired.

It is not "unknown", not "pending", and not zero. It is the honest state, and it is
checked at the database so a malformed key cannot be stored even if a future
writer computes one wrongly.

## An asset is shared, so it is owned by nothing

`MediaAsset` has **no foreign key**. That is not an omission. The committed corpus
proves the relationship: `mock-media-shared-01` is referenced by two different ads
(`mock-ad-000201`, `mock-ad-000202`), because a brand running the same image
across two ads is ordinary rather than exceptional. An asset table owned by an ad
would have to either duplicate that asset per ad or lie about ownership.

So the observation relationship lives in `AdSnapshotMedia` -- a many-to-many link,
the same shape as `seen_in_run`. A snapshot may reference zero media (an ad with no
creative) or several; an asset may be referenced by many snapshots across many ads.

## Mutability, and why this table can be updated

`MediaAsset` is **mutable**: `last_seen_at` advances every time a run observes it,
and `storage_key` is designed to be filled later by an explicitly approved
byte-acquisition checkpoint.

That is safe precisely because this table holds no observation. The observations
are `AdSnapshotMedia` rows and the append-only `AdSnapshot` rows they point at.
Updating a row here updates a *summary* of observations, never one of them.

`AdSnapshotMedia` is append-only in the same sense `seen_in_run` is: one row per
(snapshot, asset), upserted, and **never rewritten to say something different about a
snapshot that already happened**. Its `position` in particular is captured once, by the
observation that created the snapshot, and is never revised by a later one --
`ad_snapshots.normalized` holds that snapshot's original media order and remains
authoritative for it. `app/services/media_references.py` explains why re-deriving that
order is impossible rather than merely discouraged.

Note the asymmetry with the table above, which is deliberate: `last_seen_at` on a
shared asset answers "when did we last see this", which genuinely changes, while
`position` on a link answers "what did *this* snapshot contain", which cannot.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import (
    TimestampMixin,
    UtcDateTime,
    UuidId,
    UuidPrimaryKeyMixin,
    not_blank,
)

#: A content key, or the absence of one. Same shape `services/media.py::content_key`
#: validates, written out rather than imported because a migration -- and a
#: constraint -- should record what the rule *is*, not whatever a module says
#: today.
_STORAGE_KEY_CHECK = "storage_key IS NULL OR storage_key ~ '^[0-9a-f]{64}$'"


class MediaAsset(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One creative asset, identified as its provider identifies it.

    Keyed on `(provider, provider_key)` rather than `provider_key` alone, for the
    same reason `ads` is keyed on `(provider, meta_ad_id)`: the same string from two
    providers is two different assets, and a bare key would let one overwrite the
    other's row.
    """

    __tablename__ = "media_assets"

    #: The provider that issued `provider_key`. Part of the identity, not
    #: attribution -- the same key string from two providers is two assets.
    provider: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    #: The provider's own id for the asset. An **identity hint**, not a content
    #: digest: see the module docstring for why that distinction is load-bearing.
    provider_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    #: Where the provider says the asset lives. **Never fetched.** `DATA_ACCESS.md`
    #: records that these expire, so this is a note of where it was, not a promise
    #: that it can be retrieved -- and a later checkpoint must re-collect rather
    #: than assume a stored URL still resolves.
    #:
    #: Refused rather than stripped if the provider embedded credentials in it, so
    #: this column cannot hold a secret.
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Provider-reported metadata, exactly as reported. `None` when not reported,
    #: never a default: `AGENTS.md` section 7 requires absence to stay absent.
    mime: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: An exact decimal, matching `MediaRef.duration_seconds` and the value S2.1
    #: stores in `normalized`. JSONB has no decimal type, so the snapshot keeps the
    #: exact string; a float here would be a measurement we could no longer say the
    #: provider reported.
    duration_seconds: Mapped[Decimal | None] = mapped_column(sa.Numeric, nullable=True)

    #: The content key the bytes would be stored under -- `sha256` of the content,
    #: per `services/media.py`. **NULL on every row S2.4 creates**, meaning "a
    #: reference is held, no bytes have been acquired". Checked at the database so a
    #: malformed key is refused rather than stored.
    storage_key: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    #: How many bytes, when they exist. NULL for the same reason as `storage_key`.
    byte_size: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)

    #: Our observation times, from the same `now()` that stamps `created_at`.
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        # The identity. Two rows for one (provider, key) pair would be two
        # conflicting descriptions of one asset.
        UniqueConstraint("provider", "provider_key", name="uq_media_assets_provider_key"),
        # NULL passes: a `CHECK` is satisfied unless it evaluates to FALSE, and a
        # regex yields NULL for NULL. So one expression serves both states -- a
        # row with no bytes yet, and a row whose key must be exactly a content key.
        CheckConstraint(_STORAGE_KEY_CHECK, name="storage_key_is_content_key"),
        not_blank("provider"),
        not_blank("provider_key"),
        # A measurement must be able to describe a real image. `MediaRef` enforces
        # `>= 1`; the same rule here means a hand-written row cannot claim a
        # zero-pixel asset.
        CheckConstraint("width IS NULL OR width >= 1", name="width_positive"),
        CheckConstraint("height IS NULL OR height >= 1", name="height_positive"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="duration_non_negative"
        ),
        # "Assets first seen in this window" -- the query a first collection or a
        # newly added competitor produces.
        Index("ix_media_assets_first_seen_at", "first_seen_at"),
    )


class AdSnapshotMedia(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One snapshot referenced one asset. The observation relationship.

    Many-to-many by necessity: an ad carries zero to several assets, and one asset
    is routinely carried by many ads -- the corpus's `mock-media-shared-01` spans
    two. Modelling it as a column on either side would force a duplication or a
    false ownership claim.

    Upserted rather than appended, on the same reasoning as `seen_in_run`: one
    snapshot referencing one asset is one fact, and a reprocessed run must not
    duplicate it.
    """

    __tablename__ = "ad_snapshot_media"

    #: The observation that mentioned this asset. RESTRICT: a snapshot is
    #: append-only evidence, and an asset's history must not be able to take it away.
    ad_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey(
            "ad_snapshots.id", name="fk_ad_snapshot_media_ad_snapshot_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )

    #: The asset referenced. RESTRICT for the same reason as every other reference
    #: in this schema: a cascade would let one deletion take history with it.
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey(
            "media_assets.id", name="fk_ad_snapshot_media_media_asset_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )

    #: Where this asset sat in the record's media tuple, in **provider order**,
    #: **as captured when the snapshot was created**.
    #:
    #: Written once and never revised. The ordering this reports is the one in the
    #: owning snapshot's own `normalized` JSON, and that JSON is append-only, so
    #: letting a later observation move this would put two tables into
    #: disagreement about a single immutable snapshot.
    #:
    #: Ordinal presentation information and nothing more. `creative_hash` v1
    #: *sorts* the provider keys before hashing, so this column cannot and does not
    #: affect any digest -- it exists so a reader can tell which image was which
    #: when a snapshot referenced several.
    #:
    #: Nullable because the position is only meaningful relative to a record we hold,
    #: and a row inserted without one is not lying about anything.
    position: Mapped[int | None] = mapped_column(sa.SmallInteger, nullable=True)

    __table_args__ = (
        # One snapshot references one asset once. Also the index that serves
        # "which assets does this snapshot reference" -- its leading column is
        # `ad_snapshot_id`, so a second index on the same column would be
        # duplicate work.
        UniqueConstraint(
            "ad_snapshot_id", "media_asset_id", name="uq_ad_snapshot_media_snapshot_asset"
        ),
        CheckConstraint("position IS NULL OR position >= 0", name="position_non_negative"),
        # The reverse direction: "which snapshots use this asset". The unique
        # constraint leads with `ad_snapshot_id` and cannot answer it.
        Index("ix_ad_snapshot_media_media_asset_id", "media_asset_id"),
    )

"""S2.4: `media_assets` and `ad_snapshot_media` -- creative references, no bytes.

## What this adds, and the column it deliberately does not

Two tables, one unique constraint each, three indexes, and **no foreign key out of
`media_assets`**. That last part is a decision rather than an oversight: the
committed corpus has `mock-media-shared-01` referenced by two different ads
(`mock-ad-000201`, `mock-ad-000202`), because one image across several ads is
ordinary. An asset table owned by an ad would have to duplicate that asset per ad
or lie about ownership, so the observation relationship lives in
`ad_snapshot_media` instead.

**No `bytes`, no `sha256`, no `downloaded_at`.** `ARCHITECTURE.md` once listed all
three, and none can be built here: `AGENTS.md` section 12 forbids media byte
downloads in S0-S3, and a content key is *the SHA-256 of bytes* -- so with no bytes
there is no key, no size and no download time. A column that can never be
truthfully populated invites the next reader to invent a value.

`storage_key` and `byte_size` therefore exist as **nullable columns, always NULL in
S2.4**. That NULL has exactly one meaning: *a reference is held, the bytes have not
been acquired.* It is not "unknown" and not "pending". The `CHECK` on `storage_key`
is written so a NULL passes (a `CHECK` is satisfied unless it evaluates to FALSE,
and a regex yields NULL for NULL) while a malformed key is still refused -- which
matters for a future writer that computes one.

## Historical data is not touched

There is **no backfill**, and none is possible: a media reference lives inside
`ad_snapshots.normalized` JSONB, and that table is append-only. A snapshot written
before this revision keeps its media in its own stored JSON, which stays
authoritative for it, and gains no links here. `ads` and `ad_snapshots` are not
altered at all -- this migration only creates.

That is the same trade `copy_hash` and `creative_hash` made when they arrived as
nullable columns, and it is the price of never rewriting history.

## `creative_hash` v1 is not reinterpreted

`creative_hash` v1 (`s2.2-creative-v1`) hashes sorted **provider keys**. This
migration gives those keys a queryable home and changes no stored digest. Byte
hashing, if ever approved, is a `creative_hash` **v2**; no v1 value is recomputed,
reinterpreted, or backfilled.

## Downgrade

Reversible, and rendered offline like every revision here. It issues `DROP`s, which
need explicit human consent under the checkpoint rules, so **it is never executed**.
Dropping these two tables loses only *derived* rows: every observation they recorded
is still in `ad_snapshots.normalized`, so the media can be re-derived by
re-collecting.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

#: Revision identifiers, used by Alembic.
revision: str = "0008_media_assets"
down_revision: str | None = "0007_status_by_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Identity is the pair, exactly as it is for `ads`: the same key string
        # from two providers is two different assets.
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("provider_key", sa.String(255), nullable=False),
        # Stored verbatim and never requested. `DATA_ACCESS.md` records that these
        # expire, so this is a note of where the asset was, not a promise it can be
        # retrieved. Refused at the normalizer if the provider embedded credentials.
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("mime", sa.String(255), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        # Exact decimal, matching `MediaRef.duration_seconds` and the value S2.1
        # stores in `normalized`. JSONB has no decimal type, so the snapshot keeps
        # the exact string; a float here could no longer be said to be the
        # provider's measurement.
        sa.Column("duration_seconds", sa.Numeric(), nullable=True),
        # Always NULL in S2.4. See the module docstring.
        sa.Column("storage_key", sa.String(64), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_assets")),
        sa.UniqueConstraint("provider", "provider_key", name="uq_media_assets_provider_key"),
        # NULL passes, because a `CHECK` is satisfied unless it evaluates to FALSE
        # and a regex yields NULL for NULL. One expression therefore serves both
        # "no bytes yet" and "a key that must be exactly a content key".
        sa.CheckConstraint(
            "storage_key IS NULL OR storage_key ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_media_assets_storage_key_is_content_key"),
        ),
        sa.CheckConstraint("btrim(provider) <> ''", name=op.f("ck_media_assets_provider_not_blank")),
        sa.CheckConstraint(
            "btrim(provider_key) <> ''", name=op.f("ck_media_assets_provider_key_not_blank")
        ),
        # A measurement must be able to describe a real image; `MediaRef` enforces
        # `>= 1`, and the same rule here stops a hand-written zero-pixel row.
        sa.CheckConstraint("width IS NULL OR width >= 1", name=op.f("ck_media_assets_width_positive")),
        sa.CheckConstraint(
            "height IS NULL OR height >= 1", name=op.f("ck_media_assets_height_positive")
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name=op.f("ck_media_assets_duration_non_negative"),
        ),
        # **No foreign key.** An asset is shared identity, not owned by an ad or a
        # snapshot -- the corpus has one key on two ads.
    )

    op.create_table(
        "ad_snapshot_media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Both RESTRICT: an asset's history and a snapshot's evidence must not be
        # able to take each other away.
        sa.Column("ad_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("media_asset_id", sa.Uuid(), nullable=False),
        # Ordinal, provider order, and never an input to any digest.
        sa.Column("position", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_snapshot_media")),
        # One snapshot references one asset once. Its leading column also serves
        # "which assets does this snapshot reference", so no second index on
        # `ad_snapshot_id` is created.
        sa.UniqueConstraint(
            "ad_snapshot_id",
            "media_asset_id",
            name="uq_ad_snapshot_media_snapshot_asset",
        ),
        sa.CheckConstraint(
            "position IS NULL OR position >= 0",
            name=op.f("ck_ad_snapshot_media_position_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["ad_snapshot_id"],
            ["ad_snapshots.id"],
            name="fk_ad_snapshot_media_ad_snapshot_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"],
            ["media_assets.id"],
            name="fk_ad_snapshot_media_media_asset_id",
            ondelete="RESTRICT",
        ),
    )

    # One index for each of the two real access patterns, and no others.
    #
    # 1. "Assets first seen in this window" -- what a first collection or a newly
    #    added competitor asks for.
    op.create_index("ix_media_assets_first_seen_at", "media_assets", ["first_seen_at"], unique=False)

    # 2. "Which snapshots use this asset" -- the reverse of the unique constraint,
    #    which leads with `ad_snapshot_id` and cannot answer it.
    op.create_index(
        "ix_ad_snapshot_media_media_asset_id", "ad_snapshot_media", ["media_asset_id"], unique=False
    )


def downgrade() -> None:
    # Indexes first, then the tables. Nothing else is involved -- no trigger, no
    # function, and no row in any pre-existing table was created by this revision.
    op.drop_index("ix_ad_snapshot_media_media_asset_id", table_name="ad_snapshot_media")
    op.drop_index("ix_media_assets_first_seen_at", table_name="media_assets")

    op.drop_table("ad_snapshot_media")
    op.drop_table("media_assets")

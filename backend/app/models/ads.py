"""What we collected, as history.

Three tables, in the order data flows through them:

    ads            one ad we have ever seen, identified for ever
        ad_snapshots   one immutable observation of that ad, at a point in time
    seen_in_run     the fact that a particular run saw that ad

## The four identities, kept apart

They are different facts and the schema refuses to let them blur:

- **Ad identity** is `(provider, meta_ad_id)`. The provider's own id, scoped to
  the provider that issued it. `meta_ad_id` alone would be ambiguous the moment a
  second provider is registered, and a page rename or a provider changing its
  numbering must never fork one ad into two.
- **Snapshot identity** is a moment. It answers "what did this ad look like when
  we saw it", and it is written once and never touched again.
- **Raw response identity** is the payload a snapshot was read from, via
  `raw_ref`. That is the whole traceability chain in one column: snapshot ->
  response -> provider call -> run -> page -> competitor.
- **Collection observation** is a `(ad, run)` pair, which is what `seen_in_run`
  records.

## No page or competitor on `ads`

An ad is not owned by a page. The same ad can be served on several pages and
across many runs, and a `facebook_page_id` here would make "which page saw this"
look like a property of the ad rather than a property of an observation. The
lineage is `seen_in_run` -> `collection_run` -> `facebook_page` -> `competitor`,
which is both correct and already indexed.

## `first_seen_at` and `last_seen_at` are ours

Not the provider's. `meta_delivery_start` is what Meta claims about when an ad
began; `first_seen_at` is when *we* first observed it, which for a commercial ad
can be long after it started, or before a competitor is even tracked. Merging the
two is the specific error `AGENTS.md` section 8 names, and it is why
`meta_delivery_start` lives on the snapshot -- as a provider-reported field,
next to `ad_status` -- and never in either column.

Both are server-clock, stamped from the same `now()` as the `seen_in_run` row
that recorded the observation, so "first seen" and the first observation agree by
construction rather than by two clocks being close.

## There is no `current_status` here

`ARCHITECTURE.md` lists one on `ads`, and it is deliberately absent in S2.1. The
status vocabulary -- `provider_active`, `not_seen_since`, `presumed_inactive`,
and the N-consecutive-complete-runs rule -- is a state machine over run history,
and it is S2.3's. Creating the column now would mean storing a value nothing in
S2.1 may compute, and an `ads` table with a permanently NULL status is a shape
that invites the next reader to fill it in by hand.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import (
    TimestampMixin,
    UtcDateTime,
    UuidId,
    UuidPrimaryKeyMixin,
    not_blank,
)
from app.models.runs import _stored_enum
from app.providers.data.provenance import DataOrigin

#: A sha256 digest, lowercase hex. Checked by the database because a malformed
#: digest would not fail loudly -- it would silently make every future
#: comparison unequal, and no snapshot would ever be written again.
_CONTENT_HASH_CHECK = "content_hash ~ '^[0-9a-f]{64}$'"


class Ad(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One ad, identified for as long as we keep collecting.

    An ad row is created the first time any run sees it and is never deleted
    while a snapshot or an observation references it. It is a pointer to
    history, not a cache of the latest state: everything about *how the ad
    currently looks* lives in `ad_snapshots`, and the only two facts kept here
    are the two that are about the ad's existence in our history rather than
    about any one observation.
    """

    __tablename__ = "ads"

    #: The provider that issued `meta_ad_id`. Part of the identity, not
    #: attribution: the same numeric id from two providers is two ads.
    provider: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    #: The provider's own ad id, untranslated. Never derived, never matched
    #: fuzzily -- two records are the same ad because the provider says so.
    meta_ad_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    data_origin: Mapped[DataOrigin] = mapped_column(
        _stored_enum(DataOrigin, name="data_origin"),
        nullable=False,
    )

    #: When we first observed this ad. Ours, not the provider's.
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    #: The most recent run that observed it. Advanced, never rewound.
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    #: The snapshot holding this ad's current state, or `None` until the first
    #: snapshot is written. Nullability is honest rather than a default: the
    #: value is meaningless before there is anything to point at.
    #:
    #: `use_alter=True` because this and `ad_snapshots.ad_id` point at each
    #: other. The migration creates the table without this constraint and adds
    #: it with an `ALTER TABLE` once `ad_snapshots` exists -- the ordinary
    #: solution, and preferable to a deferrable constraint the writer would then
    #: have to be careful never to need.
    latest_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidId,
        ForeignKey(
            "ad_snapshots.id",
            name="fk_ads_latest_snapshot_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )

    #: `foreign_keys` is stated because the two tables reference each other:
    #: without it SQLAlchemy cannot tell `ad_snapshots.ad_id` from
    #: `ads.latest_snapshot_id` and refuses to guess.
    snapshots: Mapped[list[AdSnapshot]] = relationship(
        back_populates="ad",
        foreign_keys="AdSnapshot.ad_id",
        order_by="AdSnapshot.created_at",
    )

    __table_args__ = (
        # The identity. Named because the persistence layer upserts on it by
        # name, and because an unnamed constraint gets a hash-based name that
        # can shift between migration runs.
        UniqueConstraint("provider", "meta_ad_id", name="uq_ads_provider_meta_ad_id"),
        not_blank("provider"),
        not_blank("meta_ad_id"),
        CheckConstraint("last_seen_at >= first_seen_at", name="ad_sighting_order"),
    )


class AdSnapshot(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One immutable observation of an ad. Written once, never touched again.

    `AGENTS.md` section 8 makes these rows append-only, and the reason is
    physical rather than procedural: a commercial ad that stops running
    disappears from Meta permanently (`DATA_ACCESS.md`), so this row is often
    the only copy of anything about it. Updating one to represent a later
    observation would not be a correction, it would be a deletion.

    ## What is deliberately absent

    **No `copy_hash`, no `creative_hash`.** `ARCHITECTURE.md` lists both, and
    both are S2.2's: the card and creative model, and duplicate detection built
    on them. S2.1 stores one self-contained comparison value, `content_hash`, so
    that nothing here depends on a richer hash arriving later. S2.2 will add the
    sub-hashes as new columns, and the historical `content_hash` values will keep
    meaning exactly what they meant under v1.

    ## `raw_ref` is the point of the table

    Every snapshot names the exact response it was read from. That single column
    is the whole audit trail: snapshot -> `raw_responses` -> `provider_runs` ->
    `collection_runs` -> `facebook_pages` -> `competitors`. It is `NOT NULL` and
    `RESTRICT` because a snapshot that cannot name its source is an assertion
    with nothing behind it, and because the evidence it points at is the copy we
    cannot re-acquire.

    ## `updated_at` never moves

    The table is append-only, so the column inherited from `TimestampMixin` is
    inert. That is not an oversight to be tidied away -- an `updated_at` that
    has moved on a row that must never change *is* the signal that something
    wrote to history. A test asserts it does not.
    """

    __tablename__ = "ad_snapshots"

    ad_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("ads.id", name="fk_ad_snapshots_ad_id", ondelete="RESTRICT"),
        nullable=False,
    )

    #: The run this observation belongs to. Not derivable from `raw_ref` in one
    #: hop, and it is the column the "one snapshot per ad per run" rule is
    #: enforced on.
    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey(
            "collection_runs.id",
            name="fk_ad_snapshots_collection_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    #: The stored provider response this snapshot was read from.
    raw_ref: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("raw_responses.id", name="fk_ad_snapshots_raw_ref", ondelete="RESTRICT"),
        nullable=False,
    )

    #: The S2.1 v1 comparison digest (`services.content_hash`). A new snapshot is
    #: written only when this differs from the current one.
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    #: The provider's own status wording, untranslated. Not our status: nothing
    #: derives `provider_active` until S2.3.
    ad_status: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    #: The provider's reported delivery start. Kept apart from `ads.first_seen_at`
    #: because they are different facts about different observers.
    meta_delivery_start: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: The normalized record as S1.3 read it, in provider order. Fidelity over
    #: query convenience: `content_hash` is computed from the `RawAdRecord`, not
    #: from this, precisely so that JSONB's key normalisation cannot move a
    #: digest.
    normalized: Mapped[Any] = mapped_column(JSONB, nullable=False)

    ad: Mapped[Ad] = relationship(
        back_populates="snapshots",
        foreign_keys=[ad_id],
    )

    __table_args__ = (
        # The snapshot cardinality rule, expressed by the database: at most one
        # snapshot per ad per run, so a run that sees one ad three times cannot
        # write three rows. Application code enforces it too; this makes it
        # impossible to get wrong rather than merely discouraged.
        UniqueConstraint("ad_id", "collection_run_id", name="uq_ad_snapshots_ad_run"),
        sa.CheckConstraint(_CONTENT_HASH_CHECK, name="content_hash_is_sha256_hex"),
    )


class SeenInRun(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """The fact that one run saw one ad. Not a snapshot, and not append-only.

    A provider can serve the same ad more than once within a single walk -- the
    committed corpus does exactly that -- so this is keyed on `(ad, run)` and
    written as an upsert: the second sighting updates `snapshot_id` rather than
    adding a second row. What the run observed *once over* is one observation.

    ## Why this table is not append-only

    `AGENTS.md` section 8 scopes append-only to `ad_snapshots`, and the two
    tables answer different questions. A snapshot is a claim about what the ad
    looked like, and rewriting one destroys evidence. This row is a link: it
    says "this run saw this ad, and here is the snapshot it resolved to", and
    the honest answer when a later sighting in the same run points at a different
    snapshot is to correct the link.

    ## No timestamp column of its own

    The observation happened *during the run*, and `collection_run_id` is that
    context. What the row needs is to know *when we wrote it*, which
    `TimestampMixin` already provides -- and that value doubles as the
    observation clock for `ads.first_seen_at`/`last_seen_at`, which are stamped
    from the same `now()` in the same transaction, so they agree by construction.
    """

    __tablename__ = "seen_in_run"

    ad_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("ads.id", name="fk_seen_in_run_ad_id", ondelete="RESTRICT"),
        nullable=False,
    )

    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey(
            "collection_runs.id",
            name="fk_seen_in_run_collection_run_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    #: The snapshot this run's sighting resolved to -- the one written by this
    #: run, or the ad's current one when the content was unchanged.
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey(
            "ad_snapshots.id",
            name="fk_seen_in_run_snapshot_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("ad_id", "collection_run_id", name="uq_seen_in_run_ad_run"),)

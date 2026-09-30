"""What we track: a competitor, and the Meta pages they advertise from.

Two tables, and the shortest possible chain between them. A competitor is
something the operator told us about; a page is something a provider reports.
Neither is collected data, so neither carries `data_origin` -- see
`ARCHITECTURE.md`'s "where relevant". The first collected value enters the
schema at `collection_runs`, and everything below it inherits the origin from
there rather than repeating it.

Persistence shape only. No behaviour lives on these classes, and none will: a
method here would be business logic on a table, which is the wrong place to
discover it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import (
    ISO_ALPHA_2_CHECK,
    CountryCodeMixin,
    TimestampMixin,
    UuidId,
    UuidPrimaryKeyMixin,
    not_blank,
)

if TYPE_CHECKING:
    from app.models.runs import CollectionRun


class Competitor(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """A brand the operator has decided to watch.

    The leanest possible table, because `ARCHITECTURE.md` specifies no fields for
    it and a name is the minimum that makes "add competitor" a real operation. A
    name is deliberately *not* unique: two brands can share a name in different
    markets, and a constraint invented here would become a lie the first time it
    is hit. A competitor is identified by its id, never by its name.

    `is_tracked` is on the page, not here, because that is the granularity
    collection actually works at.
    """

    __tablename__ = "competitors"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    pages: Mapped[list[FacebookPage]] = relationship(back_populates="competitor")

    __table_args__ = (not_blank("name"),)


class FacebookPage(Base, UuidPrimaryKeyMixin, TimestampMixin, CountryCodeMixin):
    """A Meta page belonging to a competitor, and the unit collection walks.

    **Page identity is stored once.** `ARCHITECTURE.md` names a `page_id` column
    and S0.3's `PageRef` names a `provider_page_id`, and it is tempting to keep
    both -- an internal key and the provider's key. That is duplication with a
    cost: every lookup has to know which one it means, and a page that ends up
    with two disagreeing values is undetectable. This table's own `id` is the
    internal key; `page_id` is the single external identity, and the two are
    never stored in the same row twice under different names.

    **Uniqueness is global, not per competitor.** A page can be attached to
    exactly one competitor, enforced by a `UNIQUE` on `page_id` rather than on
    `(competitor_id, page_id)`. The per-composite version would permit the same
    page under two competitors, and then every ad collected through it would
    belong to two parents at once -- an ambiguous foreign key, which is the one
    thing this schema is not allowed to produce. Tracking one page twice is a
    data-entry mistake, and refusing it is the correct behaviour.

    `name` and `url` mirror S0.3's `PageRef.page_name` and `PageRef.url`
    exactly, nullable because a provider need not report them. Transcribing a
    contract that already exists is not inventing a field. The URL keeps the
    same `http(s)`-only rule the provider boundary enforces, so a stored
    destination is never something a later fetcher could not act on.

    `tracking_frequency` is plain text with no closed vocabulary. The set of
    frequencies is a scheduling decision, and it belongs to the scheduler that
    S1.2 writes -- the same argument S0.3 used to leave `JobRequest.kind` a
    free string. Guessing `('hourly', 'daily', 'weekly')` here would put a
    scheduler's vocabulary into a table and make every later change a migration.
    """

    __tablename__ = "facebook_pages"

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("competitors.id", ondelete="RESTRICT"),
        nullable=False,
    )

    page_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    url: Mapped[str | None] = mapped_column(Text, nullable=True)

    tracking_frequency: Mapped[str] = mapped_column(String(64), nullable=False)

    is_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False)

    competitor: Mapped[Competitor] = relationship(back_populates="pages")
    collection_runs: Mapped[list[CollectionRun]] = relationship(back_populates="facebook_page")

    __table_args__ = (
        # Explicit, because the naming convention would otherwise derive the
        # name and the index would only be findable by reading the convention.
        # This one serves `/competitors/{id}/pages`, the reverse lookup the
        # ARCHITECTURE.md API surface actually names for this table; an
        # unindexed foreign key makes it a sequential scan.
        Index("ix_facebook_pages_competitor_id", "competitor_id"),
        CheckConstraint(ISO_ALPHA_2_CHECK, name="country_iso_alpha2"),
        not_blank("page_id"),
        not_blank("tracking_frequency"),
        CheckConstraint("url IS NULL OR url ~ '^https?://'", name="url_http_only"),
    )

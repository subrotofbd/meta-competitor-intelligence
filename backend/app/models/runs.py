"""The record of what we collected, in the order it was collected.

Three tables, and the shape of the shape is the whole point:

    collection_run   one attempt to collect one page, in one country, from one
                     provider. It is the unit of history.
        provider_run   one HTTP call inside that attempt. A cursor walk is many
                       of them, which is why timing, HTTP status and cost are
                       recorded here and not on the run.
            raw_response   the bytes that came back, before anything read them.

**Why a run is per page, not per competitor.** `ARCHITECTURE.md` defines
`not_seen_since` as "we did not see it in the latest complete run *for that
Page/country*", and allows `presumed_inactive` only after "N consecutive
COMPLETE runs". Both rules are about a page's own run history. A run scoped to a
competitor would make every one of those rules a three-table join and would make
"complete" mean "no page in a set failed", which is a different and weaker
claim. Per-page runs make each of those queries one indexed lookup, and make the
lease in the job queue mean one page rather than one brand.

**Provenance and provider are recorded once, at the top of the chain.**
`collection_runs` owns `provider` and `data_origin`; `provider_runs` and
`raw_responses` reach them through their foreign keys. Repeating them per row
would be three copies that can disagree, and there is no reading of this schema
in which a single run legitimately used two providers. Every value collected
during a run therefore resolves to exactly one `data_origin`, which is what
AGENTS.md section 7 requires of a stored value.

**This checkpoint declares a vocabulary, not a state machine.** The status
values exist so the columns are typed and constrained. What may legally follow
what is S1.2's job, and no transition is validated here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import (
    ISO_ALPHA_2_CHECK,
    CountryCodeMixin,
    TimestampMixin,
    UtcDateTime,
    UuidId,
    UuidPrimaryKeyMixin,
    at_most,
    not_blank,
)
from app.models.tracking import FacebookPage
from app.providers.data.provenance import DataOrigin

#: An operator reading a failed run gets a sentence, not a megabyte of provider
#: HTML. The column is unbounded `Text`; the check is what keeps it readable.
_ERROR_MESSAGE_LIMIT = 2000


class CollectionRunStatus(StrEnum):
    """The lifecycle of one collection attempt.

    `complete` and `failed` are obvious. `partial` is the one that earns its
    place: `ARCHITECTURE.md` forbids marking an ad inactive after "a failed or
    partial run", which means a run that stopped half way has to be
    distinguishable from one that got nothing at all. Collapsing them would make
    the history rules unenforceable.

    `pending` exists because the worker is a queue consumer, and a run is
    enqueued before anything has called a provider.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class ProviderRunStatus(StrEnum):
    """The outcome of one HTTP call.

    `blocked` is a status rather than an error string because AGENTS.md section 5
    is unconditional: a block stops the run and is reported, and never gets
    retried or quietly retried as a generic failure. A run that hit a block must
    be able to be found by querying for one.

    The other three typed provider failures -- `RateLimited`, `SchemaChanged`,
    `Transient` -- are deliberately *not* statuses. They are recorded in
    `ProviderRun.error_type`, which keeps the vocabulary open exactly as S0.3's
    `retryable` class attribute does: adding a fifth failure mode is then a new
    string in a column, not a migration and a value every consumer must learn.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


def _stored_enum(values: type[Enum], *, name: str) -> sa.Enum:
    """Map a Python enum onto a `VARCHAR` with a named `CHECK` constraint.

    Three deliberate choices:

    * **Not a native PostgreSQL enum.** `ALTER TYPE ... ADD VALUE` cannot run
      inside a transaction, so extending a native enum is a special case in
      every future migration and a value can never be removed. A `VARCHAR` plus
      a check is an ordinary migration, which is what AGENTS.md section 12 asks
      for ("additive enum changes need a migration and a UI label").
    * **Values, not names.** `DataOrigin.official_api` has the name
      `OFFICIAL_API` and the value `official_api`; SQLAlchemy persists names by
      default, which would store `OFFICIAL_API` and diverge from every other
      place the value appears.
    * **The check is named**, so the naming convention resolves it to
      `ck_<table>_<name>` and Alembic can reverse it by name. An unnamed
      constraint gets a hash-based name that can shift between runs.
    """
    return sa.Enum(
        values,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda enum_class: [member.value for member in enum_class],
    )


class CollectionRun(Base, UuidPrimaryKeyMixin, TimestampMixin, CountryCodeMixin):
    """One attempt to collect one page, in one country, from one provider.

    `started_at` and `finished_at` are both nullable, and deliberately so: they
    answer "did this run happen yet" and "is it still happening" without
    inventing a fourth status. A `pending` run has neither, a `running` one has
    only the first.

    `country` is a run parameter, not a property of the page. A page advertises
    in more than one market, and the country is what scopes the history rules,
    so it belongs on the run and not only on `facebook_pages`.

    `records_returned` counts the records the run *read* -- the ones that became
    a `RawAdRecord`. It is therefore lower than what arrived whenever some record
    could not be read, and the gap is exactly what the `PARTIAL` status and
    `error_message` are for. It is not a count of new or changed ads: those are
    decided by comparing `content_hash` against the previous snapshot, which is
    S2's work and must not be anticipated here with a column that looks like it
    already knows. How many records *arrived* is not recorded separately; the
    raw responses hold all of them either way.
    """

    __tablename__ = "collection_runs"

    facebook_page_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("facebook_pages.id", ondelete="RESTRICT"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    data_origin: Mapped[DataOrigin] = mapped_column(
        _stored_enum(DataOrigin, name="data_origin"),
        nullable=False,
    )

    status: Mapped[CollectionRunStatus] = mapped_column(
        _stored_enum(CollectionRunStatus, name="status"),
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    records_returned: Mapped[int] = mapped_column(
        sa.Integer,
        server_default=sa.text("0"),
        nullable=False,
    )

    error_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    facebook_page: Mapped[FacebookPage] = relationship(back_populates="collection_runs")
    provider_runs: Mapped[list[ProviderRun]] = relationship(back_populates="collection_run")

    __table_args__ = (
        # One indexed lookup answers "the latest complete run for this page and
        # country", which is the query ARCHITECTURE.md's `not_seen_since` rule
        # is written as. Deliberately not a composite index on
        # (page, country, started_at): that query is S2's to write and to
        # measure, and adding the index before the query exists is how index
        # overengineering starts.
        Index("ix_collection_runs_facebook_page_id", "facebook_page_id"),
        CheckConstraint(ISO_ALPHA_2_CHECK, name="country_iso_alpha2"),
        not_blank("provider"),
        CheckConstraint("records_returned >= 0", name="records_returned_not_negative"),
        at_most("error_message", _ERROR_MESSAGE_LIMIT),
        # A run that finished before it started is a clock or ordering bug, and
        # every duration the UI will ever show is computed from these two.
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
    )


class ProviderRun(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One HTTP call to one provider, inside a collection run.

    Split from the run because a cursor walk is many calls, and three facts only
    make sense per call: how long it took, what HTTP status came back, and what
    it cost. Apify bills per result per call; a per-run total would be
    unattributable.

    `request_meta` stores S0.3's `RequestMeta` verbatim as JSONB, including the
    provider, origin and country that the run already knows. That overlap is
    intentional and is not the duplication the rest of this schema avoids: the
    run says what we *asked for*, and this says what the call *was*. Keeping the
    object whole means a change to the provider contract does not need a
    migration, and it is the evidence for what the call actually was.
    """

    __tablename__ = "provider_runs"

    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("collection_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[ProviderRunStatus] = mapped_column(
        _stored_enum(ProviderRunStatus, name="status"),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    request_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    #: Where the *next* call in this walk should resume from. `NULL` means the
    #: walk is finished. The run itself stores no cursor, deliberately: a run
    #: covers one page, so its resume point is exactly the `next_cursor` of its
    #: last call, and a second copy of that would be two values to keep in step.
    next_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)

    http_status: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: The S0.3 exception class that ended the call -- `rate_limited`,
    #: `blocked`, `schema_changed`, `transient` -- or any other short token.
    #: Free text on purpose; see `ProviderRunStatus`.
    error_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(sa.String(3), nullable=True)
    cost_method: Mapped[str | None] = mapped_column(Text, nullable=True)

    collection_run: Mapped[CollectionRun] = relationship(back_populates="provider_runs")
    raw_response: Mapped[RawResponse | None] = relationship(
        back_populates="provider_run",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_provider_runs_collection_run_id", "collection_run_id"),
        CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="http_status_range",
        ),
        at_most("error_message", _ERROR_MESSAGE_LIMIT),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        CheckConstraint(
            "cost_amount IS NULL OR cost_amount >= 0",
            name="cost_amount_not_negative",
        ),
        # A cost with no method is not displayable. AGENTS.md section 7 requires
        # an ESTIMATE to render with the method it was arrived at, so a partial
        # triple is refused at the database rather than shown as a bare number.
        CheckConstraint(
            "(cost_amount IS NULL AND cost_currency IS NULL AND cost_method IS NULL) OR "
            "(cost_amount IS NOT NULL AND cost_currency IS NOT NULL AND cost_method IS NOT NULL)",
            name="cost_all_or_nothing",
        ),
    )


class RawResponse(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """A provider's response, stored before anything parsed it.

    AGENTS.md section 8 requires the raw payload to be persisted before
    normalisation, so that a parser bug can be fixed against the original instead
    of destroying the collection. The row exists to be that original.

    **`payload_hash` is computed by the database, in a `BEFORE INSERT OR UPDATE`
    trigger, and nothing else may write it.** A `GENERATED ALWAYS AS ... STORED`
    column was the obvious choice and does not work: PostgreSQL requires a
    generated expression to be immutable, and the JSONB-to-text cast is not. So
    the trigger takes `sha256` of the *stored* payload's own canonical text,
    which gives a stronger property than a hash computed by the application --
    the hash cannot disagree with the payload it sits beside, cannot be omitted,
    and cannot be forged, and any later edit of the payload is visible because
    the hash moves with it.

    It is a hash of the stored form, not of the wire bytes. `jsonb` normalises
    key order, whitespace and duplicate keys, so `payload_hash` identifies *what
    we kept*; it is not a claim to have preserved the provider's exact
    serialisation. `payload` is the value, queryable, and lossless for anything
    JSON can express.

    One response per call, enforced by the `UNIQUE` on `provider_run_id`: a
    `ProviderResult` carries exactly one `raw`, so a second response for the
    same call is a bug, and refusing it is louder than storing both.
    """

    __tablename__ = "raw_responses"

    provider_run_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("provider_runs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    #: S0.3's `RawPayload`: a dict or a list. Deliberately untyped here too,
    #: because a provider response genuinely can be either and the alternative
    #: is a wrapper object around data whose whole purpose is to be untouched.
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)

    #: Maintained by the trigger described above. Declared here as an ordinary
    #: column so that the model's metadata still matches the database exactly;
    #: the trigger is invisible to autogenerate and lives in the migration.
    payload_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    provider_run: Mapped[ProviderRun] = relationship(back_populates="raw_response")

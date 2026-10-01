"""Status for one ad, in one monitoring context. Derived, never evidence.

## Why a table rather than a column on `ads`

`ARCHITECTURE.md` originally put `current_status` on `ads`. That cannot work, and
the reason is structural rather than a matter of taste.

**An ad is not owned by a page.** `models/ads.py` states it directly: the same ad
is served on several pages, and a `facebook_page_id` on `ads` would turn "which
page saw this" into a property of the ad. So `ads` carries no page and no country
-- deliberately, and `test_ads.py` enforces it.

But status *is* a fact about a context. An ad can be present on page A in India
and absent from page B in the same country, and both are true at once. One row on
`ads` cannot hold two answers to "did we see it?". The only structures that could
are a per-context table or a page/country foreign key on `ads`, and the second is
the thing the schema was designed to avoid.

So status lives here, keyed on `(ad_id, facebook_page_id, country)`, and `ads`
gains nothing.

## What is evidence and what is a projection

The evidence chain is unchanged and is the only thing that is true:

    raw_responses -> ad_snapshots -> seen_in_run -> collection_runs -> page/country

Every column in this table is **recomputable** from that chain. `current_status` is
what we concluded; `not_seen_since_at` is where the absence boundary sits;
`provider_active` is a normalised reading of a provider's own words. Delete this
table's contents and the next evaluation rebuilds it. That is why it is safe to
update freely while `ad_snapshots` is append-only and is not.

## Two facts that must never be merged

`provider_active` is **the provider's assertion**, and `current_status` is **our
conclusion**. They disagree routinely and both stay:

- a provider can report an ad active in a run where we did not observe it;
- we can observe an ad the provider has marked inactive.

Collapsing them into one boolean is the specific error `AGENTS.md` section 7 warns
about for provenance generally -- a value badged as something it is not. A stale
`true` carried across an absent run would assert provider evidence that no longer
exists, so an absent run **clears** `provider_active` to `NULL`.

## Absence is not proof

`current_status` is a *presumption*. `AGENTS.md` section 8 is explicit: an ad
missing from a run is not evidence it stopped, `not_seen_since` is not "stopped",
and `presumed_inactive` requires N consecutive COMPLETE runs. That is why the name
carries "presumed", and why recovery -- an ad reappearing -- is a legal transition
back to `seen` rather than an error.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import (
    ISO_ALPHA_2_CHECK,
    CountryCodeMixin,
    TimestampMixin,
    UtcDateTime,
    UuidId,
    UuidPrimaryKeyMixin,
)

#: The derived vocabulary. Frozen for S2.3.
#:
#: `seen` is the one that is easy to forget: it is not "good", not "active" and
#: not a verdict, only the statement that the most recent complete run for this
#: context observed the ad. `AGENTS.md` section 7 forbids labelling longevity a
#: verdict, and the same restraint applies here.
#:
#: `not_seen_since` is deliberately *not* "stopped". `presumed_inactive` is a
#: presumption after N consecutive complete absences, and the name says so.
STATUS_SEEN = "seen"
STATUS_NOT_SEEN_SINCE = "not_seen_since"
STATUS_PRESUMED_INACTIVE = "presumed_inactive"

AD_STATUS_VALUES: tuple[str, ...] = (
    STATUS_SEEN,
    STATUS_NOT_SEEN_SINCE,
    STATUS_PRESUMED_INACTIVE,
)


class AdStatusByContext(Base, UuidPrimaryKeyMixin, TimestampMixin, CountryCodeMixin):
    """What we concluded about one ad, observed in one Page + country context.

    One row per `(ad_id, facebook_page_id, country)`. Four contexts for one ad are
    four rows with four independent absence streaks -- an ad present on page A and
    absent from page B must be able to say both, and `ARCHITECTURE.md`'s
    "latest complete run for that Page/country" only means something once the
    context is pinned down.

    This table is a **derived projection and is recomputable**. Nothing here is the
    record of what a provider said; that is `ad_snapshots.ad_status`, stored
    untranslated and never overwritten.
    """

    __tablename__ = "ad_status_by_context"

    #: The ad whose status this is. `RESTRICT`: an ad's status history outlives any
    #: part of the chain that produced it.
    ad_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("ads.id", name="fk_ad_status_by_context_ad_id", ondelete="RESTRICT"),
        nullable=False,
    )

    #: The Page this status is about. The ad is not *owned* by it; the ad was
    #: simply observed there, and the same ad can have a different status for a
    #: different page.
    facebook_page_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey(
            "facebook_pages.id",
            name="fk_ad_status_by_context_facebook_page_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    #: Our conclusion about this ad in this context. `NOT NULL` because a row that
    #: exists at all is a row about which we have concluded something -- a row
    #: meaning "unknown" would be indistinguishable from one not yet evaluated, and
    #: `NULL` would invite a reader to treat "not yet evaluated" as a finding.
    current_status: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    #: The provider's explicit assertion, normalised. Tri-state on purpose:
    #:
    #: `True`  -- the provider said active.
    #: `False` -- the provider said inactive.
    #: `None`  -- the provider said nothing recognisable, said nothing at all, or
    #:            we did not observe the ad in this context's latest complete run.
    #:
    #: `None` is never rounded to `False`. A provider that does not report a
    #: status has made no assertion, and recording "not active" from silence is
    #: inventing a finding. The raw wording stays on `ad_snapshots.ad_status`, so
    #: nothing is lost by normalising here.
    provider_active: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)

    #: When this ad was last *observed* in a complete run for this context --
    #: specifically that run's `finished_at`, our own server-side boundary.
    #:
    #: Never `meta_delivery_start`: that is the provider's claim about when the ad
    #: began, and this is when *we* last saw it. `AGENTS.md` section 8 forbids
    #: merging the two, and a "not seen since" date built from a provider-reported
    #: start date would be a claim about the past that we cannot support.
    #:
    #: `NULL` until the ad has been observed in a complete run for this context.
    not_seen_since_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: The most recent run whose completion was evaluated into this row.
    #:
    #: This is the idempotence guard, not bookkeeping. Two workers can finish
    #: runs for the same page, and a replayed or retried job must not rewind a
    #: status that a newer run already established -- so an evaluation whose run
    #: is older than this is discarded. Without it, reprocessing an old run would
    #: walk the streak backwards and could resurrect a `presumed_inactive` that a
    #: later run legitimately set.
    last_status_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidId,
        ForeignKey(
            "collection_runs.id",
            name="fk_ad_status_by_context_last_status_run_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    __table_args__ = (
        # One status per context. Two rows for the same triple would mean two
        # contradictory conclusions about the same observation, and nothing could
        # say which was newer.
        UniqueConstraint(
            "ad_id",
            "facebook_page_id",
            "country",
            name="uq_ad_status_by_context_ad_page_country",
        ),
        # A frozen vocabulary in the database, not only in Python. An unrecognised
        # status is a bug that would otherwise surface as an unknown value in a
        # report, which is the worst place to discover one.
        CheckConstraint(
            "current_status IN ('seen', 'not_seen_since', 'presumed_inactive')",
            name="current_status_vocabulary",
        ),
        CheckConstraint(ISO_ALPHA_2_CHECK, name="country_iso_alpha2"),
        # The absence boundary cannot be in the future. A `not_seen_since_at`
        # ahead of `updated_at` would mean the row was built from a run that has
        # not finished, which is exactly the run that must not count.
        CheckConstraint(
            "not_seen_since_at IS NULL OR not_seen_since_at <= now()",
            name="not_seen_since_not_in_future",
        ),
        # Bulk evaluation of one context after a run: every ad whose status is
        # about to be advanced, for one Page + country.
        Index("ix_ad_status_by_context_page_country", "facebook_page_id", "country"),
        # The idempotence guard's own lookup, for reconciling a context against
        # the runs that have already been evaluated.
        Index("ix_ad_status_by_context_last_status_run_id", "last_status_run_id"),
    )

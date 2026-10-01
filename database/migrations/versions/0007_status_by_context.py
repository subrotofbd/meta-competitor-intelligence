"""S2.3: `ad_status_by_context` -- per Page + country status, and its indexes.

## Why a new table rather than a column on `ads`

`ARCHITECTURE.md` originally specified `ads.current_status`. That is not
buildable. An ad is served on several pages, `ads` deliberately carries no page
or country foreign key, and status is a fact *about a context*: an ad can be
present on page A and absent from page B, and both are true simultaneously. One
row on `ads` cannot hold two answers to "did we see it?", and adding a page
foreign key to `ads` would undo the S2.1 decision that an ad is not owned by a
page.

So status lives here, keyed on `(ad_id, facebook_page_id, country)`, and **`ads`
is not touched at all**.

## What this table is, and is not

It is a **derived projection and is fully recomputable** from the evidence chain
`raw_responses -> ad_snapshots -> seen_in_run -> collection_runs`. Delete its
contents and the next evaluation rebuilds it. That is what makes it safe to
update freely while `ad_snapshots` remains append-only.

This migration therefore **adds** a table and **writes nothing**. There is no
backfill, no `UPDATE`, no default, and no row is derived here: status is a
conclusion drawn from run history at evaluation time, and a status row whose
backing runs do not exist would be a finding with no evidence behind it.

## The indexes are for named queries, not for symmetry

1. `collection_runs (facebook_page_id, country, finished_at DESC)` --
   the consecutive-complete-runs walk. `PROJECT_MEMORY.md` deferred a composite
   here until "S2 writes the query and measures"; this is that query. Partial on
   `status = 'complete'`, because FAILED and PARTIAL runs are *invisible* to the
   walk -- they can neither advance nor reset a streak -- so indexing them would
   be indexing rows the query must never read.
2. `seen_in_run (collection_run_id)` -- "which ads did this run observe", needed
   for bulk evaluation of one context. The existing
   `UNIQUE (ad_id, collection_run_id)` leads on `ad_id` and cannot answer it.
3. `ad_status_by_context (facebook_page_id, country)` -- the same bulk evaluation
   from the status side.
4. `ad_status_by_context (last_status_run_id)` -- the idempotence guard's lookup.

No trigram or GIN index: no text is searched in S2.3, and
`test_no_text_search_index` enforces that.

## Downgrade

Reversible, and rendered offline like every revision here. It issues `DROP`s,
which need explicit human consent under the checkpoint rules, so **it is never
executed**.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

#: Revision identifiers, used by Alembic.
revision: str = "0007_status_by_context"
down_revision: str | None = "0006_s2_2_hashes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ad_status_by_context",
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
        # All three parents RESTRICT. An ad's status history outlives any part of
        # the chain that produced it, and a cascade here would let one deleted
        # page take every observed status with it.
        sa.Column("ad_id", sa.Uuid(), nullable=False),
        sa.Column("facebook_page_id", sa.Uuid(), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("current_status", sa.String(32), nullable=False),
        # Tri-state: True / False / NULL. `None` means the provider made no
        # assertion -- unknown wording, omitted entirely, or we did not observe
        # the ad in this context's latest complete run. Never rounded to False.
        sa.Column("provider_active", sa.Boolean(), nullable=True),
        # The last complete run that actually observed this ad, by our own
        # server-side boundary. Never `meta_delivery_start`, which is the
        # provider's claim about when the ad began (AGENTS.md section 8).
        sa.Column("not_seen_since_at", sa.DateTime(timezone=True), nullable=True),
        # The idempotence guard. Nullable because a row exists from its first
        # sighting, and its `last_status_run_id` is set at that moment.
        sa.Column("last_status_run_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_status_by_context")),
        # One status per context. Two rows for the same triple would be two
        # contradictory conclusions about one observation, with nothing to say
        # which was newer.
        sa.UniqueConstraint(
            "ad_id",
            "facebook_page_id",
            "country",
            name="uq_ad_status_by_context_ad_page_country",
        ),
        # A frozen vocabulary in the database, not only in Python: an
        # unrecognised status would otherwise surface as an unknown value in a
        # report, which is the worst place to discover one.
        sa.CheckConstraint(
            "current_status IN ('seen', 'not_seen_since', 'presumed_inactive')",
            name=op.f("ck_ad_status_by_context_current_status_vocabulary"),
        ),
        sa.CheckConstraint(
            "country ~ '^[A-Z]{2}$'",
            name=op.f("ck_ad_status_by_context_country_iso_alpha2"),
        ),
        # The absence boundary cannot be in the future: it is stamped from a run's
        # `finished_at`, and a value ahead of now() would mean it was built from a
        # run that has not finished -- which is exactly the run that must not count.
        sa.CheckConstraint(
            "not_seen_since_at IS NULL OR not_seen_since_at <= now()",
            name=op.f("ck_ad_status_by_context_not_seen_since_not_in_future"),
        ),
        sa.ForeignKeyConstraint(
            ["ad_id"],
            ["ads.id"],
            name="fk_ad_status_by_context_ad_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["facebook_page_id"],
            ["facebook_pages.id"],
            name="fk_ad_status_by_context_facebook_page_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_status_run_id"],
            ["collection_runs.id"],
            name="fk_ad_status_by_context_last_status_run_id",
            ondelete="RESTRICT",
        ),
    )

    # 1. The consecutive-complete-runs walk. Partial on `status = 'complete'`
    # because FAILED and PARTIAL runs are invisible to the query: a provider
    # outage must be able to neither advance nor reset an absence streak.
    op.create_index(
        "ix_collection_runs_page_country_complete",
        "collection_runs",
        ["facebook_page_id", "country", sa.text("finished_at DESC")],
        unique=False,
        postgresql_where=sa.text("status = 'complete'"),
    )

    # 2. "Which ads did this run observe", for bulk evaluation of one context.
    # The existing `UNIQUE (ad_id, collection_run_id)` leads on `ad_id` and cannot
    # answer it.
    op.create_index(
        "ix_seen_in_run_collection_run_id",
        "seen_in_run",
        ["collection_run_id"],
        unique=False,
    )

    # 3 and 4. The same evaluation from the status side, plus the idempotence
    # guard's lookup.
    op.create_index(
        "ix_ad_status_by_context_page_country",
        "ad_status_by_context",
        ["facebook_page_id", "country"],
        unique=False,
    )
    op.create_index(
        "ix_ad_status_by_context_last_status_run_id",
        "ad_status_by_context",
        ["last_status_run_id"],
        unique=False,
    )


def downgrade() -> None:
    # Indexes first, then the table. No trigger or function is involved, so
    # there is nothing else to order.
    op.drop_index("ix_ad_status_by_context_last_status_run_id", table_name="ad_status_by_context")
    op.drop_index("ix_ad_status_by_context_page_country", table_name="ad_status_by_context")
    op.drop_index("ix_seen_in_run_collection_run_id", table_name="seen_in_run")
    op.drop_index(
        "ix_collection_runs_page_country_complete", table_name="collection_runs"
    )

    op.drop_table("ad_status_by_context")

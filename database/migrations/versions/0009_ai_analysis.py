"""S3.1: `ad_analysis` and `ai_jobs` -- AI copy analysis, references only.

## What this adds

Two tables. `ad_analysis` is immutable evidence, one row per
`(copy_hash, analysis_version)`. `ai_jobs` is one row per **AI provider call
attempt**, referencing the `jobs` table that already exists.

## Why `ad_analysis` is keyed on copy and not on an ad

**`UNIQUE(copy_hash, analysis_version)`, and there is no `ad_id` in the key.**

Two different advertisers running identical words is a finding, and it is the
whole reason `copy_hash` exists (`services/copy_hash.py`). Keying an analysis on
an ad would force one paid model call per advertiser for one piece of copy and
would hide the duplicate in the place it matters.

So `source_ad_id` and `source_ad_snapshot_id` record **where that copy was first
seen** -- provenance for the `AI INTERPRETATION` badge, not identity. The
migration adds no `evidence_class` column because `providers/data/provenance.py`
derives that centrally and no table in this schema stores it.

`copy_hash` is **NOT NULL**. `AGENTS.md` section 7 requires every interpretation to
link back to the `copy_hash` it came from, and a NULL cannot satisfy that.
Snapshots predating S2.2 carry NULL and are permanently outside S3.1.

## Why `ai_jobs` is not a second queue

`jobs` **is** the queue (`services/jobs.py`, `SELECT ... FOR UPDATE SKIP LOCKED`).
`ai_jobs` therefore has no `worker_id`, no `lease_expires_at` and no retry
counter: duplicating those would be a second queue, which `AGENTS.md` section 12
forbids.

What it adds is what only an AI call produces: the model that answered, the
tokens it reported, and its cost. `UNIQUE(job_id, attempt_no)` makes one row per
**call**, so the single corrective retry `AGENTS.md` section 10 permits is a
second row rather than an overwrite -- which is what makes "a retry cannot create
a duplicate analysis" structural rather than a matter of care.

## Fourteen typed columns, not one `result` JSONB

`ARCHITECTURE.md` sketched `result JSONB`. Typed columns were chosen instead,
because a blob makes every one of these checks impossible: that no performance
field exists, that each field respects its length bound, that `confidence` is one
of three values. With typed columns a reviewer reads the contract off the schema,
and a future `estimated_roas` would be visible in a migration rather than buried
in a serialiser.

There is no `spend`, `roas`, `leads`, `conversions`, `reach`, `impressions`,
`clicks`, `ctr` or `cpc` column. Their absence is the control.

## Unavailable is not zero

Every token column is nullable, and the cost triple is all-or-nothing exactly as
`provider_runs` makes it. A provider that reports no usage leaves these NULL, and
NULL renders as an em dash. `0` would be a claim that a call cost nothing, which
is a different claim from "we were not told", and only the provider can make the
first one.

## Historical data is not touched

There is no backfill and none is possible: an analysis needs a provider call, and
nothing in S2.1-S2.4 recorded that any was made. `ads`, `ad_snapshots` and `jobs`
are not altered at all -- this migration only creates. A pre-S2.2 snapshot with a
NULL `copy_hash` simply never becomes eligible.

## Downgrade

Reversible, and rendered offline like every revision here. It issues `DROP`s,
which need explicit human consent under the checkpoint rules, so **it is never
executed**. Dropping these tables loses only derived rows: the copy they
described is still in `ad_snapshots.normalized`, so an analysis could be
re-derived by re-running the pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

#: Revision identifiers, used by Alembic.
revision: str = "0009_ai_analysis"
down_revision: str | None = "0008_media_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The fourteen analysis fields. Written out rather than looped so a migration
#: reads as the schema it creates, and so a future field added to the model is
#: visible here as a diff instead of arriving silently.
_ANALYSIS_COLUMNS = (
    "hook",
    "problem",
    "promise",
    "offer",
    "cta",
    "persona",
    "pain_point",
    "angle",
    "proof",
    "urgency",
    "awareness_level",
    "funnel_stage",
    "copy_structure",
    "why_it_may_work",
)

#: Mirrors `providers/ai/models.MAX_ANALYSIS_FIELD_CHARS`. Held as a number here
#: so the CHECK states the rule rather than deferring to whatever the model module
#: exports this week.
_MAX_FIELD_CHARS = 2_000

#: Mirrors `jobs`. An operator reading both tables should read one limit.
_MAX_ERROR_CHARS = 2_000

_SHA256 = "~ '^[0-9a-f]{64}$'"


def upgrade() -> None:
    op.create_table(
        "ad_analysis",
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
        # NOT NULL: an interpretation that cannot name its words cannot be badged
        # honestly (AGENTS.md section 7).
        sa.Column("copy_hash", sa.String(64), nullable=False),
        sa.Column("analysis_version", sa.String(64), nullable=False),
        # Provenance, not identity. Neither is in the unique key.
        sa.Column("source_ad_id", sa.Uuid(), nullable=False),
        sa.Column("source_ad_snapshot_id", sa.Uuid(), nullable=False),
        # The fourteen fields. All nullable: an ad with no urgency has none.
        # No spend/roas/leads/conversions/reach/impressions/clicks/ctr/cpc column
        # exists, and that absence is the control (AGENTS.md section 5).
        *[sa.Column(name, sa.Text(), nullable=True) for name in _ANALYSIS_COLUMNS],
        # One set of fields, in the copy's own language. There are deliberately no
        # `*_en` companions: English summaries, if ever wanted, are a new
        # analysis version with their own schema.
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("confidence", sa.String(16), nullable=True),
        # Which provider and model answered, and which prompt contract was used.
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_analysis")),
        # The identity, and the constraint that makes a lost race harmless.
        sa.UniqueConstraint("copy_hash", "analysis_version", name="uq_ad_analysis_copy_version"),
        sa.CheckConstraint(
            f"copy_hash {_SHA256}", name=op.f("ck_ad_analysis_copy_hash_is_sha256_hex")
        ),
        sa.CheckConstraint(
            "btrim(analysis_version) <> ''", name=op.f("ck_ad_analysis_analysis_version_not_blank")
        ),
        sa.CheckConstraint("btrim(provider) <> ''", name=op.f("ck_ad_analysis_provider_not_blank")),
        sa.CheckConstraint(
            "btrim(prompt_version) <> ''", name=op.f("ck_ad_analysis_prompt_version_not_blank")
        ),
        # A closed vocabulary. NULL stays valid -- "the model did not say" is not
        # the same as "low".
        sa.CheckConstraint(
            "confidence IS NULL OR confidence IN ('low', 'medium', 'high')",
            name=op.f("ck_ad_analysis_confidence_in_vocabulary"),
        ),
        # No interpretation field may grow without a migration.
        *[
            sa.CheckConstraint(
                f"{name} IS NULL OR length({name}) <= {_MAX_FIELD_CHARS}",
                name=op.f(f"ck_ad_analysis_{name}_max_length"),
            )
            for name in _ANALYSIS_COLUMNS
        ],
        # RESTRICT: an interpretation's evidence must not be able to take the
        # snapshot that justifies it away, nor be taken away with it.
        sa.ForeignKeyConstraint(
            ["source_ad_id"],
            ["ads.id"],
            name="fk_ad_analysis_source_ad_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_ad_snapshot_id"],
            ["ad_snapshots.id"],
            name="fk_ad_analysis_source_ad_snapshot_id",
            ondelete="RESTRICT",
        ),
    )

    # The badge follows this link back to the snapshot the model read, so it needs
    # its own index: the FK is not unique.
    op.create_index(
        "ix_ad_analysis_source_ad_snapshot_id",
        "ad_analysis",
        ["source_ad_snapshot_id"],
        unique=False,
    )

    op.create_table(
        "ai_jobs",
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
        # The queue row that drove this call. This is what makes `ai_jobs` an
        # accounting record rather than a second queue: it has no lease, no worker
        # id and no retry counter of its own.
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.SmallInteger(), nullable=False),
        sa.Column("call_kind", sa.String(32), nullable=False),
        sa.Column("copy_hash", sa.String(64), nullable=False),
        sa.Column("analysis_version", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        # Provider-reported, verbatim. NULL means the provider reported nothing --
        # never 0, which would be a cost claim nobody made.
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(12, 6), nullable=True),
        sa.Column("cost_currency", sa.String(3), nullable=True),
        sa.Column("cost_method", sa.Text(), nullable=True),
        sa.Column("error_type", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_jobs")),
        # One row per CALL, so the single corrective retry is a second row rather
        # than an overwrite of the attempt that failed. Also the index serving
        # "which calls did this job make", so no second index on `job_id`.
        sa.UniqueConstraint("job_id", "attempt_no", name="uq_ai_jobs_job_attempt"),
        sa.CheckConstraint("attempt_no >= 1", name=op.f("ck_ai_jobs_attempt_no_positive")),
        sa.CheckConstraint(
            "status IN ('succeeded', 'invalid_response', 'failed')",
            name=op.f("ck_ai_jobs_status"),
        ),
        sa.CheckConstraint(
            "call_kind IN ('initial', 'invalid_json_retry')", name=op.f("ck_ai_jobs_call_kind")
        ),
        sa.CheckConstraint(f"copy_hash {_SHA256}", name=op.f("ck_ai_jobs_copy_hash_is_sha256_hex")),
        sa.CheckConstraint(
            "btrim(analysis_version) <> ''", name=op.f("ck_ai_jobs_analysis_version_not_blank")
        ),
        sa.CheckConstraint("btrim(provider) <> ''", name=op.f("ck_ai_jobs_provider_not_blank")),
        sa.CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0",
            name=op.f("ck_ai_jobs_prompt_tokens_not_negative"),
        ),
        sa.CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name=op.f("ck_ai_jobs_completion_tokens_not_negative"),
        ),
        sa.CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0",
            name=op.f("ck_ai_jobs_total_tokens_not_negative"),
        ),
        sa.CheckConstraint(
            "cost_amount IS NULL OR cost_amount >= 0",
            name=op.f("ck_ai_jobs_cost_amount_not_negative"),
        ),
        # All three cost fields or none, exactly as `provider_runs` does it. A
        # figure with no method is an unexplained number, and an unexplained
        # number is not stored.
        sa.CheckConstraint(
            "(cost_amount IS NULL AND cost_currency IS NULL AND cost_method IS NULL) OR "
            "(cost_amount IS NOT NULL AND cost_currency IS NOT NULL AND cost_method IS NOT NULL)",
            name="ck_ai_jobs_cost_all_or_nothing",
        ),
        # A success carries no failure text; a failure must say why.
        sa.CheckConstraint(
            "status != 'succeeded' OR (error_type IS NULL AND error_message IS NULL)",
            name=op.f("ck_ai_jobs_success_has_no_error"),
        ),
        sa.CheckConstraint(
            "status = 'succeeded' OR error_message IS NOT NULL",
            name=op.f("ck_ai_jobs_failure_has_message"),
        ),
        sa.CheckConstraint(
            f"error_message IS NULL OR length(error_message) <= {_MAX_ERROR_CHARS}",
            name=op.f("ck_ai_jobs_error_message_max"),
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name=op.f("ck_ai_jobs_duration_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_ai_jobs_job_id",
            ondelete="RESTRICT",
        ),
    )

    # Two real access paths, and no others: "which calls did this copy take", and
    # "what is in flight right now".
    op.create_index("ix_ai_jobs_copy_hash", "ai_jobs", ["copy_hash"], unique=False)
    op.create_index(
        "ix_ai_jobs_status_started_at", "ai_jobs", ["status", "started_at"], unique=False
    )


def downgrade() -> None:
    # Indexes first, then tables. Nothing else is involved -- no trigger, no
    # function, and no row in any pre-existing table was created by this revision.
    op.drop_index("ix_ai_jobs_status_started_at", table_name="ai_jobs")
    op.drop_index("ix_ai_jobs_copy_hash", table_name="ai_jobs")
    op.drop_index("ix_ad_analysis_source_ad_snapshot_id", table_name="ad_analysis")

    op.drop_table("ai_jobs")
    op.drop_table("ad_analysis")

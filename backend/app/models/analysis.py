"""What a model said about an ad's copy, and what each call cost to obtain.

## Two tables, two completely different lifetimes

`AdAnalysis` is **immutable evidence**: one row per `(copy_hash,
analysis_version)`, written once when a model answered, never updated. It is an
`AI_INTERPRETATION` in the sense `AGENTS.md` section 7 defines -- always badged,
always traceable back to the snapshot and `copy_hash` it came from.

`AIJob` is **mutable accounting**: one row per provider call attempt, recording
which model was asked, what it said it used, and what it cost. It is written
while the call is in flight and finished afterwards.

Conflating them would be the mistake: an analysis that "updated" would mean a
stored interpretation had changed its mind, and a call record that could not be
updated would lose the cost of the retry that produced the analysis.

## Why `AdAnalysis` is keyed on copy, not on an ad

**`UNIQUE(copy_hash, analysis_version)`, and `ad_id` is not in the key.**

Two different advertisers running identical words is a *finding*
(`services/copy_hash.py` says so in as many words), and it is the reason
`copy_hash` exists. Keying analysis on `ad_id` would force one paid model call
per advertiser for one piece of copy, and would make the duplicate invisible in
the place it matters. So the key is the copy, and `source_ad_id` /
`source_ad_snapshot_id` record **where that copy was first seen** -- provenance,
not identity.

That also answers the "latest snapshot or a specific one" question without
choosing: any snapshot with that `copy_hash` resolves to the same analysis, and
the badge links to the snapshot the analysis was actually derived from.

**`copy_hash` is NOT NULL.** `AGENTS.md` section 7 requires every interpretation
to link back to the `copy_hash` it came from, and a NULL cannot satisfy that.
Snapshots predating S2.2 carry NULL and are permanently outside S3.1.

## `AIJob` is a call-attempt record, not a second queue

`jobs` **is** the queue (`services/jobs.py`, `FOR UPDATE SKIP LOCKED`). This
table deliberately has no `worker_id`, no `lease_expires_at` and no retry
counter: those belong to `jobs`, and duplicating them would create a second
queue, which `AGENTS.md` section 12 forbids.

What it adds is what only an AI call produces: the model that answered, the
tokens it reported, and its cost. One row **per provider call**, so the
invalid-output retry is a second row against the same `job_id` rather than an
overwritten one. That is what makes "a retry cannot create a duplicate
analysis" structural -- `ad_analysis` is only ever written after a validated
response, and this table records the calls that did not produce one.

## Unavailable is not zero

Every token and cost column is nullable, and the cost triple is all-or-nothing
exactly as `provider_runs` makes it. A provider that reports no usage leaves
these NULL, and NULL renders as an em dash. `0` is a claim that a call cost
nothing, which is a different claim from "we were not told", and only the
provider can make the first one.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Final

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

#: The digest rules, written out rather than imported. A migration and a
#: constraint should record what the rule *is*, not whatever a module says today.
_SHA256_CHECK = "~ '^[0-9a-f]{64}$'"

#: Mirrors `jobs`' own bound. Duplicated rather than imported because a model
#: module depending on a service module inverts the layering, and one number
#: written twice is better than an import in the wrong direction.
ERROR_MESSAGE_MAX: Final = 2_000

#: Ceiling on one analysis field's text, matching `providers.ai.models`. Held as
#: a number rather than imported so the constraint below states the rule instead
#: of deferring to whatever the model module happens to export this week.
MAX_ANALYSIS_FIELD_CHARS: Final = 2_000


class AIJobStatus(str):
    """How one provider call ended.

    A plain string set with a CHECK rather than a native enum, so adding a state
    is an ordinary migration. `jobs` uses the same approach for the same reason.
    """

    SUCCEEDED = "succeeded"
    INVALID_RESPONSE = "invalid_response"
    FAILED = "failed"


class AIJobCallKind(str):
    """Which call this row records.

    `initial` is the first ask. `invalid_json_retry` is the single corrective
    retry `AGENTS.md` section 10 permits, and it is a separate row so the cost
    of getting it wrong is visible rather than folded into the success.
    """

    INITIAL = "initial"
    INVALID_JSON_RETRY = "invalid_json_retry"


class AdAnalysis(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One model's reading of one piece of copy. Written once, never revised.

    Fourteen nullable text columns rather than one `result` JSONB, and that is a
    decision with teeth. A JSONB blob would have made every one of these checks
    impossible: that no performance field exists, that each field respects its
    length bound, that `confidence` is one of three values. With typed columns a
    reviewer reads the contract off the schema, and a future field named
    `estimated_roas` would be visible in a migration rather than buried in a
    serialiser.
    """

    __tablename__ = "ad_analysis"

    #: The S2.2 copy digest this analysis is **about**. NOT NULL: an
    #: interpretation that cannot name its words cannot be badged honestly.
    copy_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    #: The analysis contract that produced this row. A v2 analysis is a new row,
    #: not a rewrite, so a v1 result keeps meaning exactly what it meant.
    analysis_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    #: The ad whose snapshot first produced this copy. Provenance, **not**
    #: identity -- see the module docstring on why it is not in the key.
    source_ad_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("ads.id", name="fk_ad_analysis_source_ad_id", ondelete="RESTRICT"),
        nullable=False,
    )

    #: The snapshot the model actually read. This is the link the
    #: `AI INTERPRETATION` badge follows (AGENTS.md section 7).
    source_ad_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey(
            "ad_snapshots.id", name="fk_ad_analysis_source_ad_snapshot_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )

    # ---- The fourteen analysis fields ----------------------------------
    #
    # Each nullable, each bounded, each in the language the copy was in. There is
    # no `spend`, `roas`, `leads`, `conversions`, `reach`, `impressions`,
    # `clicks`, `ctr` or `cpc` column, and their absence is the control: those
    # are not public for commercial ads (AGENTS.md section 5), and a schema that
    # cannot hold them cannot be asked to display them.

    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    promise: Mapped[str | None] = mapped_column(Text, nullable=True)
    offer: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona: Mapped[str | None] = mapped_column(Text, nullable=True)
    pain_point: Mapped[str | None] = mapped_column(Text, nullable=True)
    angle: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof: Mapped[str | None] = mapped_column(Text, nullable=True)
    urgency: Mapped[str | None] = mapped_column(Text, nullable=True)
    awareness_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    funnel_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    copy_structure: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_it_may_work: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Metadata about the analysis, not about the ad ------------------

    #: The language the analysis was written in, as the model reported it.
    #: There is deliberately **no `*_en` companion column**: S3.1 has one set of
    #: fields, in the copy's own language. English summaries, if ever wanted, are
    #: a new analysis version with its own schema.
    language: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    #: The model's own confidence in the interpretation. Never a confidence in
    #: any number about results, because there are none.
    confidence: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)

    #: Which provider produced this. Recorded so a stored interpretation can
    #: always be traced back to what wrote it.
    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    #: Which model answered, when the provider names one. NULL when it does not,
    #: and never a name written into this module: it comes from settings.
    model: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    #: The prompt contract used. Separate from `analysis_version` because the two
    #: version independently -- a prompt fix that changes no schema field is
    #: still a new prompt, and collapsing them would make one of the two lie.
    prompt_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    __table_args__ = (
        # The identity. One analysis per copy per contract version. This is what
        # makes a lost race harmless: a second worker inserting the same analysis
        # hits this constraint and does nothing, rather than paying for -- and
        # storing -- a second identical interpretation.
        UniqueConstraint("copy_hash", "analysis_version", name="uq_ad_analysis_copy_version"),
        CheckConstraint(f"copy_hash {_SHA256_CHECK}", name="copy_hash_is_sha256_hex"),
        not_blank("analysis_version"),
        not_blank("provider"),
        not_blank("prompt_version"),
        # Confidence is a closed three-value vocabulary, and an unrecognised
        # value must not be stored as though the model had expressed one. NULL
        # remains valid: "the model did not say" is not the same as "low".
        CheckConstraint(
            "confidence IS NULL OR confidence IN ('low', 'medium', 'high')",
            name="confidence_in_vocabulary",
        ),
        # The badge follows this link back to the snapshot the model read
        # (AGENTS.md section 7), so it needs its own index: neither FK is unique.
        Index("ix_ad_analysis_source_ad_snapshot_id", "source_ad_snapshot_id"),
    )


class AIJob(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One provider call attempt: what was asked, what it cost, how it ended.

    **Not a queue.** `jobs` is the queue. This table has no lease, no worker id
    and no retry counter precisely so it cannot be mistaken for one -- a second
    queue is forbidden by `AGENTS.md` section 12, and the fastest way to build
    one by accident is to give a table a status column and call it a job.

    One row per **call**, not per job. The invalid-output retry is therefore a
    second row against the same `job_id`, and the cost of the mistake that
    triggered it stays visible instead of being overwritten by the success that
    followed.
    """

    __tablename__ = "ai_jobs"

    #: The queue row that drove this call. RESTRICT: a call record must not be
    #: able to take the job that explains it away, nor be taken away with it.
    job_id: Mapped[uuid.UUID] = mapped_column(
        UuidId,
        ForeignKey("jobs.id", name="fk_ai_jobs_job_id", ondelete="RESTRICT"),
        nullable=False,
    )

    #: Which call this is, 1-based. `UNIQUE(job_id, attempt_no)` makes a
    #: duplicated attempt number impossible, so a retry cannot overwrite the row
    #: recording the attempt before it.
    attempt_no: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False)

    #: `initial`, or the single `invalid_json_retry` AGENTS.md section 10 allows.
    call_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    #: What was analysed, and under which contract. Recorded on the call as well
    #: as on the analysis so a failed call is still diagnosable.
    copy_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    analysis_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)

    #: Which provider, and which model within it. The model comes from settings;
    #: NULL when the provider names none, never a name written into code.
    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)

    # ---- Usage and cost ------------------------------------------------
    #
    # Provider-reported, stored verbatim. NULL means the provider reported
    # nothing -- never `0`, which would be a cost claim nobody made. A partially
    # reported usage is kept as given rather than completed from the parts we
    # happen to have.

    prompt_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: Cost, all three or none, exactly as `provider_runs` does it. `cost_method`
    #: is the part that makes a figure honest: it says how the number was
    #: arrived at, and a calculated figure without one is not storable.
    cost_amount: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(sa.String(3), nullable=True)
    cost_method: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Failure and timing --------------------------------------------
    #
    #: The typed class name, e.g. `RateLimited`, `InvalidResponse`. Read with a
    #: `retryable` flag rather than by matching the message.
    error_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    #: Truncated to `ERROR_MESSAGE_MAX`. Never the prompt, never a response body,
    #: never a credential: a provider's error text can quote back what it was
    #: sent, and this column is read by operators.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    __table_args__ = (
        # One row per call attempt. Also the index that serves "which calls did
        # this job make", so no second index on `job_id` is needed.
        UniqueConstraint("job_id", "attempt_no", name="uq_ai_jobs_job_attempt"),
        CheckConstraint("attempt_no >= 1", name="attempt_no_positive"),
        CheckConstraint(
            "status IN ('succeeded', 'invalid_response', 'failed')", name="ck_ai_jobs_status"
        ),
        CheckConstraint(
            "call_kind IN ('initial', 'invalid_json_retry')", name="ck_ai_jobs_call_kind"
        ),
        CheckConstraint(f"copy_hash {_SHA256_CHECK}", name="copy_hash_is_sha256_hex"),
        not_blank("analysis_version"),
        not_blank("provider"),
        # Token counts cannot be negative. A negative count is not "unknown",
        # it is a provider reporting something impossible.
        CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0", name="prompt_tokens_not_negative"
        ),
        CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name="completion_tokens_not_negative",
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0", name="total_tokens_not_negative"
        ),
        CheckConstraint("cost_amount IS NULL OR cost_amount >= 0", name="cost_amount_not_negative"),
        # Every analysis field respects the same ceiling. A `CHECK` cannot carry
        # a bind parameter, so the number is written out -- and the rule is that
        # no interpretation field may grow without a migration.
        *(
            CheckConstraint(
                f"{column} IS NULL OR length({column}) <= {MAX_ANALYSIS_FIELD_CHARS}",
                name=f"{column}_max_length",
            )
            for column in (
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
        ),
        # All three cost fields or none. A figure with no method is an
        # unexplained number, and an unexplained number is not stored.
        CheckConstraint(
            "(cost_amount IS NULL AND cost_currency IS NULL AND cost_method IS NULL) OR "
            "(cost_amount IS NOT NULL AND cost_currency IS NOT NULL AND cost_method IS NOT NULL)",
            name="cost_all_or_nothing",
        ),
        # A successful call carries no failure text, and a failed one must say
        # why -- "it silently did not work" is the outcome this exists to stop.
        CheckConstraint(
            "status != 'succeeded' OR (error_type IS NULL AND error_message IS NULL)",
            name="success_has_no_error",
        ),
        CheckConstraint(
            "status = 'succeeded' OR error_message IS NOT NULL", name="failure_has_message"
        ),
        CheckConstraint(
            # A literal rather than a bound parameter: a CHECK cannot carry one
            # through DDL, and the number is fixed at 2000 either way. Same
            # bound `jobs` uses, so an operator reading both tables reads the
            # same limit.
            f"error_message IS NULL OR length(error_message) <= {ERROR_MESSAGE_MAX}",
            name="error_message_max",
        ),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_not_negative"),
        # "Which analyses ran in this window", and "which calls did this piece
        # of copy take". The dedupe check reads `ad_analysis` by its unique
        # constraint; these two answer the questions that constraint cannot.
        Index("ix_ai_jobs_copy_hash", "copy_hash"),
        Index("ix_ai_jobs_status_started_at", "status", "started_at"),
    )

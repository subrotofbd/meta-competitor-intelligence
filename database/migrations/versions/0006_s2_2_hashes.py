"""S2.2: `copy_hash` and `creative_hash` on `ad_snapshots`, plus their indexes.

## What this adds, and what it deliberately does not

Two nullable `VARCHAR(64)` columns, two named `CHECK` constraints, two plain
indexes. Nothing else. In particular it does **not** add `ad_creatives`,
`ad_platforms`, `ad_countries` or `landing_pages` -- those are not S2.2 scope,
and `ad_creatives` in particular cannot be built from the current normalized
contract at all: `app/providers/data/normalize.py::_read_body` reads only
`bodies[0]` and flattens it, so there is no card-level structure to store. The
committed corpus has nine ads, every one single-bodied. A per-card table built
today would be fabricating rows, so it is deferred rather than approximated.

## Why the columns are nullable and there is no backfill

`ad_snapshots` is append-only, enforced by `trg_ad_snapshots_append_only`, which
refuses `UPDATE` and `DELETE`. A backfill would require exactly that, so a
snapshot written before this revision can never be given a digest -- and that is
the correct trade, because the alternative is rewriting history, which is the one
thing this table exists to prevent. `NULL` therefore carries a meaning: *this
observation predates S2.2*. It is never a default, never a computed placeholder,
and every query that groups on these columns filters `NULL` out explicitly
(`app/services/duplicate_detection.py`).

## The state this migration was written against

Before this revision was authored, `ads`, `ad_snapshots` and `seen_in_run` were
each verified to hold **0 rows**, at revision `0005_ads_data_origin_check`. So
the migration is not merely non-destructive, it has nothing to act on. The
nullable design is what would keep it non-destructive if that were not true,
which is why it is the design rather than a convenience.

## Why the checks accept NULL without an `IS NULL OR` guard

A `CHECK` constraint is satisfied unless it evaluates to `FALSE`, and a regex
match against `NULL` yields `NULL`. So the identical expression S2.1 uses for
`content_hash` -- and which S2.2 reuses verbatim -- accepts a NULL row while
still refusing a malformed digest. Adding `IS NULL OR` would be redundant, and
the expression is kept byte-identical to S2.1's so there is one validation
pattern in the schema rather than two that can drift.

## Downgrade

Reversible, and rendered offline like every other revision here. It issues
`DROP`s, and the checkpoint rules require explicit human consent for a
destructive command, so **it is never executed** -- `test_schema_integration.py`
renders it with `alembic downgrade --sql` and asserts the statements, without
connecting.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

#: Revision identifiers, used by Alembic.
revision: str = "0006_s2_2_hashes"
down_revision: str | None = "0005_ads_data_origin_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The SHA-256 hex validation, written out rather than imported. A migration
#: that read application code would be recording whatever that code says today
#: instead of what it said when it ran, which is the difference between a record
#: and a tautology.
_SHA256_HEX = "copy_hash ~ '^[0-9a-f]{64}$'"
_SHA256_HEX_CREATIVE = "creative_hash ~ '^[0-9a-f]{64}$'"


def upgrade() -> None:
    # Nullable, no default, no backfill. See the module docstring: the table is
    # append-only, so a pre-S2.2 row keeps NULL for ever rather than being
    # rewritten to hold a value it was never observed with.
    op.add_column("ad_snapshots", sa.Column("copy_hash", sa.String(64), nullable=True))
    op.add_column("ad_snapshots", sa.Column("creative_hash", sa.String(64), nullable=True))

    # The same validation pattern S2.1 used, so a malformed digest cannot make
    # duplicate detection silently stop finding anything.
    op.create_check_constraint(
        op.f("ck_ad_snapshots_copy_hash_is_sha256_hex"), "ad_snapshots", _SHA256_HEX
    )
    op.create_check_constraint(
        op.f("ck_ad_snapshots_creative_hash_is_sha256_hex"), "ad_snapshots", _SHA256_HEX_CREATIVE
    )

    # One per access pattern in `app/services/duplicate_detection.py`: grouping
    # snapshots by digest to find ads that say the same thing, and by digest to
    # find ads that use the same assets. Plain indexes -- a partial one is not
    # reliably compared by autogenerate, and phantom drift from that is a worse
    # cost than the handful of NULL rows it would exclude.
    op.create_index(op.f("ix_ad_snapshots_copy_hash"), "ad_snapshots", ["copy_hash"])
    op.create_index(op.f("ix_ad_snapshots_creative_hash"), "ad_snapshots", ["creative_hash"])


def downgrade() -> None:
    # Indexes first, then the checks, then the columns -- the reverse of the
    # upgrade order, and the only order in which each object still exists when
    # the statement naming it runs.
    op.drop_index(op.f("ix_ad_snapshots_creative_hash"), table_name="ad_snapshots")
    op.drop_index(op.f("ix_ad_snapshots_copy_hash"), table_name="ad_snapshots")

    op.drop_constraint(
        op.f("ck_ad_snapshots_creative_hash_is_sha256_hex"), "ad_snapshots", type_="check"
    )
    op.drop_constraint(
        op.f("ck_ad_snapshots_copy_hash_is_sha256_hex"), "ad_snapshots", type_="check"
    )

    op.drop_column("ad_snapshots", "creative_hash")
    op.drop_column("ad_snapshots", "copy_hash")

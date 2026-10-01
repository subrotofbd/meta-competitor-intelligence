"""S3.2: expression indexes for ad-copy search, on PostgreSQL only.

## What this adds, and what it deliberately does not

Two GIN indexes over the **same four-field copy projection**:

1. `to_tsvector('simple', ...)` for whole-word and phrase matching.
2. the identical text expression with `gin_trgm_ops` for partial and fuzzy matching.

Nothing else. No column is added, no table changes, and no row is written.

## Why an expression index and not a generated column

The copy text lives in exactly one place: inside `ad_snapshots.normalized`, a JSONB
column. `AGENTS.md` section 8 makes that column **append-only evidence** -- the
trigger refuses every UPDATE, and it cannot be recomputed or re-derived without
re-collecting from the provider, which for a commercial ad that stopped running is
often impossible.

So search must read the copy in place. The two ways to index a JSONB read are a
generated column (materialising the text into a real column) or an expression index
(materialising nothing, computing the same expression at write time into the index).

An **expression index** is the right one here:

- The stored document is never touched, so no rewriting of evidence and no risk of
  the JSON and the index disagreeing.
- A generated column would be a *second* copy of provider text, which is one more
  place a redaction, a length limit or a normalisation rule has to be enforced.
- Nothing about `content_hash`, `copy_hash` or `creative_hash` changes. They hash the
  `RawAdRecord`, never the stored JSON, so an index over JSON cannot move a digest.

## Why `'simple'` and not `'english'`

`'simple'` performs no stemming and no stop-word removal. This corpus is Hindi and
Hinglish: an English stemmer mangles Devanagari and discards short tokens a Hindi
phrase depends on. It also keeps the expression stable -- attaching a dictionary
later would silently invalidate every stored tsvector.

## One expression, two indexes, on purpose

The trigram index covers the *same* text as the full-text index rather than just
`primary_text`. A user searching for a word that appears only in a headline would
otherwise get no fuzzy result, which is the kind of inconsistency that reads as
"search is unreliable".

## The expression is written out rather than imported

`backend/app/services/ad_search.py` builds the same projection for queries. A
migration should record what the rule *is*, not depend on a service module that may
change. That makes the two copies a genuine risk -- an index whose expression differs
from the query's is **silently unused** once PostgreSQL switches the statement to a
generic plan -- correct results, sequential scan, no signal. So
`test_every_copy_of_the_search_projection_agrees` compares the SQL all three produce
and fails if they ever drift, and
`test_the_search_query_matches_the_index_expression_exactly` pins every literal in
the query so none can quietly become a bind parameter.

## Downgrade

Reversible: two `drop_index` statements, no data implications. Rendered offline in
tests and **never executed** without explicit consent -- it is a DROP.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

#: Revision identifiers, used by Alembic.
revision: str = "0011_api_search_indexes"
down_revision: str | None = "0010_ai_jobs_cost_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The copy fields searched, in the order they are concatenated. Order does not
#: affect matching, but it fixes the expression text, and a stable text is what lets
#: the index and the query agree.
_COPY_FIELDS: Sequence[str] = ("primary_text", "headline", "description", "cta")

#: The projection. Written once and reused by both indexes so the two can never
#: cover different text -- which would be worse than having only one.
_PROJECTION: str = " || ' ' || ".join(
    f"coalesce(normalized->>'{field}', '')" for field in _COPY_FIELDS
)

#: `'simple'` is a literal, not a parameter, for the same reason the constraint text
#: in earlier revisions is: an expression index needs an immutable expression.
_TSVECTOR: str = f"to_tsvector('simple', {_PROJECTION})"

_INDEX = "ix_ad_snapshots_copy_fts_gin"


def upgrade() -> None:
    # Written as explicit SQL rather than through `op.create_index`. Two reasons,
    # both learned the hard way:
    #
    # 1. `op.create_index` quotes a plain string as an *identifier*, so the raw
    #    expression becomes a column name and fails with "column does not exist".
    #    `sa.text()` fixes that.
    # 2. `sa.text()` then breaks the opclass: Alembic renders `postgresql_ops`
    #    against the text key and emits `... || 'cta', '' gin_trgm_ops)` -- the
    #    opclass lands inside the concatenation and PostgreSQL reports a syntax
    #    error at `||`.
    #
    # An opclass on an expression index needs its own parentheses in PostgreSQL
    # (`((expr) opclass)`), which no helper here expresses. Explicit SQL says
    # exactly that and nothing else.
    op.execute(f"CREATE INDEX {_INDEX} ON ad_snapshots USING gin ({_TSVECTOR})")
    op.execute(
        "CREATE INDEX ix_ad_snapshots_copy_trgm_gin ON ad_snapshots "
        f"USING gin (({_PROJECTION}) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_ad_snapshots_copy_trgm_gin", table_name="ad_snapshots")
    op.drop_index(_INDEX, table_name="ad_snapshots")

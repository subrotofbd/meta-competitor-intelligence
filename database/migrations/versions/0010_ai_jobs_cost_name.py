"""Fix the doubled prefix on `ai_jobs`' cost constraint name.

## What is wrong

`0009_ai_analysis` created one constraint with a literal, already-prefixed name:

    name="ck_ai_jobs_cost_all_or_nothing"

while every other constraint in that revision passed a bare suffix through
`op.f()`, letting the metadata convention (`"ck": "ck_%(table_name)s_%(constraint_name)s"`
in `app/db/base.py`) add the prefix. The convention then added it a second time,
and the database holds:

    ck_ai_jobs_ck_ai_jobs_cost_all_or_nothing

`models/analysis.py` declares the bare `cost_all_or_nothing`, so the ORM metadata
and the database disagreed about the constraint's name from the moment `0009`
ran. `alembic check` does not compare `CHECK` constraint *names* -- only their
expressions -- which is why it reported no drift and the mismatch went unnoticed.

## Why it matters even though the behaviour is identical

The expression is byte-for-byte the same and the constraint fires exactly as
before, so nothing is mis-evaluated. What is wrong is that the constraint an
operator sees when they describe the table cannot be found by the name the code
that declared it uses, and every future migration, error-message assertion or
manual repair that reaches for `ck_ai_jobs_cost_all_or_nothing` misses.

## What this migration does

Drops the doubled name and re-adds the same constraint under the conventional one.
**DDL only -- no row is read, written or deleted**, and the replacement expression
is identical to the original, so the constraint's meaning does not change at any
point: PostgreSQL holds the old constraint until the new one is added.

Renaming rather than recreating would need `ALTER TABLE ... RENAME CONSTRAINT`,
which PostgreSQL does not support for CHECK constraints -- hence drop-then-add.

## Downgrade

Restores the doubled name and nothing else. Purely a rename in both directions.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

#: Revision identifiers, used by Alembic.
#:
#: Kept short deliberately: `alembic_version.version_num` is `VARCHAR(32)`, and a
#: longer descriptive id fails at *insert* with a truncation error rather than at
#: revision load, which is a confusing place to discover the limit.
revision: str = "0010_ai_jobs_cost_name"
down_revision: str | None = "0009_ai_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The expression `0009` created, reproduced exactly. Changing it here would be a
#: semantic change wearing a rename's clothes, so it is byte-identical on purpose.
_EXPRESSION = (
    "(cost_amount IS NULL AND cost_currency IS NULL AND cost_method IS NULL) OR "
    "(cost_amount IS NOT NULL AND cost_currency IS NOT NULL AND cost_method IS NOT NULL)"
)

#: What `0009` actually created, by accident.
_DOUBLED = "ck_ai_jobs_ck_ai_jobs_cost_all_or_nothing"

#: What the ORM metadata declares, resolved through the naming convention.
_CONVENTIONAL = "ck_ai_jobs_cost_all_or_nothing"


def upgrade() -> None:
    # `op.f()` marks a name as already final, so the metadata convention leaves it
    # alone. Without it the convention prefixes *again* -- which is precisely the
    # mistake that produced `_DOUBLED` in the first place.
    op.drop_constraint(op.f(_DOUBLED), "ai_jobs", type_="check")
    op.create_check_constraint(op.f(_CONVENTIONAL), "ai_jobs", _EXPRESSION)


def downgrade() -> None:
    op.drop_constraint(op.f(_CONVENTIONAL), "ai_jobs", type_="check")
    op.create_check_constraint(op.f(_DOUBLED), "ai_jobs", _EXPRESSION)

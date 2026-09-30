"""Enable the pg_trgm extension.

Revision ID: 0001_pg_trgm
Revises:
Create Date: 2026-09-30

Why this is the first migration, and why it is not a table:

`ARCHITECTURE.md` puts ad search on PostgreSQL -- `tsvector` for full text and
`pg_trgm` for fuzzy matching -- with no external search engine. `pg_trgm` is a
database-level extension, so it is part of the foundation rather than part of
any table, and it must exist before the first GIN trigram index is created with
the ads schema in S1.1.

S0.2 creates no domain tables by design, so this migration is the whole of the
database foundation for now.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_pg_trgm"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install pg_trgm. IF NOT EXISTS keeps a re-run on a prepared database safe."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    """Remove pg_trgm.

    Reversible, and therefore destructive to anything that depends on it. In
    practice the dependency set is empty at this revision because no table
    exists yet, but this still must not be run without explicit approval: it is
    a DROP.
    """
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")

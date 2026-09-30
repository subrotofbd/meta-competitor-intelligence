"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
${imports if imports else ""}

# Note on imports: `import sqlalchemy as sa` is deliberately NOT included here.
# Most generated migrations do not reference it, and the blanket import makes
# ruff flag F401 on every one of them. Add it by hand in the same file if a
# hand-written operation needs it.

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """${upgrades if upgrades else "pass"}"""


def downgrade() -> None:
    """${downgrades if downgrades else "pass"}"""

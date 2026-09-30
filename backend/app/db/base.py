"""Declarative base and shared metadata conventions.

S0.2 deliberately defines no domain tables. What it does establish is the
metadata every future model inherits, plus a constraint naming convention.

The naming convention is not decoration. Alembic drops constraints *by name* on
downgrade, and unnamed constraints get hash-based names that can shift between
runs. Without a convention, a migration can generate cleanly and then fail to
reverse. `ARCHITECTURE.md` requires every migration to be reversible, so this
belongs in the foundation rather than in the first domain table.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for every ORM model.

    S1.1 adds the model modules. Until then the metadata is intentionally empty
    and autogenerate produces no table diffs.
    """

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            # Requires every CheckConstraint to be named explicitly. That is
            # intended: an unnamed check cannot be reversed by name later.
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )

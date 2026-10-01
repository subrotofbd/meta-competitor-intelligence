"""Alembic environment.

Two deliberate departures from the generated template:

* The database URL is read from `app.core.config.Settings` instead of
  `alembic.ini`, so the password lives in exactly one place.
* `logging.config.fileConfig` is not called. It would tear out the structured
  JSON handler from `app.core.logging` and install Alembic's own console
  formatter, so a migration would log in a different shape from every other
  process. The same handler is configured instead, and migrations emit JSON.

This module runs only under the `alembic` command; it is not importable
standalone, because `alembic.context` is only populated during a migration run.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base

config = context.config

settings = get_settings()
configure_logging(settings)

target_metadata = Base.metadata

# Registering the models is what fills `Base.metadata` with the tables, and an
# empty metadata is why autogenerate would otherwise see no drift at all. The
# imported names are unused here on purpose -- the import *is* the effect -- so
# the warning is silenced rather than faked with a dummy assignment.
from app import models  # noqa: E402,F401
from app.models.ads import SEARCH_EXPRESSION_INDEX_NAMES  # noqa: E402

# Compare column types as well as names/columns, so a changed type is caught
# instead of silently ignored.
_COMPARE_TYPE = True

#: Indexes that exist in the database but cannot be expressed in ORM metadata.
#:
#: S3.2's two search indexes are expression indexes over `ad_snapshots.normalized`.
#: They are declared on the model as `sa.text(...)` so they are documented in one
#: place, but autogenerate cannot round-trip them, so the comparison reports each
#: as both "remove" and "add". See `models.ads.SEARCH_EXPRESSION_INDEX_NAMES` for the
#: full reasoning -- it lives there rather than here because `env.py` reads
#: `alembic.context` at module level and so cannot be imported by anything else.
#:
#: Excluding them by name is the honest fix. Leaving the noise in place would make
#: `alembic check` permanently red, and a permanently red gate stops being read --
#: which is how real drift gets shipped. Everything else is still compared, so a
#: genuine change to a table, column, constraint or ordinary index is still caught.
#:
#: The indexes themselves are still fully tracked by migration `0011`, which is
#: what actually creates and drops them.
_EXPRESSION_INDEX_NAMES = SEARCH_EXPRESSION_INDEX_NAMES


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Filter the two un-representable expression indexes out of the comparison."""
    if type_ == "index" and name in _EXPRESSION_INDEX_NAMES:
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    For reviewing a migration, or for a DBA who applies SQL by hand.
    """
    context.configure(
        url=settings.dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=_COMPARE_TYPE,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply the migrations inside a transaction."""
    # NullPool: a migration is a short, single-use process. Pooling connections
    # here would only keep them open for nothing.
    connectable = create_engine(
        settings.dsn,
        poolclass=pool.NullPool,
        pool_pre_ping=True,
    )
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=_COMPARE_TYPE,
                include_object=include_object,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

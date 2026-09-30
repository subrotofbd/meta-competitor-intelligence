"""Live PostgreSQL behaviour, against the local compose container.

    docker compose up -d      # required
    uv run pytest -m integration

These are deliberately not skipped when the database is unreachable. A skip is
indistinguishable from a pass in CI output, and this project does not report
unverified work as green.

Every statement here is read-only or creates a *temporary* table that PostgreSQL
discards with the session. Nothing in the development database is modified, and
nothing is ever dropped.
"""

from __future__ import annotations

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import check_database, get_engine, session_scope
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.integration


def test_database_reports_postgres_16() -> None:
    assert "PostgreSQL 16" in check_database()


def test_pg_trgm_extension_is_installed() -> None:
    """Installed by migration 0001; the fuzzy-search design depends on it."""
    with get_engine().connect() as connection:
        version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm'")
        ).scalar_one()
    assert version


def test_database_is_migrated_to_the_code_head() -> None:
    """The applied revision must equal the head the code declares.

    Comparing against the script directory rather than a hardcoded revision id
    means this keeps working after S1.1 adds migrations, and still fails if the
    database is left behind.
    """
    heads = set(ScriptDirectory.from_config(Config(str(REPO_ROOT / "alembic.ini"))).get_heads())
    with get_engine().connect() as connection:
        applied = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    assert applied == heads


def test_session_scope_commits_on_a_clean_exit() -> None:
    events: list[str] = []
    with session_scope() as session:
        session.execute(text("SELECT 1"))
        event.listen(session, "after_commit", lambda _session: events.append("commit"))
    assert events == ["commit"]


def test_session_scope_rolls_back_and_reraises() -> None:
    """Both the CREATE and the INSERT go inside the transaction that must roll back.

    The temporary table is the proof: if the rollback silently did nothing, the
    table would still exist afterwards.
    """
    with pytest.raises(RuntimeError, match="deliberate"), session_scope() as session:
        session.execute(text("CREATE TEMPORARY TABLE s02_rollback_probe (id integer)"))
        session.execute(text("INSERT INTO s02_rollback_probe (id) VALUES (1)"))
        raise RuntimeError("deliberate failure")

    with get_engine().connect() as connection:
        still_there = connection.execute(
            text("SELECT to_regclass('s02_rollback_probe')")
        ).scalar_one()
    assert still_there is None


def test_a_terminated_connection_is_replaced_transparently() -> None:
    """End-to-end proof of `pool_pre_ping`.

    A pooled connection is returned to the pool, its backend is then killed, and
    the next checkout must still succeed. Without pre-ping the pool would hand
    back the dead connection and raise. The killer uses its own pool-less engine
    so the connection under test is not terminated out from under the killer
    itself, and the pid is passed as a bound parameter -- never interpolated into
    the SQL string.
    """
    engine = get_engine()

    with engine.connect() as connection:
        backend_pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
    # Returned to the pool, still alive, now addressable by pid.

    killer = create_engine(get_settings().dsn, poolclass=NullPool)
    try:
        with killer.connect() as connection:
            connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": backend_pid})
    finally:
        killer.dispose()

    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1

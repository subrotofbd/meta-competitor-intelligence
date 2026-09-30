"""Alembic configuration and migration history.

No database connection: these tests read `alembic.ini` and the migration files on
disk. That is enough to catch the mistakes that actually happen here -- a lost
downgrade, a branching history, a second copy of a database URL, or a table that
should not exist yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.unit

MIGRATIONS_DIR = REPO_ROOT / "database" / "migrations"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))


def test_alembic_ini_exists_and_points_at_the_migration_directory() -> None:
    assert ALEMBIC_INI.is_file()
    assert (MIGRATIONS_DIR / "env.py").is_file()

    configured = Config(str(ALEMBIC_INI)).get_main_option("script_location")
    assert configured is not None
    assert Path(configured) == Path("database/migrations")
    assert (REPO_ROOT / configured).is_dir()


def test_history_has_exactly_one_head() -> None:
    """Two heads means two independent lineages that no single upgrade reaches."""
    assert len(_script_directory().get_heads()) == 1


def test_s02_contains_exactly_one_revision() -> None:
    revisions = [revision.revision for revision in _script_directory().walk_revisions()]
    assert revisions == ["0001_pg_trgm"]


def test_every_revision_is_reversible() -> None:
    """Reversibility is a project requirement, so it is asserted for every revision.

    The downgrade bodies are not executed here: running them issues DROP
    statements, which needs explicit human approval.
    """
    for revision in _script_directory().walk_revisions():
        assert callable(revision.module.upgrade), f"{revision.revision} has no upgrade()"
        assert callable(revision.module.downgrade), f"{revision.revision} has no downgrade()"


def test_first_revision_enables_pg_trgm_and_creates_no_tables() -> None:
    """S0.2 must not invent domain tables ahead of the schema checkpoint."""
    source = (MIGRATIONS_DIR / "versions" / "0001_pg_trgm.py").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm" in source
    assert "create_table" not in source


def test_alembic_ini_holds_no_database_url() -> None:
    """The DSN lives in Settings alone; a URL here is a second copy of a password."""
    ini = ALEMBIC_INI.read_text(encoding="utf-8")
    assert "sqlalchemy.url" not in ini
    assert "postgresql" not in ini


def test_no_migration_file_hardcodes_a_dsn() -> None:
    offenders = [
        path.name
        for path in MIGRATIONS_DIR.rglob("*.py")
        if "postgresql" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_env_py_does_not_replace_the_structured_log_handler() -> None:
    """`logging.config.fileConfig` would swap Alembic's console formatter in, so
    a migration would log in a different shape from every other process.

    Asserted on the import and the call, not the word: the module's docstring
    explains the decision and must keep naming the function it avoids.
    """
    env_source = (MIGRATIONS_DIR / "env.py").read_text(encoding="utf-8")
    assert "from logging.config import" not in env_source
    assert "fileConfig(" not in env_source
    assert "configure_logging" in env_source

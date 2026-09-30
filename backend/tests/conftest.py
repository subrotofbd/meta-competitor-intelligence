"""Shared fixtures for the S0.2 test suite.

Two rules the whole suite depends on:

* **Unit tests are hermetic.** They never read the developer's real `.env`
  (every construction passes `_env_file=None`) and never open a connection.
* **Tests that need PostgreSQL are marked `integration`** and run against the
  local compose container. They are not skipped when it is down -- a silent skip
  is indistinguishable from a pass, and this project does not report unverified
  work as green.

    uv run pytest                       # everything; requires the container
    uv run pytest -m "not integration"  # no Docker required
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings
from app.db.session import dispose_engine

# A syntactically valid psycopg 3 URL for settings that are never connected with.
# Placeholder credentials on purpose -- unit tests must not need a real password.
FAKE_DSN = "postgresql+psycopg://user:password@localhost:5432/brandset"

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every variable Settings reads, so a test starts from a known-empty environment
# instead of inheriting whatever the developer's shell happens to export.
_SETTINGS_ENV_VARS = (
    "APP_ENV",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "DATABASE_URL",
    "DATABASE_ECHO",
)


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    """Drop the memoised engine and settings after every test.

    Both are process-wide singletons. Without this, one test's DSN leaks into
    the next and results depend on execution order.
    """
    yield
    dispose_engine()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_root_logger() -> Iterator[None]:
    """Restore the root logger after any test that reconfigures it.

    `configure_logging` replaces root handlers, which would otherwise leak into
    every later test and make their captured output depend on ordering.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    try:
        yield
    finally:
        for handler in list(root.handlers):
            if handler not in saved_handlers:
                root.removeHandler(handler)
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def _set_settings_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    """Put the process environment into a known state, then apply `env`."""
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", FAKE_DSN)
    for name, value in env.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def make_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Build `Settings` from an explicit environment, ignoring the real `.env`.

    Keyword arguments are environment-variable names and values, so tests read
    the same way the deployed process is configured.
    """

    def _make(**env: str) -> Settings:
        _set_settings_env(monkeypatch, **env)
        return Settings(_env_file=None)

    return _make


@pytest.fixture
def use_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Reconfigure the process-wide singletons from an explicit environment.

    Needed by anything that goes through `get_settings()` rather than building
    `Settings` directly, such as the engine in `app.db.session`.
    """

    def _use(**env: str) -> None:
        _set_settings_env(monkeypatch, **env)
        get_settings.cache_clear()
        dispose_engine()

    _use()
    return _use

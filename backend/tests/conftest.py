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

import json
import logging
import socket
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.composition import build_ad_provider, build_ai_provider
from app.core.config import Settings, get_settings
from app.db.session import dispose_engine
from app.providers.ai.base import AIProvider
from app.providers.ai.models import CopyAnalysis
from app.providers.data.base import AdDataProvider
from app.providers.data.mock import MockBatch, MockPage
from app.providers.data.models import PageRef

# A syntactically valid psycopg 3 URL for settings that are never connected with.
# Placeholder credentials on purpose -- unit tests must not need a real password.
FAKE_DSN = "postgresql+psycopg://user:password@localhost:5432/brandset"

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

#: The instant every deterministic test pretends it is running at.
FIXED_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

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


# ============================================================
# S0.3 -- provider corpus, stored analyses, and the offline guard
# ============================================================


def _read_fixture(*parts: str) -> Any:
    path = FIXTURES_DIR.joinpath(*parts)
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    """A clock that never moves, so a whole `ProviderResult` can be compared."""
    return lambda: FIXED_NOW


@pytest.fixture
def mock_pages() -> dict[str, MockPage]:
    """The sanitized ad corpus, keyed by provider page id.

    Loaded into a fixture rather than read by the provider, so `MockProvider`
    itself performs no file I/O and can be used identically from a script.
    """
    pages: dict[str, MockPage] = {}
    for entry in _read_fixture("ad_provider", "corpus.json")["pages"]:
        reference = PageRef(**entry["page"])
        pages[reference.provider_page_id] = MockPage(
            page=reference,
            batches=tuple(
                MockBatch(raw=batch["raw"], next_cursor=batch["next_cursor"])
                for batch in entry["batches"]
            ),
        )
    return pages


@pytest.fixture
def mock_analyses() -> dict[str, CopyAnalysis]:
    """Stored `CopyAnalysis` values, keyed by `copy_hash`."""
    return {
        key: CopyAnalysis(**value)
        for key, value in _read_fixture("ai", "analyses.json")["responses"].items()
    }


@pytest.fixture
def ad_provider(
    mock_pages: dict[str, MockPage], fixed_clock: Callable[[], datetime]
) -> AdDataProvider:
    """The ad provider, built the way the application builds it.

    Goes through `app.composition` on purpose. It is the only module allowed to
    name a concrete provider, so a test that built its provider any other way
    would not be testing the wiring we actually ship.
    """
    return build_ad_provider(mock_pages, clock=fixed_clock)


@pytest.fixture
def ai_provider(mock_analyses: dict[str, CopyAnalysis]) -> AIProvider:
    """The copy-analysis provider, built the way the application builds it."""
    return build_ai_provider(mock_analyses)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any attempt to open a socket fail loudly.

    Opt-in, not autouse: the `integration` tests genuinely open a connection to
    the local PostgreSQL container, and a guard that blocked them would be a
    guard nobody could trust. The mock suites request this explicitly, so
    "the provider made no network call" is a tested fact rather than an
    assumption about what the provider does.
    """

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("S0.3 tests must not touch the network")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)

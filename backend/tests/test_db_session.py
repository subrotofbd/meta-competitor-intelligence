"""Engine and session construction.

None of these tests open a connection. SQLAlchemy connects lazily, so engine and
session construction is fully exercisable offline, which keeps the unit suite
runnable with no Docker at all. Transaction behaviour that genuinely needs a live
database lives in `test_db_integration.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.session import (
    dispose_engine,
    get_engine,
    get_session,
    get_session_factory,
    session_scope,
)

pytestmark = pytest.mark.unit


def test_engine_uses_the_psycopg3_driver(use_settings: Callable[..., None]) -> None:
    use_settings(DATABASE_URL="postgresql+psycopg://user:pw@localhost:5432/db")
    assert get_engine().url.drivername == "postgresql+psycopg"


def test_engine_repr_masks_the_password(use_settings: Callable[..., None]) -> None:
    use_settings(DATABASE_URL="postgresql+psycopg://user:hunter2@localhost:5432/db")
    assert "hunter2" not in repr(get_engine().url)


def test_engine_honours_the_echo_setting(use_settings: Callable[..., None]) -> None:
    use_settings(DATABASE_ECHO="true")
    assert get_engine().echo is True


def test_pool_pre_ping_is_enabled(use_settings: Callable[..., None]) -> None:
    """`pool_pre_ping` is what makes a container restart cost one reconnect instead
    of a failed request. SQLAlchemy exposes no public accessor for the flag, so
    this reads the pool directly to stop it being dropped by accident. The live
    behaviour is covered in `test_db_integration.py`.
    """
    use_settings()
    assert get_engine().pool._pre_ping is True


def test_engine_is_memoised(use_settings: Callable[..., None]) -> None:
    """One engine per process: engines own a connection pool."""
    assert get_engine() is get_engine()


def test_dispose_engine_forces_a_rebuild(use_settings: Callable[..., None]) -> None:
    first = get_engine()
    dispose_engine()
    second = get_engine()

    assert second is not first
    assert isinstance(second, Engine)


def test_session_factory_yields_a_session_bound_to_the_engine(
    use_settings: Callable[..., None],
) -> None:
    session = get_session_factory()()
    try:
        assert isinstance(session, Session)
        assert session.get_bind() is get_engine()
    finally:
        session.close()


def test_session_factory_follows_a_disposed_engine(
    use_settings: Callable[..., None],
) -> None:
    """The factory is rebuilt per call precisely so it cannot outlive its engine."""
    before = get_session_factory()()
    dispose_engine()
    after = get_session_factory()()
    try:
        assert after.get_bind() is not before.get_bind()
    finally:
        before.close()
        after.close()


def test_session_scope_closes_the_session_on_success(
    use_settings: Callable[..., None],
) -> None:
    with session_scope() as session:
        assert isinstance(session, Session)
    assert not session.in_transaction()


def test_session_scope_closes_the_session_on_failure(
    use_settings: Callable[..., None],
) -> None:
    with pytest.raises(RuntimeError, match="deliberate"), session_scope() as session:
        raise RuntimeError("deliberate failure")
    assert not session.in_transaction()


def test_get_session_is_a_generator_dependency(
    use_settings: Callable[..., None],
) -> None:
    """FastAPI drives a generator dependency per request and closes it on exit."""
    dependency: Iterator[Session] = get_session()
    session = next(dependency)
    assert isinstance(session, Session)

    with pytest.raises(StopIteration):
        next(dependency)

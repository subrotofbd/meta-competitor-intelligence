"""Engine, session factory, and the session lifecycle.

One process-wide engine, built on first use. Engines own a connection pool, so
creating one per request or per worker iteration would be both slow and wrong.

The two ways to obtain a session are deliberately different:

* `session_scope` -- a context manager for the worker, scripts and tests, which
  are not inside a request.
* `get_session`  -- a generator dependency for FastAPI, which is.

`get_session` delegates to `session_scope` rather than reimplementing the
transaction rules, so there is one definition of "what happens when the body
raises".
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    """The process-wide engine, created on first use.

    Connecting is deferred to first checkout, so importing this module -- and
    therefore the whole app -- never requires a reachable database.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.dsn,
            echo=settings.database_echo,
            # Probe a pooled connection before handing it out. A connection the
            # server or the container dropped while idle then costs one
            # reconnect instead of surfacing as a failed request.
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """A session factory bound to the current engine.

    Rebuilt from `get_engine()` on every call instead of being memoised
    alongside it. Building one is trivial, and it removes the possibility of a
    factory surviving a `dispose_engine()` and silently pointing at a dead pool.
    """
    return sessionmaker(
        bind=get_engine(),
        class_=Session,
        # Keep attributes usable after commit. Without this, reading a
        # flushed-and-committed instance later raises DetachedInstanceError in
        # exactly the response-serialisation path that follows a commit.
        expire_on_commit=False,
    )


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transactional scope: commit on success, roll back on error, always close."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding one session per request."""
    with session_scope() as session:
        yield session


def dispose_engine() -> None:
    """Close pooled connections and forget the engine, so the next call rebuilds it.

    Required whenever the configuration changes underneath a live process --
    tests switching DSNs, or a process that must reconnect to a restarted
    database.
    """
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def check_database() -> str:
    """Confirm the database answers, and return its server version.

    Raises `SQLAlchemyError` if the connection or the query fails. Returns only
    the version string: the DSN carries a password and must never be returned
    into a log line or an error path.
    """
    with get_engine().connect() as connection:
        return str(connection.execute(text("SELECT version()")).scalar_one())

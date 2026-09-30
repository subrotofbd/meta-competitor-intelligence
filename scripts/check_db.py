"""Confirm the database is reachable and migrated.

    uv run python scripts/check_db.py

Read-only by construction: it opens a connection and reads. It never migrates,
never resets, and never prints the DSN, which carries a password.

Exit code 0 means reachable, 1 means not. This is the "is the stack actually up"
command to run before `alembic upgrade head`.
"""

from __future__ import annotations

import logging
import sys
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.logging import configure_logging, run_id_context
from app.db.session import check_database

logger = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    configure_logging(settings)

    # A run id even though no collection is running: this proves the run_id
    # plumbing works end to end in a real process, not just in the tests.
    with run_id_context(str(uuid4())):
        logger.info("checking database", extra={"app_env": settings.app_env.value})
        try:
            version = check_database()
        except SQLAlchemyError as exc:
            # Exception type only, never the message and never exc_info: a
            # connection error can carry the DSN, and the DSN carries a
            # password. The traceback would reintroduce exactly what the
            # SecretStr in config exists to keep out of the logs.
            logger.error("database unreachable", extra={"error": type(exc).__name__})
            return 1
        logger.info("database reachable", extra={"server": version})
    return 0


if __name__ == "__main__":
    sys.exit(main())

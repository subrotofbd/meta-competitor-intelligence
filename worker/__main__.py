"""Worker entrypoint: `python -m worker`.

S0.1 -- placeholder. Exits cleanly without doing any work.

This is deliberately a no-op rather than a half-built consumer. Queue claiming,
typed-error handling, and the capped exponential backoff with jitter are S0.2
work and must not be guessed at here.
"""

import logging
import sys

logger = logging.getLogger("worker")


def main() -> int:
    """Report that the worker is not implemented yet, then exit cleanly."""
    logger.info("worker entrypoint reached (checkpoint S0.1 placeholder)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

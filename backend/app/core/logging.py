"""Structured logging for the API and the future worker. Standard library only.

Every record is emitted as one JSON object, so a single collection run can be
followed end to end by `run_id` across both processes. `LOG_FORMAT=text` gives a
readable single line for a terminal.

`run_id` lives in a `ContextVar`, not a global, so a run id is bound to the
current thread or asyncio task. Sibling tasks each get their own value instead
of inheriting whichever run started last.

No third-party logging framework: the stdlib covers this, and a dependency added
here would be paid for by every process in the project forever.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final, TextIO

from app.core.config import LogFormat, Settings

_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)

# Attributes `logging.LogRecord` sets on every record. Anything else found on a
# record was supplied by the caller through `extra=` and belongs in the payload.
# Listed explicitly rather than sniffed, so the split is auditable.
_RESERVED_ATTRS: Final = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# Keys that the text renderer already prints, so it does not repeat them.
_TEXT_CORE: Final = frozenset({"timestamp", "level", "logger", "message"})


@contextmanager
def run_id_context(run_id: str) -> Iterator[None]:
    """Bind `run_id` to every record logged inside the block, then unbind it.

    Unbinding is guaranteed even if the block raises, so a failed run cannot
    leave its id attached to unrelated later logs in the same task.
    """
    token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(token)


def get_run_id() -> str | None:
    """The `run_id` bound to the current context, or None."""
    return _run_id.get()


class _RunIdFilter(logging.Filter):
    """Copy the context's `run_id` onto the record for the formatter to read.

    Written to `__dict__` rather than `record.run_id = ...` because `run_id` is
    not a `LogRecord` attribute; assigning it normally is a type error, and the
    alternative is a `LogRecord` subclass plus a cast at every read.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.__dict__["run_id"] = _run_id.get()
        return True


class StructuredFormatter(logging.Formatter):
    """Render a record as a JSON object, or as one readable line.

    The payload is assembled once and then rendered, so the two output formats
    cannot drift apart in what they carry.
    """

    def __init__(self, *, as_json: bool) -> None:
        super().__init__()
        self._as_json = as_json

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        run_id = getattr(record, "run_id", None)
        if run_id is not None:
            payload["run_id"] = run_id

        # Caller-supplied `extra={"ad_id": ...}`. Reserved LogRecord internals
        # are skipped so the payload stays a clean, predictable shape.
        payload.update(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _RESERVED_ATTRS and key != "run_id"
            }
        )

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        if self._as_json:
            return json.dumps(payload, default=str, ensure_ascii=False)
        return self._as_text(payload)

    @staticmethod
    def _as_text(payload: dict[str, Any]) -> str:
        line = (
            f"{payload['timestamp']} {payload['level']:<8} {payload['logger']} {payload['message']}"
        )
        extras = {k: v for k, v in payload.items() if k not in _TEXT_CORE}
        if not extras:
            return line
        return f"{line} " + " ".join(f"{k}={v!r}" for k, v in extras.items())


def configure_logging(settings: Settings, *, stream: TextIO | None = None) -> None:
    """Install the structured handler on the root logger.

    Idempotent: existing root handlers are removed first, so a reload or a test
    calling this twice cannot double every subsequent line. Taking `Settings`
    rather than loose level/format arguments means a call site cannot
    accidentally pick the wrong one of the two.

    `stream` defaults to stdout, which is what a container wants. It is a
    parameter rather than a hardcoded lookup so tests can capture the real
    output instead of re-implementing the handler: test runners legitimately
    rebind the streams of existing StreamHandlers, which makes monkeypatching
    `sys.stdout` an unreliable place to intercept.
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(StructuredFormatter(as_json=settings.log_format is LogFormat.JSON))
    handler.addFilter(_RunIdFilter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)

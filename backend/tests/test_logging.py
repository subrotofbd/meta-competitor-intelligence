"""Structured logging: payload shape, `run_id` binding and unbinding, exception
capture, and idempotent configuration.

These tests drive the real `configure_logging` with the real formatter and filter.
The only substitution is the output stream, passed explicitly rather than by
monkeypatching `sys.stdout` -- test runners rebind the streams of existing
StreamHandlers, so patching `sys.stdout` is not a reliable interception point.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime

import pytest

from app.core.config import LogFormat, LogLevel, Settings
from app.core.logging import configure_logging, get_run_id, run_id_context

pytestmark = pytest.mark.unit


@dataclass
class Captured:
    """An in-memory log sink standing in for stdout."""

    stream: io.StringIO

    def lines(self) -> list[str]:
        return [line for line in self.stream.getvalue().splitlines() if line.strip()]

    def records(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.lines()]


@pytest.fixture
def captured() -> Iterator[Captured]:
    yield Captured(io.StringIO())


@pytest.fixture
def log_to(captured: Captured) -> Callable[[Settings], None]:
    """Configure real structured logging into the captured buffer."""

    def _log_to(settings: Settings) -> None:
        configure_logging(settings, stream=captured.stream)

    return _log_to


def test_json_record_carries_the_required_fields(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    log_to(make_settings())
    logging.getLogger("ads.collector").info("run started")

    (record,) = captured.records()
    assert record["message"] == "run started"
    assert record["level"] == "INFO"
    assert record["logger"] == "ads.collector"

    timestamp = datetime.fromisoformat(str(record["timestamp"]))
    assert timestamp.utcoffset() is not None, "timestamp must be timezone-aware"


def test_run_id_is_absent_when_no_run_is_bound(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    log_to(make_settings())
    logging.getLogger("test").info("no run")

    (record,) = captured.records()
    assert "run_id" not in record


def test_run_id_is_attached_inside_the_context_and_dropped_after(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    log_to(make_settings())
    with run_id_context("run-abc"):
        logging.getLogger("test").info("inside")
    logging.getLogger("test").info("outside")

    inside, outside = captured.records()
    assert inside["run_id"] == "run-abc"
    assert "run_id" not in outside
    assert get_run_id() is None


def test_run_id_is_unbound_even_when_the_block_raises(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    """A failed run must not leave its id attached to later, unrelated logs."""
    log_to(make_settings())
    with pytest.raises(RuntimeError), run_id_context("run-boom"):
        raise RuntimeError("boom")

    logging.getLogger("test").info("after the failure")
    assert get_run_id() is None
    assert "run_id" not in captured.records()[0]


def test_nested_contexts_restore_the_outer_run_id(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    log_to(make_settings())
    with run_id_context("outer"):
        with run_id_context("inner"):
            logging.getLogger("test").info("nested")
        assert get_run_id() == "outer"
        logging.getLogger("test").info("back to outer")
    assert get_run_id() is None

    nested, outer = captured.records()
    assert nested["run_id"] == "inner"
    assert outer["run_id"] == "outer"


def test_exception_information_is_captured(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    log_to(make_settings())
    try:
        raise ValueError("kaboom")
    except ValueError:
        logging.getLogger("test").exception("collection failed")

    (record,) = captured.records()
    assert "ValueError: kaboom" in str(record["exception"])


def test_caller_supplied_fields_are_included(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    log_to(make_settings())
    logging.getLogger("test").info("stored", extra={"ad_id": "abc", "rows": 3})

    (record,) = captured.records()
    assert record["ad_id"] == "abc"
    assert record["rows"] == 3
    # LogRecord internals must stay out of the payload, or its shape is not predictable.
    assert "pathname" not in record
    assert "created" not in record
    assert "exc_info" not in record


def test_percent_style_arguments_are_interpolated(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    log_to(make_settings())
    logging.getLogger("test").info("run %s took %dms", "abc", 12)

    (record,) = captured.records()
    assert record["message"] == "run abc took 12ms"


def test_non_ascii_copy_survives_json_rendering(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    """Hindi/Hinglish ad copy is first-class in this project from S1 onward."""
    log_to(make_settings())
    logging.getLogger("test").info("आज ही शुरू करें")

    (record,) = captured.records()
    assert record["message"] == "आज ही शुरू करें"


def test_configure_logging_is_idempotent(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    """A reload or a second call must not double every subsequent line."""
    settings = make_settings()
    log_to(settings)
    configure_logging(settings, stream=captured.stream)

    logging.getLogger("test").info("once")
    assert len(captured.records()) == 1
    assert len(logging.getLogger().handlers) == 1


def test_configured_level_suppresses_lower_records(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    log_to(make_settings(LOG_LEVEL=str(LogLevel.ERROR)))
    logging.getLogger("test").info("suppressed")

    assert captured.records() == []


def test_text_format_emits_a_single_readable_line(
    captured: Captured,
    log_to: Callable[[Settings], None],
    make_settings: Callable[..., Settings],
) -> None:
    log_to(make_settings(LOG_FORMAT=str(LogFormat.TEXT)))

    with run_id_context("run-text"):
        logging.getLogger("test").info("plain message", extra={"ad_id": "x"})

    (line,) = captured.lines()
    assert "INFO" in line
    assert "plain message" in line
    assert "run_id='run-text'" in line
    assert "ad_id='x'" in line

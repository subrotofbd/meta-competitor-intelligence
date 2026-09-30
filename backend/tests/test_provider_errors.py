"""Provider failure modes.

The important assertions are the negative ones. `Blocked` and `SchemaChanged`
must be unreachable by any retry policy, and `RateLimited` must carry enough
metadata for the orchestrator to wait the right amount of time rather than
guessing.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.providers.data import errors
from app.providers.data.errors import (
    Blocked,
    ProviderError,
    RateLimited,
    SchemaChanged,
    Transient,
)

ALL_ERRORS = (RateLimited, Blocked, SchemaChanged, Transient)


def test_the_four_modes_are_the_whole_vocabulary() -> None:
    """A fifth mode would need its own retry policy, not a silent fallthrough."""
    exported = {
        name
        for name, value in vars(errors).items()
        if isinstance(value, type) and issubclass(value, ProviderError)
    }
    assert exported == {
        "ProviderError",
        "RateLimited",
        "Blocked",
        "SchemaChanged",
        "Transient",
    }


@pytest.mark.parametrize("error", ALL_ERRORS)
def test_every_mode_is_a_provider_error(error: type[ProviderError]) -> None:
    assert issubclass(error, ProviderError)
    assert issubclass(error, Exception)


def test_the_base_error_is_not_retryable() -> None:
    """The default is refusal. An unknown failure must not become a retry."""
    assert ProviderError.retryable is False


@pytest.mark.parametrize("error", [Transient, RateLimited])
def test_transient_failures_are_retryable(error: type[ProviderError]) -> None:
    assert error.retryable is True


@pytest.mark.parametrize("error", [Blocked, SchemaChanged])
def test_terminal_failures_are_never_retryable(error: type[ProviderError]) -> None:
    """The whole point. A block is a decision, not an obstacle."""
    assert error.retryable is False


def test_a_block_carries_the_status_it_was_refused_with() -> None:
    error = Blocked(
        "ad library returned a challenge page",
        provider="mock",
        status_code=429,
        detail="consent wall",
    )
    assert error.retryable is False
    assert error.status_code == 429
    assert error.detail == "consent wall"
    assert error.provider == "mock"
    assert "challenge page" in str(error)


def test_a_block_without_a_status_is_still_terminal() -> None:
    """A refusal we cannot classify is a refusal, not a reason to try harder."""
    assert Blocked("refused", provider="mock").status_code is None


def test_a_rate_limit_exposes_its_stated_wait_in_seconds() -> None:
    error = RateLimited("slow down", provider="mock", retry_after=timedelta(seconds=90))
    assert error.retryable is True
    assert error.retry_after == timedelta(seconds=90)
    assert error.retry_after_seconds == 90.0


def test_a_rate_limit_without_a_stated_wait_says_so() -> None:
    """`None` means the orchestrator's own budget decides, not an immediate retry."""
    error = RateLimited("slow down", provider="mock")
    assert error.retry_after is None
    assert error.retry_after_seconds is None


def test_a_schema_change_names_both_the_expectation_and_the_reality() -> None:
    error = SchemaChanged(
        "ad_creative_bodies missing",
        provider="mock",
        expected="ad_creative_bodies: non-empty list",
        found="ad_creative_bodies=[]",
    )
    assert error.retryable is False
    assert error.expected == "ad_creative_bodies: non-empty list"
    assert error.found == "ad_creative_bodies=[]"


def test_a_transient_failure_keeps_the_provider_detail() -> None:
    error = Transient("connection reset", provider="mock", detail="server closed idle socket")
    assert error.retryable is True
    assert error.detail == "server closed idle socket"
    assert error.provider == "mock"


def _raise(error: type[ProviderError]) -> ProviderError:
    """Raise one of the four modes with the metadata its own signature demands."""
    if error is SchemaChanged:
        return error("boom", provider="mock", expected="a field", found="nothing")
    return error("boom", provider="mock")


@pytest.mark.parametrize("error", ALL_ERRORS)
def test_every_mode_names_the_provider_that_failed(error: type[ProviderError]) -> None:
    """A run can mix providers. An error that lost its source is undiagnosable."""
    raised = _raise(error)
    assert raised.provider == "mock"
    assert raised.message == "boom"


def test_no_provider_error_declares_a_retry_helper() -> None:
    """Backoff and jitter belong to the orchestrator, which sees the whole run.

    A provider that retried internally would hide its retries from the run
    record, and would make `Blocked` look like a slow call.
    """
    for error in ALL_ERRORS:
        members = {name for name in vars(error) if not name.startswith("_")}
        assert not {"retry", "backoff", "attempt", "sleep"} & members

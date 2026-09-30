"""How a provider says it failed.

Four failure modes, four types, and one class attribute the orchestrator reads:
`retryable`. Keeping the decision as a flag rather than an `isinstance` chain
means adding a fifth failure mode cannot silently fall through orchestration's
error handling as "unknown, ignore".

`retryable = False` means **stop the run and surface the error**. There is no
circumvention path. A blocked provider is reported, never worked around, never
retried harder, and never routed around (AGENTS.md section 5, section 9).

Nothing here retries. Backoff, jitter and retry budgets belong to the
orchestrator, which can see the run as a whole; a provider that silently
retried three times inside one call would hide that from the run record.
"""

from __future__ import annotations

from datetime import timedelta
from typing import ClassVar


class ProviderError(Exception):
    """Base class for every provider failure.

    Attributes:
        provider: The provider that failed, so a mixed run is diagnosable.
        message: What went wrong, in words safe to log.
    """

    retryable: ClassVar[bool] = False
    """Whether orchestration may try this call again. Default: no."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider


class RateLimited(ProviderError):
    """The provider asked us to slow down.

    Retryable, but not at the caller's convenience: the orchestrator waits for
    `retry_after` when the provider stated one, and falls back to its own
    backoff budget when it did not.

    Attributes:
        retry_after: The provider's stated wait, or `None` if it gave none.
        detail: Free-form provider wording, for the run log.
    """

    retryable: ClassVar[bool] = True

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        retry_after: timedelta | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.retry_after = retry_after
        self.detail = detail

    @property
    def retry_after_seconds(self) -> float | None:
        """The stated wait in seconds, for a caller that works in floats.

        `None` means the provider named no deadline, so the retry budget -- not
        the provider -- decides when to try again.
        """
        return None if self.retry_after is None else self.retry_after.total_seconds()


class Blocked(ProviderError):
    """Access was refused: a challenge, a blocklist, a consent wall.

    Terminal by policy, not by capability. Retrying, rotating egress or
    changing how we present the request are all prohibited; the correct
    response is to stop the run and tell the operator (AGENTS.md section 5).

    Attributes:
        status_code: The HTTP status the provider adapter saw, when there was one.
        detail: Free-form provider wording, for the run log.
    """

    retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.status_code = status_code
        self.detail = detail


class SchemaChanged(ProviderError):
    """The provider's response no longer matches the shape we parse.

    Terminal, and a loud one. Parsing an unrecognised payload into plausible
    fields is how invented data gets stored as observed data, so the run stops
    and a human decides what changed.

    Attributes:
        expected: The field or shape the adapter expected.
        found: What it actually received.
    """

    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, provider: str, expected: str, found: str) -> None:
        super().__init__(message, provider=provider)
        self.expected = expected
        self.found = found


class Transient(ProviderError):
    """A failure that is very likely to disappear on its own.

    A dropped connection, a 5xx, a timeout. Retryable with the orchestrator's
    capped exponential backoff and jitter.

    Attributes:
        detail: Free-form provider wording, for the run log.
    """

    retryable: ClassVar[bool] = True

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.detail = detail

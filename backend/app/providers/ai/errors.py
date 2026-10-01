"""How an AI provider says it failed.

The same philosophy as `app.providers.data.errors`, applied to models: a fixed
vocabulary of failure types carrying one class attribute, `retryable`, so the
handler decides what to do by reading a flag rather than by matching an error
string. Adding a fifth failure mode must not be able to fall through as "unknown,
ignore" -- which is exactly what happens when behaviour keys off message text.

`retryable = False` means **stop and surface it**. A blocked or refusing model is
reported, never retried harder and never routed around, for the same reason
`AGENTS.md` section 5 applies to a blocked ad provider.

## What is NOT here

**No retry, and no backoff.** A model that quietly re-called itself three times
inside one `analyze_copy` would hide that from `ai_jobs`, and `ai_jobs` is the
only record of what the product actually spent. Retries are the handler's, one
corrective retry, and the outer `jobs` mechanism's after that.
"""

from __future__ import annotations

from typing import ClassVar


class AIError(Exception):
    """Base class for every AI provider failure.

    Attributes:
        provider: The provider that failed, so a mixed run is diagnosable.
        message: What went wrong, in words safe to log.
    """

    retryable: ClassVar[bool] = False
    """Whether the handler may try this call again. Default: no."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider


class RateLimited(AIError):
    """The provider asked us to slow down.

    Retryable. The handler does not treat it as a validation failure: no
    corrective prompt helps, because the model never read the first one.
    """

    retryable: ClassVar[bool] = True


class Blocked(AIError):
    """Access refused, or the key was rejected.

    Terminal by design. A blocked model is reported and the run stops calling it.
    Retrying a refusal harder is the behaviour `AGENTS.md` section 5 forbids for
    every other provider, and an API key problem is an operator's to fix, not
    something to hammer.
    """

    retryable: ClassVar[bool] = False


class InvalidResponse(AIError):
    """The model answered, and the answer cannot be stored.

    Raised by the adapter when the payload is not JSON, or is JSON this schema
    cannot hold, **after** the single corrective retry has already been spent.
    Terminal for this call: a second guess is not permitted, because the handler
    has exactly one retry and a fabricated analysis is never the alternative
    (`AGENTS.md` section 10).

    Not retryable. The outer `jobs` mechanism may re-run the whole job later, and
    that is a decision made with the run in view rather than from inside one
    call.

    Attributes:
        detail: Free-form wording about what was wrong, for the job log.
    """

    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, provider: str, detail: str | None = None) -> None:
        super().__init__(message, provider=provider)
        self.detail = detail


class Transient(AIError):
    """A failure likely to resolve itself: a timeout, a dropped connection.

    Retryable. Distinct from `InvalidResponse` because the model may well answer
    correctly next time, and from `RateLimited` because no wait was requested.
    """

    retryable: ClassVar[bool] = True


class ResponseTooLarge(AIError):
    """The model's answer was refused before it was parsed.

    Checked against `ai_max_response_chars` *before* any JSON parsing, so a
    pathological answer costs a length comparison rather than a parse of
    whatever the model chose to emit. Not retryable: the same prompt produced
    the same overlong answer, and asking again spends money to learn nothing.

    Attributes:
        size_chars: How long the refused answer was, which is the useful part of
            the diagnosis. Never the answer itself.
    """

    retryable: ClassVar[bool] = False

    def __init__(self, message: str, *, provider: str, size_chars: int) -> None:
        super().__init__(message, provider=provider)
        self.size_chars = size_chars

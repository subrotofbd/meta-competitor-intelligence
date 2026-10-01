"""The `AIProvider` contract.

One method, one result type, no vendor. Business logic asks for an analysis of
some copy; which model produced it, at what cost, is not its concern -- and is
not allowed to become its concern, because the moment a service branches on
vendor the swap stops being a one-file change.

The contract is deliberately small:

* **No SDK, no client, no credentials here.** Those belong in a concrete
  adapter, configured from settings. No AI SDK is installed (AGENTS.md
  section 12), so `MockAIProvider` is the only implementation in S3.1.
* **No partial results.** An adapter that gets unparseable output retries once
  and then raises `InvalidResponse`. Returning half an analysis would be
  indistinguishable from "the copy did not say that".
* **No performance claims.** The schema has nowhere to put them, and the
  prompt is written to forbid them (AGENTS.md section 10).
* **Usage and cost are reported, never computed here.** The provider says what
  it was told; the handler decides what may be stored and how it is labelled.

## Why the return type is a wrapper

S3.1 must track tokens and cost per call (`AGENTS.md` section 10). A bare
`CopyAnalysis` return had nowhere to put a token count, a model name, or a
provider name, so the earlier contract could not satisfy a requirement the same
document set. `AIResult` carries the analysis beside `AIUsage`; both are
nullable where the provider reported nothing.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.providers.ai.errors import (
    AIError,
    Blocked,
    InvalidResponse,
    RateLimited,
    ResponseTooLarge,
    Transient,
)
from app.providers.ai.models import AIResult, CopyAnalysisRequest


@runtime_checkable
class AIProvider(Protocol):
    """A source of copy interpretations."""

    name: str
    """Stable identifier recorded with every analysis, so a stored result can
    always be traced to the model and version that produced it."""

    def analyze_copy(self, request: CopyAnalysisRequest) -> AIResult:
        """Interpret one ad's copy.

        Args:
            request: The ad's copy, its `copy_hash` and the analysis version.

        Returns:
            The analysis and what is known about the call. Fields the copy did not
            support are `None`; an unsupported value must never be filled with a
            generated sentence. `usage` is `None` when the provider reported none.

        Raises:
            RateLimited: The provider asked us to slow down.
            Blocked: Access refused, or the key was rejected. Terminal.
            InvalidResponse: The answer is not JSON, or is JSON this schema
                cannot hold, after the single permitted retry.
            ResponseTooLarge: The answer was refused before it was parsed.
            Transient: A failure likely to resolve itself.
        """
        ...


__all__ = [
    "AIError",
    "AIProvider",
    "AIResult",
    "Blocked",
    "CopyAnalysisRequest",
    "InvalidResponse",
    "RateLimited",
    "ResponseTooLarge",
    "Transient",
]

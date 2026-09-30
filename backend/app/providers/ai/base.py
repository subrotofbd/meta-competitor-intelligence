"""The `AIProvider` contract.

One method, one schema, no vendor. Business logic asks for an analysis of some
copy; which model produced it, at what temperature, at what cost, is not its
concern -- and is not allowed to become its concern, because the moment a
service branches on vendor the swap stops being a one-file change.

The contract is deliberately small:

* **No SDK, no client, no credentials here.** Those belong in a concrete
  adapter, configured from settings.
* **No partial results.** An adapter that gets unparseable output retries once
  and then fails loudly. Returning half an analysis would be indistinguishable
  from "the copy did not say that".
* **No performance claims.** The schema has nowhere to put them, and the
  prompt is written to forbid them (AGENTS.md section 10).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.providers.ai.models import CopyAnalysis, CopyAnalysisRequest


@runtime_checkable
class AIProvider(Protocol):
    """A source of copy interpretations."""

    name: str
    """Stable identifier recorded with every analysis, so a stored result can
    always be traced to the model and version that produced it."""

    def analyze_copy(self, request: CopyAnalysisRequest) -> CopyAnalysis:
        """Interpret one ad's copy.

        Args:
            request: The ad's copy, its `copy_hash` and the analysis version.

        Returns:
            The analysis. Fields the copy did not support are `None`; an
            unsupported value must never be filled with a generated sentence.

        Raises:
            ValueError: The model returned something this schema cannot hold,
                after the single permitted retry.
            RuntimeError: The model was unreachable or refused. Transient
                upstream failures are the orchestrator's to retry, not the
                provider's.
        """
        ...

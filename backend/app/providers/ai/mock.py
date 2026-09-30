"""An offline `AIProvider` that returns stored analyses.

Same standing as `MockAdProvider`: a real implementation of the protocol,
registered through the same composition root, not a test double. It is how the
analysis pipeline is built and demonstrated before any model is configured, and
no SDK is installed to run it.

Responses are keyed by `copy_hash` -- the same key results are deduplicated on
in storage -- and injected at construction, so this module reads no file and
opens no socket.

## Unknown copy returns an empty analysis

That is a deliberate choice, not a fallback. A `copy_hash` with no stored
analysis is copy nobody has read, and the honest analysis of copy nobody has
read is fourteen nulls. Returning something plausible would be the exact
failure the schema exists to prevent: a generated sentence that reads like an
observation and gets badged `AI_INTERPRETATION`.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.providers.ai.models import CopyAnalysis, CopyAnalysisRequest

#: Returned for a `copy_hash` with no stored analysis. Every field `None`,
#: which is a valid `CopyAnalysis` and renders as fourteen em dashes.
_NO_ANALYSIS: CopyAnalysis = CopyAnalysis()


class MockAIProvider:
    """An `AIProvider` that looks up a stored analysis by `copy_hash`.

    Attributes:
        name: Recorded with every analysis, so a stored result can be traced to
            the model that produced it.
    """

    name = "mock-ai"

    def __init__(self, responses: Mapping[str, CopyAnalysis] | None = None) -> None:
        self._responses = dict(responses or {})

    def analyze_copy(self, request: CopyAnalysisRequest) -> CopyAnalysis:
        """Return the stored analysis for `request.copy_hash`, or the empty one.

        Deterministic by construction: the same request always returns an equal
        result, and no clock, network or random state is consulted.
        """
        return self._responses.get(request.copy_hash, _NO_ANALYSIS)

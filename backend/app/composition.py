"""The composition root: the one place concrete providers are named.

Everything else receives a provider as an argument. No service, schema or
route imports `app.providers.data.mock` or `app.providers.ai.mock`, so a
provider can be replaced by editing this file and nothing else
(AGENTS.md section 9).

Each builder is annotated as returning the *protocol*, not the class. That is
not a stylistic choice: it is what makes it impossible for a caller to reach
through the returned object to the concrete type, and it means a caller cannot
even write `result.fetch_fixture()` by accident.

The mocks are built here exactly as a real provider would be, because they are
providers. A future real provider becomes one more builder beside these, and
the choice between them becomes configuration rather than a code change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from app.providers.ai.base import AIProvider
from app.providers.ai.mock import MockAIProvider
from app.providers.ai.models import CopyAnalysis
from app.providers.data.base import AdDataProvider
from app.providers.data.mock import MockPage, MockProvider


def build_ad_provider(
    pages: Mapping[str, MockPage],
    *,
    clock: Callable[[], datetime] | None = None,
) -> AdDataProvider:
    """Build the ad provider for this process.

    Args:
        pages: The corpus the mock serves, keyed by provider page id.
        clock: Time source. Injected so a run's records can be deterministic;
            production wiring passes the real clock.

    Returns:
        An `AdDataProvider`. With no real provider implemented yet this is
        always the mock, and that is stated here rather than implied.
    """
    return MockProvider(pages, clock=clock)


def build_ai_provider(responses: Mapping[str, CopyAnalysis]) -> AIProvider:
    """Build the copy-analysis provider for this process.

    Args:
        responses: Stored analyses keyed by `copy_hash`.

    Returns:
        An `AIProvider`. Always the mock in S0.3; no model is configured and no
        SDK is installed.
    """
    return MockAIProvider(responses)

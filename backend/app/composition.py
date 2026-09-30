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
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.providers.ai.base import AIProvider
from app.providers.ai.mock import MockAIProvider
from app.providers.ai.models import CopyAnalysis
from app.providers.data.base import AdDataProvider
from app.providers.data.mock import MockPage, MockProvider
from app.services.collection import CollectionOrchestrator
from app.services.jobs import JobQueue, PostgresJobQueue


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


def build_job_queue(
    *,
    lease_duration: timedelta | None = None,
    max_attempts: int | None = None,
) -> JobQueue:
    """Build the job queue for this process.

    Args:
        lease_duration: How long a worker holds a lease before it expires.
            Defaults to 5 minutes.
        max_attempts: Maximum number of attempts before a job is marked DEAD.
            Defaults to 5.

    Returns:
        A `JobQueue` implementation. In S1.2 this is always `PostgresJobQueue`.
    """
    from app.services.jobs import DEFAULT_LEASE_DURATION, MAX_ATTEMPTS

    return PostgresJobQueue(
        get_session_factory(),
        lease_duration=lease_duration or DEFAULT_LEASE_DURATION,
        max_attempts=max_attempts or MAX_ATTEMPTS,
    )


def build_mock_pages() -> Mapping[str, MockPage]:
    """Load the mock page corpus from the test fixtures.

    This is the same corpus used by tests, exposed here so the worker can
    run against deterministic mock data without importing test modules.
    """
    import json
    from pathlib import Path

    from app.providers.data.mock import MockPage
    from app.providers.data.models import PageRef

    fixtures_path = (
        Path(__file__).resolve().parents[2]
        / "backend"
        / "tests"
        / "fixtures"
        / "ad_provider"
        / "corpus.json"
    )
    data = json.loads(fixtures_path.read_text(encoding="utf-8"))

    pages: dict[str, MockPage] = {}
    for entry in data["pages"]:
        reference = PageRef(**entry["page"])
        pages[reference.provider_page_id] = MockPage(
            page=reference,
            batches=entry["batches"],
        )
    return pages


def build_collection_orchestrator(
    *,
    lease_duration: timedelta | None = None,
    max_attempts: int | None = None,
) -> tuple[CollectionOrchestrator, Session]:
    """Build a collection orchestrator with all its dependencies.

    The two collection safety settings come from `Settings`, so each is one
    value in one place and overridable per environment, rather than a constant
    buried in a service.

    Returns the orchestrator AND the session it uses. The caller is responsible
    for closing the session.

    This is a convenience for the worker entrypoint and API routes.
    """
    from app.services.collection import build_collection_orchestrator as _build

    session_factory = get_session_factory()
    session = session_factory()

    provider = build_ad_provider(build_mock_pages())
    job_queue = build_job_queue(lease_duration=lease_duration, max_attempts=max_attempts)

    settings = get_settings()
    orchestrator = _build(
        session,
        provider,
        job_queue,
        max_records=settings.collection_max_records_per_run,
        stale_run_timeout=settings.collection_stale_run_timeout,
    )
    return orchestrator, session

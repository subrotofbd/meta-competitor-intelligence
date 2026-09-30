"""A real, offline ad provider.

`MockProvider` is not test scaffolding. It is registered and built through the
same composition root as any other provider, satisfies the same protocol, and
returns the same types -- which is what lets the whole product be developed and
demonstrated without touching Meta, a paid feed, or a network at all.

It is deterministic. With a fixed clock, the same `(page, cursor)` returns an
equal `ProviderResult` every time, so a test can assert on a whole result
rather than on fragments of one.

## What it actually does

The corpus is injected at construction and served verbatim. This provider
returns provider data and nothing else: it does not read the payload, does not
decide what a record means, and does not judge whether one is well formed.
`app.providers.data.normalize` does the reading, and the orchestrator calls it
*after* the raw response is stored, so a malformed record can be reported
without the evidence for that report being thrown away first.

## What it refuses to do

No network, no filesystem, no database, no clock of its own beyond the one
injected -- and no judgement. It raises nothing. `Blocked`, `SchemaChanged` and
the rest are the vocabulary of a provider that can be *reached and understood*;
this one is served from memory, so its only failure modes are being handed a
cursor it does not recognise, which ends a walk rather than breaking it.

It also refuses to shorten a page. A caller that ignores the errors it gets from
`normalize_payload` and reads `raw` directly will get a page that is quietly
short -- the same reason the provider's all-or-nothing policy used to exist, and
the reason `CollectionOutcome` carries the status alongside the records.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from app.providers.data.models import (
    CanaryResult,
    CostEstimate,
    PageRef,
    ProviderCapabilities,
    ProviderResult,
    RawPayload,
    RequestMeta,
)
from app.providers.data.provenance import DataOrigin

MOCK_CAPABILITIES: Final = ProviderCapabilities(
    countries=("IN", "GB", "US"),
    categories=(),
    # Honest: the corpus has no history. History is what our own snapshots
    # create, and no provider will hand it to us for commercial ads.
    has_history=False,
    serves_commercial_ads=True,
)

MOCK_COST: Final = CostEstimate(
    amount=Decimal("0"),
    currency="USD",
    method="the mock provider issues no billable request",
)


@dataclass(frozen=True, slots=True)
class MockBatch:
    """One page of a provider response: the payload, and where to go next.

    Attributes:
        raw: The unparsed response. Persisted verbatim, exactly as a real
            provider's would be.
        next_cursor: Cursor for the following batch, or `None` to end.
    """

    raw: RawPayload
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class MockPage:
    """One trackable page and every batch the provider will serve for it.

    Attributes:
        page: The page's identity, in the provider's own terms.
        batches: Ordered pages of results. The last one has no `next_cursor`.
    """

    page: PageRef
    batches: tuple[MockBatch, ...]


class MockProvider:
    """An `AdDataProvider` served entirely from an injected corpus.

    The corpus is a constructor argument, not a file this module reads. That
    keeps the provider free of I/O of every kind and leaves the fixtures where
    they belong -- in the test suite, committed and sanitised.
    """

    name: str = "mock"
    origin: DataOrigin = DataOrigin.third_party

    def __init__(
        self,
        pages: Mapping[str, MockPage] | None = None,
        *,
        capabilities: ProviderCapabilities = MOCK_CAPABILITIES,
        cost_estimate: CostEstimate = MOCK_COST,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._pages = dict(pages or {})
        self._capabilities = capabilities
        self._cost_estimate = cost_estimate
        self._clock = clock or (lambda: datetime.now(UTC))

    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def fetch_page_ads(
        self,
        page: PageRef,
        country: str,
        *,
        cursor: str | None = None,
    ) -> ProviderResult:
        """Serve one batch for `page`, starting at `cursor`.

        Provider data and nothing else. The payload is returned exactly as the
        corpus holds it, including records that no reader could make sense of:
        a parser's opinion about one record must not be able to cost us the whole
        response, and this provider is the one place where that opinion used to
        live. Reading is the orchestrator's job, after the raw has been stored.

        A page the corpus does not hold yields an empty result rather than an
        error: a provider that does not track a page really does have no ads for
        it, and raising would turn an ordinary "nothing to report" into a run
        failure.
        """
        requested_at = self._clock()
        fixture = self._pages.get(page.provider_page_id)
        batch = None if fixture is None else _batch_at(fixture, cursor)

        raw: RawPayload = {"ads": []}
        next_cursor: str | None = None
        if batch is not None:
            raw = batch.raw
            next_cursor = batch.next_cursor

        return ProviderResult(
            raw=raw,
            next_cursor=next_cursor,
            request_meta=RequestMeta(
                provider=self.name,
                origin=self.origin,
                country=country,
                requested_at=requested_at,
                cursor=cursor,
                duration_ms=0,
            ),
            cost_estimate=self._cost_estimate,
        )

    def canary(self) -> CanaryResult:
        """Answer without touching anything.

        Succeeds by construction: the corpus is in memory, so there is nothing
        that could be down.
        """
        return CanaryResult(
            provider=self.name,
            ok=True,
            checked_at=self._clock(),
            detail="served from an in-memory corpus; no network call was made",
            latency_ms=0,
        )


def _batch_at(page: MockPage, cursor: str | None) -> MockBatch | None:
    """Find the batch a cursor points at, or the first one when there is none.

    A batch's `next_cursor` is the handle for the batch *after* it, so the last
    batch's cursor is always `None` and can never be resumed from.

    An unknown cursor ends the walk rather than raising. A provider that has
    moved past a cursor is a normal end-of-results condition, and turning it
    into an error would fail a run that had in fact finished cleanly.
    """
    if cursor is None:
        return page.batches[0] if page.batches else None
    for index, batch in enumerate(page.batches[:-1]):
        if batch.next_cursor == cursor:
            return page.batches[index + 1]
    return None

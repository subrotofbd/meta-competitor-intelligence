"""The `AdDataProvider` contract.

Business logic depends on this protocol and nothing else. A provider is
constructed in `app.composition`, handed in, and called; no service, schema or
route may import a concrete provider module.

## What a provider must never do

* **Touch the database.** It returns data; the orchestrator persists it.
* **Write a file.** No caching, no media, no logs-to-disk.
* **Decide ad status or history.** `provider_active`, `not_seen_since` and
  `presumed_inactive` are conclusions drawn from *our* runs
  (AGENTS.md section 8). A provider reports what it saw, not what it means.
* **Create or update a snapshot.** `ad_snapshots` is append-only and is written
  by the orchestrator, once, after the raw payload is safely stored.

A provider that wanted to persist something would be doing the orchestrator's
job and would break the moment we swapped it out.

## Failure

Providers raise `RateLimited`, `Blocked`, `SchemaChanged` or `Transient` and
nothing else. Orchestration reads `ProviderError.retryable` to decide whether
to try again; a provider never retries internally. `Blocked` and
`SchemaChanged` are terminal, and neither is ever worked around.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.providers.data.models import (
    CanaryResult,
    PageRef,
    ProviderCapabilities,
    ProviderResult,
)
from app.providers.data.provenance import DataOrigin


@runtime_checkable
class AdDataProvider(Protocol):
    """A source of public ad data for tracked pages.

    `runtime_checkable` so the composition root and the contract tests can
    assert a candidate satisfies the shape. It checks that the attributes
    exist, not that they behave -- behaviour is covered by the contract tests
    in `backend/tests`.
    """

    name: str
    """Stable identifier used in run records and the provider registry."""

    origin: DataOrigin
    """Where this provider's data comes from. Drives the evidence class every
    value it returns carries, so it is a property of the provider and not a
    per-call choice."""

    def capabilities(self) -> ProviderCapabilities:
        """What this provider can serve.

        Called before a run is planned, not during it: a provider that cannot
        serve a country or commercial ads has to say so up front rather than
        return empty pages forever.
        """
        ...

    def fetch_page_ads(
        self,
        page: PageRef,
        country: str,
        *,
        cursor: str | None = None,
    ) -> ProviderResult:
        """Fetch one page of a page's ads for one country.

        Args:
            page: The page to collect, in this provider's own identifiers.
            country: ISO-3166 alpha-2 code to collect for.
            cursor: Where to resume, as returned by a previous `next_cursor`.

        Returns:
            The unparsed payload, the normalised reading of it, the cursor for
            the next call, and the accounting for this call.

        Raises:
            RateLimited: The provider asked us to slow down.
            Blocked: Access was refused. Stop the run; do not work around it.
            SchemaChanged: The response no longer matches what we parse.
            Transient: A failure likely to resolve itself.
        """
        ...

    def canary(self) -> CanaryResult:
        """Cheapest possible check that this provider still answers.

        Must be fast and must not collect anything. Its job is to fail loudly
        in seconds instead of partway through a run.
        """
        ...

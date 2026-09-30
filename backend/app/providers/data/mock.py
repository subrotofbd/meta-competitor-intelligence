"""A real, offline ad provider.

`MockProvider` is not test scaffolding. It is registered and built through the
same composition root as any other provider, satisfies the same protocol, and
returns the same types -- which is what lets the whole product be developed and
demonstrated without touching Meta, a paid feed, or a network at all.

It is deterministic. With a fixed clock, the same `(page, cursor)` returns an
equal `ProviderResult` every time, so a test can assert on a whole result
rather than on fragments of one.

## What it actually does

The corpus is injected at construction. Each record is stored twice: as the
`raw` dict the provider "received", and as the normalised `RawAdRecord` its
adapter would produce. `_normalise` is the real parsing step, so the pair stays
honest -- `records` is a reading of `raw`, and a payload the parser cannot
read raises `SchemaChanged` rather than yielding a half-filled record.

## What it refuses to do

No network, no filesystem, no database, no clock of its own beyond the one
injected. A `Blocked` or a `SchemaChanged` here means the corpus is malformed,
which is a bug to fix, not a condition to work around.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final

from app.providers.data.errors import SchemaChanged
from app.providers.data.models import (
    AdFormat,
    CanaryResult,
    CostEstimate,
    MediaRef,
    PageRef,
    ProviderCapabilities,
    ProviderResult,
    RawAdRecord,
    RawPayload,
    RequestMeta,
)
from app.providers.data.provenance import DataOrigin

#: Every raw key `_normalise` reads. Anything else survives untouched in
#: `provider_metadata`, so a field this product has not modelled yet is still
#: available when someone models it.
_MAPPED_KEYS: Final = frozenset(
    {
        "ad_id",
        "ad_creative_bodies",
        "ad_delivery_start_time",
        "format",
        "page_id",
        "page_name",
        "platforms",
        "status",
        "targeted_countries",
    }
)

#: The same, one level down, inside a creative body. A body has more text slots
#: than `RawAdRecord` models -- the link card's own title has nowhere to go --
#: and the leftovers are kept rather than dropped.
_MAPPED_BODY_KEYS: Final = frozenset(
    {
        "body",
        "call_to_action",
        "link_description",
        "link_url",
        "media",
        "title",
    }
)

#: The only creative shape a record can carry. A carousel is one body holding
#: several media entries, which is how a real feed models it too.
_CREATIVE_BODY_KEY: Final = "ad_creative_bodies"

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


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """Read a provider's list of strings without inventing an entry for `None`."""
    if not value:
        return ()
    return tuple(str(item) for item in value)


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a provider timestamp, keeping `None` as `None`.

    A naive datetime is left for the schema to reject: silently assuming a
    timezone is how a delivery start drifts by a day.
    """
    if value is None:
        return None
    return datetime.fromisoformat(str(value))


def _require_ad_id(raw: Mapping[str, Any]) -> str:
    """The one field a record cannot be tracked without."""
    ad_id = raw.get("ad_id")
    if not isinstance(ad_id, str) or not ad_id:
        raise SchemaChanged(
            "provider record has no usable ad_id",
            provider="mock",
            expected="ad_id: non-empty string",
            found=f"ad_id={ad_id!r}",
        )
    return ad_id


def _require_body(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """The creative body, which every record in this corpus carries exactly one of.

    A carousel is one body holding several media entries, not several bodies,
    which is how a real feed reports it and how `RawAdRecord` models it.
    """
    bodies = raw.get(_CREATIVE_BODY_KEY) or []
    if not isinstance(bodies, list) or not bodies:
        raise SchemaChanged(
            "provider record has no creative body",
            provider="mock",
            expected=f"{_CREATIVE_BODY_KEY}: non-empty list",
            found=f"{_CREATIVE_BODY_KEY}={bodies!r}",
        )
    body: Mapping[str, Any] = bodies[0]
    return body


def _read_media(body: Mapping[str, Any]) -> tuple[MediaRef, ...]:
    """Every asset the body references. An empty body yields none, not a guess."""
    return tuple(
        MediaRef(
            provider_key=str(entry.get("key")),
            source_url=entry.get("url"),
            mime=entry.get("mime"),
            width=entry.get("width"),
            height=entry.get("height"),
            duration_seconds=entry.get("duration_seconds"),
        )
        for entry in (body.get("media") or [])
    )


def _unmodelled_fields(
    raw: Mapping[str, Any],
    body: Mapping[str, Any],
    format_value: Any,
    display_format: AdFormat | None,
) -> dict[str, Any]:
    """Everything the provider sent that this product does not model.

    Collected rather than dropped, so a field nobody modelled today is still
    there when someone does. The unrecognised creative format is included: it
    was read, just not understood, and losing it would make `None` look like a
    provider that said nothing.
    """
    fields: dict[str, Any] = {key: value for key, value in raw.items() if key not in _MAPPED_KEYS}
    fields.update((key, value) for key, value in body.items() if key not in _MAPPED_BODY_KEYS)
    if format_value is not None and display_format is None:
        fields["format"] = format_value
    return fields


def _normalise(raw: Mapping[str, Any]) -> RawAdRecord:
    """Read one provider record into a `RawAdRecord`.

    Raises:
        SchemaChanged: A field this adapter depends on is missing or the wrong
            shape. Stopping is the point -- filling a required field with a
            guess would put invented data into the store as observed data.
    """
    ad_id = _require_ad_id(raw)
    body = _require_body(raw)

    format_value = raw.get("format")
    try:
        display_format = AdFormat(format_value) if format_value is not None else None
    except ValueError:
        display_format = None

    call_to_action = body.get("call_to_action") or {}

    return RawAdRecord(
        external_ad_id=ad_id,
        page_id=raw.get("page_id"),
        page_name=raw.get("page_name"),
        platforms=_as_str_tuple(raw.get("platforms")),
        countries=_as_str_tuple(raw.get("targeted_countries")),
        ad_status=raw.get("status"),
        meta_delivery_start=_parse_datetime(raw.get("ad_delivery_start_time")),
        primary_text=body.get("body"),
        headline=body.get("title"),
        description=body.get("link_description"),
        cta=call_to_action.get("type"),
        destination_url=body.get("link_url"),
        media=_read_media(body),
        display_format=display_format,
        provider_metadata=_unmodelled_fields(raw, body, format_value, display_format),
    )


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

        A page the corpus does not hold yields an empty result rather than an
        error: a provider that does not track a page really does have no ads for
        it. The orchestrator sees the empty record count; raising here would
        turn an ordinary "nothing to report" into a run failure.

        Raises:
            SchemaChanged: A corpus record is malformed. That is a bug in the
                fixture, and it must be loud.
        """
        requested_at = self._clock()
        fixture = self._pages.get(page.provider_page_id)
        batch = None if fixture is None else _batch_at(fixture, cursor)

        records: tuple[RawAdRecord, ...] = ()
        raw: RawPayload = {"ads": []}
        next_cursor: str | None = None
        if batch is not None:
            raw = batch.raw
            ads = batch.raw.get("ads", []) if isinstance(batch.raw, Mapping) else []
            records = tuple(_normalise(ad) for ad in ads)
            next_cursor = batch.next_cursor

        return ProviderResult(
            raw=raw,
            records=records,
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

"""The data vocabulary a provider speaks.

Everything crossing the `AdDataProvider` boundary is one of these types. The
point is that no untyped dict survives into business logic: a `dict` reaches
the orchestrator only as the opaque `raw` payload it is required to persist
verbatim before parsing, and every field the product actually uses is a
declared, validated attribute.

The models are frozen. A provider hands its result over and cannot keep editing
it behind the orchestrator's back.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field

from app.providers.data.provenance import DataOrigin

#: The provider's response exactly as received, before any parsing.
#:
#: Deliberately untyped, and the only untyped value in the contract. The
#: orchestrator stores it with a `payload_hash` before it parses anything, so a
#: parser bug can be fixed against the original bytes instead of losing the run
#: (AGENTS.md section 8).
type RawPayload = dict[str, Any] | list[Any]


def _require_http_url(value: str) -> str:
    """Reject anything that is not an absolute http(s) URL.

    Provider output is untrusted input, and these URLs are fetched by later
    checkpoints. Without this check a provider could hand back
    `file:///etc/passwd` or `javascript:...` and have a future fetcher act on
    it. Applied at the boundary so the unsafe value is never stored as if it
    were a normal destination.
    """
    lowered = value.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError(f"URL scheme must be http or https, got {value!r}")
    return value


#: A URL we may later fetch. http(s) only.
type HttpUrl = Annotated[str, AfterValidator(_require_http_url)]


class AdFormat(StrEnum):
    """Creative shapes this product models.

    A provider that reports a shape not listed here yields `None`, not a guess.
    The value is not lost -- it stays in `RawAdRecord.provider_metadata` -- so
    widening this enum later is a display decision, not a re-collection.
    """

    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    CAROUSEL = "CAROUSEL"


class _ContractModel(BaseModel):
    """Frozen, closed models: boundary values cannot be mutated or extended by accident."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PageRef(_ContractModel):
    """The page to collect, as the target provider identifies it.

    Attributes:
        provider_page_id: The provider's own id for the page. This is what
            collection asks for; it is not an internal `facebook_pages` key.
        page_name: Display name, when the provider reports one.
        url: The page's public URL, for human reference. Never fetched by a
            provider.
    """

    provider_page_id: str = Field(min_length=1)
    page_name: str | None = None
    url: HttpUrl | None = None


class MediaRef(_ContractModel):
    """A reference to one creative asset, not the asset itself.

    S0.3 stores references only. No provider downloads bytes, and no store is
    wired into collection, so `source_url` here is a pointer for a later
    checkpoint to resolve -- never something the provider has already fetched.

    Attributes:
        provider_key: The provider's stable id for the asset. Serves as the
            creative identity until the bytes are downloaded and hashed.
        source_url: Where the provider says the asset lives.
        mime: Reported content type, when known.
        width: Reported pixel width, when known.
        height: Reported pixel height, when known.
        duration_seconds: Reported length. Set for video, `None` otherwise.
    """

    provider_key: str = Field(min_length=1)
    source_url: HttpUrl | None = None
    mime: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    duration_seconds: Decimal | None = Field(default=None, ge=0)


class RawAdRecord(_ContractModel):
    """One ad, normalised, exactly as the provider claims it.

    This is a provider's *report*, not our observation of history. It therefore
    has no `first_seen_at`, no `content_hash` and no status we computed:
    `meta_delivery_start` (the provider's own start claim) and `first_seen_at`
    (when we first saw the ad) are different facts and are never merged
    (AGENTS.md section 8).

    Every field the provider may not report is `None`. Absence is recorded as
    absence -- never `0`, never `""`, never a plausible-looking substitute.

    Attributes:
        external_ad_id: The provider's ad id. The only required field, because
            an ad we cannot identify cannot be tracked at all.
        ad_status: The provider's *own* status wording, untranslated. It is not
            `provider_active`; that is a domain status decided later, from our
            own complete runs.
        display_format: The creative shape, or `None` when the provider
            reported a shape this product does not model.
        provider_metadata: Provider fields this product does not model -- at
            the record level or inside a creative body -- kept verbatim rather
            than dropped, so nothing observed is ever thrown away.
    """

    external_ad_id: str = Field(min_length=1)
    page_id: str | None = None
    page_name: str | None = None
    platforms: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    ad_status: str | None = None
    meta_delivery_start: AwareDatetime | None = None
    primary_text: str | None = None
    headline: str | None = None
    description: str | None = None
    cta: str | None = None
    destination_url: HttpUrl | None = None
    media: tuple[MediaRef, ...] = ()
    display_format: AdFormat | None = None
    provider_metadata: Mapping[str, Any] = Field(default_factory=dict)


class ProviderCapabilities(_ContractModel):
    """What a provider can actually serve, declared rather than assumed.

    Read this before designing a collection run. `serves_commercial_ads` is the
    field this project exists on: Meta's own API does not serve Indian
    commercial ads (DATA_ACCESS.md), and a provider that cannot serve them must
    say so here rather than return empty results forever.

    Attributes:
        countries: ISO-3166 alpha-2 codes the provider serves.
        categories: Ad categories the provider distinguishes; empty when it does
            not categorise at all.
        has_history: Whether the provider can return ads that are no longer
            running. Almost none can, for commercial ads -- history comes from
            our own snapshots.
        serves_commercial_ads: Whether normal commercial advertising is
            available, as opposed to political and issue advertising only.
    """

    countries: tuple[str, ...]
    categories: tuple[str, ...] = ()
    has_history: bool
    serves_commercial_ads: bool


class RequestMeta(_ContractModel):
    """What was asked for, and what the provider reported about the call.

    Persisted with every run and shown in the UI, so it deliberately carries no
    tokens, headers or credentials -- only facts a reader may see.

    Attributes:
        country: The country the request targeted.
        requested_at: When the request was made, timezone-aware.
        cursor: The pagination cursor that was sent, if any.
        duration_ms: Wall time the provider reported, if it reported one.
    """

    provider: str = Field(min_length=1)
    origin: DataOrigin
    country: str = Field(min_length=2)
    requested_at: AwareDatetime
    cursor: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class CostEstimate(_ContractModel):
    """What a request is expected to have cost.

    Always an `EvidenceClass.ESTIMATE`: the true figure is the provider's
    invoice, not this number. It is stored with its method so the UI can label
    it as an estimate and say how it was arrived at.

    Attributes:
        amount: Estimated cost. `0` only when the provider genuinely charges
            nothing for the call, stated as such in `method`.
        currency: ISO-4217 code.
        method: How the figure was arrived at. Never omitted.
    """

    amount: Decimal
    currency: str = Field(default="USD", min_length=3, max_length=3)
    method: str = Field(min_length=1)


class ProviderResult(_ContractModel):
    """One page of provider output, plus everything needed to account for it.

    `raw` and `records` are both present on purpose. `raw` is what the provider
    said; `records` is our reading of it. Keeping both lets the orchestrator
    store the original before trusting the interpretation.

    Attributes:
        raw: The unparsed response, to be persisted with a `payload_hash`.
        records: The normalised reading of `raw`. May be empty even when `raw`
            is not, which is a signal worth keeping rather than hiding.
        next_cursor: Cursor for the following page, or `None` at the end.
        request_meta: Facts about the call itself.
        cost_estimate: Expected cost of the call, with its method.
    """

    raw: RawPayload
    records: tuple[RawAdRecord, ...]
    next_cursor: str | None = None
    request_meta: RequestMeta
    cost_estimate: CostEstimate


class CanaryResult(_ContractModel):
    """The answer to "is this provider still working, cheaply?".

    A canary exists so a dead provider is discovered in seconds rather than
    halfway through a run. It must be the cheapest call the provider offers,
    and on the mock it touches nothing at all.

    Attributes:
        ok: Whether the provider answered normally.
        checked_at: When the probe ran, timezone-aware.
        detail: Why it failed, or what it checked, when there is something to say.
        latency_ms: Probe duration, when measured.
    """

    provider: str = Field(min_length=1)
    ok: bool
    checked_at: AwareDatetime
    detail: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)

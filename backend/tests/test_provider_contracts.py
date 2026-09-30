"""The `AdDataProvider` contract and the shapes that cross it.

Two things are checked here that nothing else can check:

* **The protocol is real.** A candidate that is missing a method fails the
  `isinstance` check, so a provider cannot satisfy it by accident.
* **The models are closed.** Frozen, `extra="forbid"`, timezone-aware, and
  refusing any URL that is not http(s). These are the properties that keep
  untrusted provider output from turning into a surprise further in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.providers.data.base import AdDataProvider
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

pytestmark = pytest.mark.contract


def _record(**overrides: object) -> RawAdRecord:
    fields: dict[str, object] = {"external_ad_id": "mock-ad-1", **overrides}
    return RawAdRecord(**fields)  # type: ignore[arg-type]


def _request_meta() -> RequestMeta:
    return RequestMeta(
        provider="mock",
        origin=DataOrigin.third_party,
        country="IN",
        requested_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _cost() -> CostEstimate:
    return CostEstimate(amount=Decimal("0"), method="no billable request")


# ============================================================
# The protocol
# ============================================================


def test_mock_provider_satisfies_the_protocol(ad_provider: AdDataProvider) -> None:
    assert isinstance(ad_provider, AdDataProvider)


def test_a_class_missing_canary_does_not_satisfy_the_protocol() -> None:
    class NoCanary:
        name = "half-a-provider"
        origin = DataOrigin.third_party

        def capabilities(self) -> ProviderCapabilities:  # pragma: no cover - never called
            raise NotImplementedError

        def fetch_page_ads(
            self, page: PageRef, country: str, *, cursor: str | None = None
        ) -> ProviderResult:  # pragma: no cover - never called
            raise NotImplementedError

    assert not isinstance(NoCanary(), AdDataProvider)


def test_a_class_missing_identity_attributes_does_not_satisfy_the_protocol() -> None:
    class NoOrigin:
        name = "no-origin"

    assert not isinstance(NoOrigin(), AdDataProvider)


# ============================================================
# RawAdRecord: absence is recorded as absence
# ============================================================


def test_only_the_ad_id_is_required() -> None:
    """Everything else can genuinely be missing, and all of it can be absent."""
    record = _record()
    assert record.external_ad_id == "mock-ad-1"
    assert record.page_id is None
    assert record.page_name is None
    assert record.ad_status is None
    assert record.meta_delivery_start is None
    assert record.primary_text is None
    assert record.headline is None
    assert record.description is None
    assert record.cta is None
    assert record.destination_url is None
    assert record.display_format is None
    assert record.media == ()
    assert record.platforms == ()
    assert record.countries == ()
    assert dict(record.provider_metadata) == {}


def test_a_blank_ad_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _record(external_ad_id="")


def test_the_record_has_no_field_for_our_own_observation() -> None:
    """`first_seen_at` and `content_hash` are ours to decide, not the provider's.

    Their presence here would be the exact merge AGENTS.md section 8 forbids --
    a provider-reported start date quietly becoming our first sighting.
    """
    forbidden = {"first_seen_at", "content_hash", "creative_hash", "copy_hash", "current_status"}
    assert not forbidden & set(RawAdRecord.model_fields)


def test_unknown_provider_fields_are_refused_rather_than_stored() -> None:
    """A closed model is what makes `provider_metadata` a deliberate channel."""
    with pytest.raises(ValidationError):
        _record(provider_reported_conversions=4200)


def test_records_are_frozen() -> None:
    record = _record()
    with pytest.raises(ValidationError):
        record.primary_text = "mutated after the provider returned it"  # type: ignore[misc]


# ============================================================
# Untrusted input: URLs and timestamps
# ============================================================


@pytest.mark.parametrize(
    "hostile",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "//cdn.example.invalid/no-scheme",
        "ftp://cdn.example.invalid/asset.png",
    ],
)
def test_only_http_urls_are_accepted(hostile: str) -> None:
    """These URLs are fetched by a later checkpoint, so the scheme is checked now."""
    with pytest.raises(ValidationError):
        _record(destination_url=hostile)
    with pytest.raises(ValidationError):
        MediaRef(provider_key="mock-media-1", source_url=hostile)
    with pytest.raises(ValidationError):
        PageRef(provider_page_id="mock-page-1", url=hostile)


def test_a_naive_delivery_start_is_rejected() -> None:
    """Assuming a timezone is how a delivery start silently drifts by a day."""
    with pytest.raises(ValidationError):
        _record(meta_delivery_start=datetime(2026, 8, 12, 9, 30))  # noqa: DTZ001


def test_an_aware_delivery_start_is_kept_verbatim() -> None:
    """The provider's own offset is not normalised away."""
    record = _record(meta_delivery_start=datetime.fromisoformat("2026-08-12T09:30:00+05:30"))
    assert record.meta_delivery_start is not None
    assert record.meta_delivery_start.utcoffset().total_seconds() == 5.5 * 3600


def test_an_unmodelled_format_stays_unmodelled() -> None:
    """Null, not a guess. The original wording is kept by the adapter."""
    assert set(AdFormat) == {AdFormat.IMAGE, AdFormat.VIDEO, AdFormat.CAROUSEL}


# ============================================================
# ProviderResult
# ============================================================


def test_a_result_carries_all_four_contract_fields() -> None:
    result = ProviderResult(
        raw={"ads": []},
        next_cursor="next",
        request_meta=_request_meta(),
        cost_estimate=_cost(),
    )
    assert set(ProviderResult.model_fields) == {
        "raw",
        "next_cursor",
        "request_meta",
        "cost_estimate",
    }
    assert result.next_cursor == "next"


def test_a_result_carries_no_reading_of_its_own_payload() -> None:
    """A provider returns provider data. Reading it is not the provider's job.

    The field this rules out used to be here, and it is why a malformed record
    could cost us the response it arrived in: a provider that reads its own
    payload can refuse to return at all, so the refusal happens before anything
    is stored. With no reading to disagree with, `raw` is all a provider has and
    all we need to keep.
    """
    assert "records" not in ProviderResult.model_fields


def test_a_result_without_cost_accounting_is_rejected() -> None:
    """Silence would be indistinguishable from a free request."""
    with pytest.raises(ValidationError):
        ProviderResult(
            raw={"ads": []},
            request_meta=_request_meta(),
        )


def test_a_result_carries_no_credential_field() -> None:
    """`request_meta` is persisted with every run and shown in the UI."""
    forbidden = {"token", "access_token", "headers", "cookies", "api_key", "authorization"}
    assert not forbidden & set(RequestMeta.model_fields)
    assert not forbidden & set(ProviderResult.model_fields)


def test_the_raw_payload_is_the_only_untyped_value() -> None:
    """`raw` is deliberately opaque: it is hashed and stored before parsing."""
    raw: RawPayload = [{"anything": [1, 2, 3]}]
    result = ProviderResult(
        raw=raw,
        request_meta=_request_meta(),
        cost_estimate=_cost(),
    )
    assert result.raw == [{"anything": [1, 2, 3]}]


def test_a_cost_estimate_must_state_its_method() -> None:
    with pytest.raises(ValidationError):
        CostEstimate(amount=Decimal("0.01"))


def test_capabilities_declare_commercial_ad_availability() -> None:
    """The field this project turns on: India commercial ads are not universal.

    It is required rather than defaulted. A provider that omits it would
    default to whichever answer was convenient, and the collection run would
    quietly collect nothing.
    """
    capabilities = ProviderCapabilities(
        countries=("IN",),
        has_history=False,
        serves_commercial_ads=False,
    )
    assert capabilities.serves_commercial_ads is False
    assert set(ProviderCapabilities.model_fields) == {
        "countries",
        "categories",
        "has_history",
        "serves_commercial_ads",
    }
    with pytest.raises(ValidationError):
        ProviderCapabilities(countries=("IN",), has_history=False)


def test_a_canary_result_is_immutable_and_dated() -> None:
    canary = CanaryResult(
        provider="mock",
        ok=True,
        checked_at=datetime(2026, 9, 1, tzinfo=UTC),
        latency_ms=0,
    )
    with pytest.raises(ValidationError):
        canary.ok = False  # type: ignore[misc]

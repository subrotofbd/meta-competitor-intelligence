"""`MockProvider`, and the corpus it serves.

The ten scenarios the checkpoint asks the corpus to cover are each pinned to a
named test below, so a fixture edit that quietly removes one of them fails
loudly instead of shrinking coverage without anyone noticing.

Everything here is offline. The provider holds its corpus in memory, injected at
construction, and performs no I/O of any kind.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from app.providers.data.base import AdDataProvider
from app.providers.data.errors import SchemaChanged
from app.providers.data.mock import MockBatch, MockPage, MockProvider
from app.providers.data.models import AdFormat, PageRef, ProviderResult, RawAdRecord
from app.providers.data.provenance import DataOrigin, EvidenceClass, evidence_class_for

pytestmark = pytest.mark.contract

PAGE_ONE = PageRef(provider_page_id="mock-page-0001", page_name="Aurora Kitchen Studio")
PAGE_TWO = PageRef(provider_page_id="mock-page-0002", page_name="Northwind Fitness Club")

FIXED_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _walk(provider: AdDataProvider, page: PageRef, country: str) -> Iterator[RawAdRecord]:
    """Collect every record a full cursor walk yields, in order."""
    cursor: str | None = None
    while True:
        result = provider.fetch_page_ads(page, country, cursor=cursor)
        yield from result.records
        cursor = result.next_cursor
        if cursor is None:
            return


# ============================================================
# Identity, capabilities, canary
# ============================================================


def test_the_provider_declares_itself(ad_provider: AdDataProvider) -> None:
    assert ad_provider.name == "mock"
    assert ad_provider.origin is DataOrigin.third_party


def test_the_mock_is_provider_data_never_verified_data(ad_provider: AdDataProvider) -> None:
    """A mock must never be badgeable as verified public data."""
    assert evidence_class_for(ad_provider.origin) is EvidenceClass.PROVIDER_DATA


def test_capabilities_state_that_there_is_no_history(ad_provider: AdDataProvider) -> None:
    """History comes from our own snapshots. Saying otherwise would be a lie."""
    capabilities = ad_provider.capabilities()
    assert capabilities.has_history is False
    assert capabilities.serves_commercial_ads is True
    assert "IN" in capabilities.countries


def test_the_canary_succeeds_without_touching_anything(ad_provider: AdDataProvider) -> None:
    canary = ad_provider.canary()
    assert canary.ok is True
    assert canary.provider == "mock"
    assert canary.latency_ms == 0
    assert canary.detail is not None and "no network" in canary.detail


def test_the_canary_is_deterministic(ad_provider: AdDataProvider) -> None:
    assert ad_provider.canary() == ad_provider.canary()


def test_fetching_is_deterministic(ad_provider: AdDataProvider) -> None:
    first = ad_provider.fetch_page_ads(PAGE_ONE, "IN")
    second = ad_provider.fetch_page_ads(PAGE_ONE, "IN")
    assert first == second


# ============================================================
# Scenario 1 -- image ad
# ============================================================


def test_scenario_01_image_ad(ad_provider: AdDataProvider) -> None:
    record = ad_provider.fetch_page_ads(PAGE_ONE, "IN").records[0]
    assert record.external_ad_id == "mock-ad-000101"
    assert record.display_format is AdFormat.IMAGE
    assert len(record.media) == 1
    assert record.media[0].mime == "image/png"
    assert record.media[0].duration_seconds is None


# ============================================================
# Scenario 2 -- video ad
# ============================================================


def test_scenario_02_video_ad(ad_provider: AdDataProvider) -> None:
    record = ad_provider.fetch_page_ads(PAGE_ONE, "IN").records[1]
    assert record.display_format is AdFormat.VIDEO
    assert record.media[0].duration_seconds is not None
    assert float(record.media[0].duration_seconds) == pytest.approx(91.4)


# ============================================================
# Scenario 3 -- carousel ad
# ============================================================


def test_scenario_03_carousel_ad(ad_provider: AdDataProvider) -> None:
    carousel = ad_provider.fetch_page_ads(PAGE_ONE, "IN", cursor="mock-cursor-0001-a").records[0]
    assert carousel.external_ad_id == "mock-ad-000103"
    assert carousel.display_format is AdFormat.CAROUSEL
    assert len(carousel.media) == 3
    assert len({media.provider_key for media in carousel.media}) == 3


# ============================================================
# Scenario 4 -- multiple copy variations
# ============================================================


def test_scenario_04_multiple_copy_variations(ad_provider: AdDataProvider) -> None:
    records = [record for page in (PAGE_ONE, PAGE_TWO) for record in _walk(ad_provider, page, "IN")]
    bodies = {record.primary_text for record in records if record.primary_text}
    assert len(bodies) >= 5
    headlines = {record.headline for record in records if record.headline}
    assert len(headlines) >= 5


# ============================================================
# Scenario 5 -- different dates
# ============================================================


def test_scenario_05_different_dates(ad_provider: AdDataProvider) -> None:
    records = list(_walk(ad_provider, PAGE_ONE, "IN"))
    starts = {record.meta_delivery_start for record in records if record.meta_delivery_start}
    assert len(starts) >= 3
    assert all(start.tzinfo is not None for start in starts if start)


def test_a_provider_start_is_never_confused_with_our_first_sighting() -> None:
    """`meta_delivery_start` is the provider's claim and stays labelled as such."""
    assert "first_seen_at" not in RawAdRecord.model_fields


# ============================================================
# Scenario 6 -- multiple platforms
# ============================================================


def test_scenario_06_multiple_platforms(ad_provider: AdDataProvider) -> None:
    platforms: set[str] = set()
    for page in (PAGE_ONE, PAGE_TWO):
        platforms.update(
            platform for record in _walk(ad_provider, page, "IN") for platform in record.platforms
        )
    assert {"facebook", "instagram", "messenger", "audience_network"} <= platforms


# ============================================================
# Scenario 7 -- multiple countries
# ============================================================


def test_scenario_07_multiple_countries(ad_provider: AdDataProvider) -> None:
    countries: set[str] = set()
    for page in (PAGE_ONE, PAGE_TWO):
        for country in ("IN", "GB"):
            countries.update(
                country_code
                for record in _walk(ad_provider, page, country)
                for country_code in record.countries
            )
    assert {"IN", "GB", "IE"} <= countries


def test_the_requested_country_is_recorded_separately_from_the_targeted_ones() -> None:
    """What we asked for is not what the ad targeted, and both are stored."""
    provider = MockProvider()
    result = provider.fetch_page_ads(PAGE_ONE, "GB")
    assert result.request_meta.country == "GB"


# ============================================================
# Scenario 8 -- different landing pages
# ============================================================


def test_scenario_08_different_landing_pages(ad_provider: AdDataProvider) -> None:
    destinations = set()
    for page in (PAGE_ONE, PAGE_TWO):
        for record in _walk(ad_provider, page, "IN"):
            if record.destination_url:
                destinations.add(record.destination_url)
    assert len(destinations) >= 5
    assert all(url.startswith("https://") for url in destinations)


# ============================================================
# Scenario 9 -- repeated creative
# ============================================================


def test_scenario_09_repeated_creative(ad_provider: AdDataProvider) -> None:
    records = {record.external_ad_id: record for record in _walk(ad_provider, PAGE_TWO, "GB")}
    first = records["mock-ad-000201"]
    second = records["mock-ad-000202"]
    assert first.media[0].provider_key == second.media[0].provider_key
    assert first.media[0].source_url == second.media[0].source_url
    assert first.destination_url != second.destination_url


# ============================================================
# Scenario 10 -- changed copy
# ============================================================


def test_scenario_10_changed_copy(ad_provider: AdDataProvider) -> None:
    """The same ad id served twice with different copy, within one walk.

    This is the input the append-only snapshot logic needs in S2.1: a second
    observation of an ad whose `content_hash` differs. The provider is not
    responsible for noticing -- it returns what it saw, in order.
    """
    records = list(_walk(ad_provider, PAGE_ONE, "IN"))
    occurrences = [record for record in records if record.external_ad_id == "mock-ad-000101"]
    assert len(occurrences) == 2
    assert occurrences[0].primary_text != occurrences[1].primary_text
    assert occurrences[0].headline != occurrences[1].headline
    assert occurrences[0].media[0].provider_key != occurrences[1].media[0].provider_key


# ============================================================
# Cursor walking and the raw/records pairing
# ============================================================


def test_a_full_walk_visits_every_batch_once(ad_provider: AdDataProvider) -> None:
    result = ad_provider.fetch_page_ads(PAGE_ONE, "IN")
    assert result.next_cursor == "mock-cursor-0001-a"
    second = ad_provider.fetch_page_ads(PAGE_ONE, "IN", cursor=result.next_cursor)
    assert second.request_meta.cursor == "mock-cursor-0001-a"
    assert second.next_cursor == "mock-cursor-0001-b"
    third = ad_provider.fetch_page_ads(PAGE_ONE, "IN", cursor=second.next_cursor)
    assert third.next_cursor is None


def test_an_unknown_cursor_ends_the_walk_without_failing(ad_provider: AdDataProvider) -> None:
    """A provider that has moved past a cursor has finished, not broken."""
    result = ad_provider.fetch_page_ads(PAGE_ONE, "IN", cursor="mock-cursor-that-was-never-issued")
    assert result.records == ()
    assert result.next_cursor is None


def test_raw_and_records_describe_the_same_response(ad_provider: AdDataProvider) -> None:
    """`raw` is what the provider said; `records` is our reading of it."""
    result = ad_provider.fetch_page_ads(PAGE_ONE, "IN")
    assert len(result.raw["ads"]) == len(result.records)
    assert result.raw["ads"][0]["ad_id"] == result.records[0].external_ad_id


def test_an_unmodelled_format_is_kept_but_not_guessed(ad_provider: AdDataProvider) -> None:
    record = ad_provider.fetch_page_ads(PAGE_TWO, "GB", cursor="mock-cursor-0002-a").records[-1]
    assert record.display_format is None
    assert record.provider_metadata["format"] == "DYNAMIC"


def test_a_sparse_record_stays_sparse(ad_provider: AdDataProvider) -> None:
    """A record that reported almost nothing keeps reporting almost nothing."""
    record = ad_provider.fetch_page_ads(PAGE_TWO, "GB", cursor="mock-cursor-0002-a").records[-1]
    assert record.external_ad_id == "mock-ad-000203"
    assert record.ad_status is None
    assert record.meta_delivery_start is None
    assert record.primary_text is None
    assert record.headline is None
    assert record.cta is None
    assert record.destination_url is None
    assert record.media == ()
    assert record.platforms == ()
    assert record.countries == ()


def test_unmodelled_provider_fields_survive(ad_provider: AdDataProvider) -> None:
    """Nothing observed is thrown away, at the record level or the body level."""
    record = ad_provider.fetch_page_ads(PAGE_ONE, "IN").records[0]
    assert record.provider_metadata["experiment_variant"] == "a"
    assert record.provider_metadata["link_title"] == "See the cycle test"
    assert "ad_creative_bodies" not in record.provider_metadata


def test_the_provider_reports_its_own_cost_honestly(ad_provider: AdDataProvider) -> None:
    result = ad_provider.fetch_page_ads(PAGE_ONE, "IN")
    assert result.cost_estimate is not None
    assert result.cost_estimate.amount == 0
    assert result.cost_estimate.method


def test_a_page_the_corpus_does_not_hold_yields_no_records() -> None:
    """A provider that does not track a page has no ads for it -- not an error."""
    provider = MockProvider()
    result = provider.fetch_page_ads(PageRef(provider_page_id="mock-page-9999"), "IN")
    assert result.records == ()
    assert result.next_cursor is None


def test_a_malformed_record_stops_the_run_loudly() -> None:
    """Filling a required field with a guess would store invented data as observed.

    So a record with no usable id raises `SchemaChanged` -- terminal, and not
    retryable, because retrying would only produce the same bad record.
    """
    page = MockPage(
        page=PAGE_ONE,
        batches=(MockBatch(raw={"ads": [{"page_id": "mock-page-0001"}]}),),
    )
    provider = MockProvider({PAGE_ONE.provider_page_id: page})
    with pytest.raises(SchemaChanged) as raised:
        provider.fetch_page_ads(PAGE_ONE, "IN")
    assert raised.value.retryable is False
    assert raised.value.expected.startswith("ad_id")


def test_a_record_with_no_creative_body_also_stops_the_run() -> None:
    page = MockPage(
        page=PAGE_ONE,
        batches=(MockBatch(raw={"ads": [{"ad_id": "mock-ad-000199"}]}),),
    )
    provider = MockProvider({PAGE_ONE.provider_page_id: page})
    with pytest.raises(SchemaChanged):
        provider.fetch_page_ads(PAGE_ONE, "IN")


# ============================================================
# No I/O
# ============================================================


def test_the_provider_reads_nothing_from_disk_and_uses_the_injected_clock() -> None:
    """Constructed with a corpus, a cost and a clock -- and nothing else.

    The clock is the only time source. If the provider called
    `datetime.now()` itself, every run's records would differ and a whole
    `ProviderResult` could not be compared.
    """
    calls = 0

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        return FIXED_NOW

    provider = MockProvider(clock=clock)
    result = provider.fetch_page_ads(PAGE_ONE, "IN")
    assert isinstance(result, ProviderResult)
    assert result.request_meta.requested_at == FIXED_NOW
    assert calls == 1

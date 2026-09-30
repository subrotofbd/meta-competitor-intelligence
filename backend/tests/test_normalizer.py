"""The provider response normalizer, and what it refuses to do.

S1.3 is normalizer-only. These are hermetic unit tests on purpose: the
normalizer is a pure function from a provider payload to `RawAdRecord` values,
so nothing here needs a database, and adding one would only prove that the
persistence layer -- which belongs to S2.1 -- accepts rows. It does not prove
that the reading of a payload is faithful, which is the whole job.

Every case is pinned to a fixture. Malformed input is the part of a normalizer
that rots quietly: a stricter reader is a bug report from a user, a looser one
is invented data in a report nobody can audit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.providers.data.models import AdFormat
from app.providers.data.normalize import (
    NormalizationErrorKind,
    NormalizationResult,
    RecordRejectedError,
    normalize_payload,
    normalize_record,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def records(normalizer_payloads: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The readable records, keyed by fixture name."""
    return {name: raw for name, raw in normalizer_payloads["records"].items() if name != "rejected"}


@pytest.fixture
def rejected(normalizer_payloads: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The deliberately unreadable records, each with the error it must produce."""
    return normalizer_payloads["records"]["rejected"]


# ============================================================
# A readable payload becomes a record, and every field is the provider's own
# ============================================================


def test_a_valid_payload_becomes_a_record(records: dict[str, Any]) -> None:
    record = normalize_record(records["complete"])

    assert record.external_ad_id == "mock-ad-000401"
    assert record.page_id == "mock-page-0004"
    assert record.page_name == "Harbourline Optics"
    assert record.platforms == ("facebook", "instagram")
    assert record.countries == ("IN", "GB")
    assert record.ad_status == "active"
    assert record.headline == "Reading glasses that survive a rickshaw commute"
    assert record.primary_text.startswith("Anti-glare coating")
    assert record.cta == "SHOP_NOW"
    assert str(record.destination_url) == (
        "https://harbourline.example.invalid/optics/coating-test"
    )
    assert record.display_format is AdFormat.VIDEO


def test_a_timestamp_keeps_the_offset_the_provider_reported(records: dict[str, Any]) -> None:
    """A delivery start is the field duration is computed from.

    Localising it is not a cosmetic choice: a start read as UTC instead of
    IST moves an ad's apparent age by five and a half hours, and a start with
    its offset stripped cannot be recovered at all.
    """
    record = normalize_record(records["complete"])

    assert record.meta_delivery_start is not None
    assert record.meta_delivery_start.utcoffset() == timedelta(hours=5, minutes=30)
    assert record.meta_delivery_start == datetime(2026, 7, 2, 5, 45, tzinfo=UTC)


def test_media_keeps_every_reported_dimension(records: dict[str, Any]) -> None:
    record = normalize_record(records["complete"])

    assert [asset.provider_key for asset in record.media] == [
        "mock-media-0401-a",
        "mock-media-0401-b",
    ]
    video, still = record.media
    assert video.width == 1080
    assert video.height == 1920
    assert video.duration_seconds == Decimal("27.5")
    assert str(video.source_url) == "https://cdn.example.invalid/p/harbourline-reel.mp4"
    # A still image has no duration, and `None` is not `0`: zero would claim
    # the provider measured a zero-length video.
    assert still.duration_seconds is None


# ============================================================
# The three absences stay apart, and none of them is filled in
# ============================================================


def test_a_field_the_provider_never_sent_is_absent(records: dict[str, Any]) -> None:
    record = normalize_record(records["sparse"])

    assert record.page_id is None
    assert record.page_name is None
    assert record.ad_status is None
    assert record.display_format is None
    assert record.cta is None
    assert record.destination_url is None
    assert record.meta_delivery_start is None
    assert record.platforms == ()
    assert record.countries == ()
    assert record.media == ()


def test_an_explicit_null_is_absent_rather_than_empty(records: dict[str, Any]) -> None:
    record = normalize_record(records["explicit_nulls"])

    assert record.page_id is None
    assert record.primary_text is None
    assert record.headline is None
    assert record.destination_url is None
    assert record.platforms == ()
    assert record.media == ()


def test_an_empty_string_is_kept_as_the_empty_string(records: dict[str, Any]) -> None:
    """A provider that said "no text" is not a provider that said nothing.

    Collapsing the two would make a real report of an empty creative
    indistinguishable from a field we simply do not read yet, and there is no
    way to tell them apart again downstream.
    """
    record = normalize_record(records["empty_values"])

    assert record.page_id == ""
    assert record.primary_text == ""
    assert record.headline == ""
    assert record.ad_status == ""
    # An empty list is genuinely empty, so there is nothing to distinguish.
    assert record.platforms == ()
    assert record.media == ()
    # Text keeps `""` because `str | None` can say so. A URL cannot: a blank
    # URL is not a broken URL, it is an absent one, and reporting it as a
    # fetch problem would point someone at a bug that is not there.
    assert record.destination_url is None


# ============================================================
# Copy is never rewritten
# ============================================================


def test_non_ascii_copy_survives_verbatim(records: dict[str, Any]) -> None:
    """Hindi and Hinglish are the original copy, not a rendering of it.

    No transliteration, no translation, no trimming of the em dash. A normalizer
    that "tidied" copy would change what the ad says, and a later checkpoint
    that analyses the tidy version would be analysing something nobody ran.
    """
    record = normalize_record(records["hinglish"])

    assert record.headline == "हर सुबह तीन मिनट"
    assert (
        record.primary_text
        == "एक कैप्सूल, तीन मिनट — बस इतना। आयुर्वेदिक चूर्ण, कोई रसायन नहीं। आज ही ऑर्डर करें।"
    )
    assert record.description == "पूरी सामग्री सूची यहाँ देखें — तुलना, सच्चाई के साथ।"


# ============================================================
# Fields nobody modelled are kept, not dropped
# ============================================================


def test_an_unmodelled_record_field_is_kept_verbatim(records: dict[str, Any]) -> None:
    record = normalize_record(records["unknown_fields"])

    assert record.provider_metadata["auction_type"] == "AUCTION"


def test_an_unmodelled_body_field_is_kept_verbatim(records: dict[str, Any]) -> None:
    """The link card's own title has no `RawAdRecord` field.

    Dropping it would mean a real observation was lost the first time a payload
    is read, and there is no second copy of it once the raw response is gone.
    """
    record = normalize_record(records["unknown_fields"])

    assert record.provider_metadata["link_title"] == "Unmodelled body key"
    assert record.provider_metadata["link_carousel_cards"] == [
        {"title": "Card one", "url": "https://coastal.example.invalid/cards/one"}
    ]


def test_an_unmodelled_creative_shape_is_recorded_rather_than_guessed(
    records: dict[str, Any],
) -> None:
    """A shape we do not model is `None` -- but the provider's own wording is kept.

    `None` alone would read as "the provider reported no format" when in fact it
    reported one we could not read. Keeping the original makes widening
    `AdFormat` a display decision instead of a re-collection.
    """
    record = normalize_record(records["unknown_fields"])

    assert record.display_format is None
    assert record.provider_metadata["format"] == "CATALOG_CAROUSEL_LIKE"


# ============================================================
# A record that cannot be read says so, and says which field and why
# ============================================================


def test_a_record_with_no_creative_body_is_refused(records: dict[str, Any]) -> None:
    """Not an ad with no copy -- a payload we cannot read.

    A row of nulls here would later read as "the provider reported an ad with
    no text", which is a claim we have no evidence for.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(records["sparse"] | {"ad_creative_bodies": None})

    assert raised.value.error.kind is NormalizationErrorKind.MALFORMED_PAYLOAD
    assert raised.value.error.field == "ad_creative_bodies"


def test_every_declared_rejection_is_rejected_as_declared(
    rejected: dict[str, dict[str, Any]],
) -> None:
    """Each malformed record, checked against the error the fixture declares.

    Driven by the fixture rather than a hand-written list so a case added to the
    corpus cannot sit there unasserted, and a renamed expectation cannot leave
    a test passing for the wrong reason.
    """
    assert rejected, "the rejection corpus is empty, so this would pass vacuously"
    for name, case in sorted(rejected.items()):
        with pytest.raises(RecordRejectedError) as raised:
            normalize_record(case["ad"])
        assert raised.value.error.kind == case["kind"], name
        assert raised.value.error.field == case["field"], name


def test_a_record_level_failure_names_its_position_and_an_envelope_one_does_not(
    rejected: dict[str, dict[str, Any]],
    normalizer_payloads: dict[str, Any],
) -> None:
    """`index` is what separates "skip this ad" from "stop the run".

    `kind` deliberately does not: a caller that watches only the kind cannot tell
    a broken envelope from a single unreadable ad, and the two call for opposite
    responses. The index is the whole of that distinction, so it is pinned.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(rejected["missing_ad_id"]["ad"])
    assert raised.value.error.index is None

    result = normalize_payload(normalizer_payloads["payloads"]["partial"])
    assert all(error.index is not None for error in result.errors)

    envelope = normalize_payload("not an object at all")
    assert envelope.errors[0].index is None


def test_a_rejection_names_the_field_and_the_reason(rejected: dict[str, Any]) -> None:
    """The error is structured, because the response to it differs by cause.

    A missing identity is a provider omission to report; a bad URL is something
    we will not fetch; a naive timestamp is a provider bug worth telling them
    about. One flat "invalid record" message supports none of those.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(rejected["unparseable_date"]["ad"])

    error = raised.value.error
    assert error.kind is NormalizationErrorKind.INVALID_DATE
    assert error.field == "ad_delivery_start_time"
    assert "02-07-2026" in str(raised.value)


def test_a_url_we_would_not_fetch_is_refused_rather_than_repaired(
    rejected: dict[str, Any],
) -> None:
    """`ftp://` and a schemeless host both stay out of the record.

    Repairing either would mean guessing at a destination we would then be
    storing as though the provider had named it. A URL a later checkpoint
    fetches is untrusted input; it is not ours to edit.
    """
    for case in ("unusable_link_scheme", "schemeless_link"):
        with pytest.raises(RecordRejectedError) as raised:
            normalize_record(rejected[case]["ad"])
        assert raised.value.error.kind is NormalizationErrorKind.INVALID_URL
        assert raised.value.error.field == "link_url"


def test_a_naive_timestamp_is_refused_rather_than_assumed_to_be_utc(
    rejected: dict[str, Any],
) -> None:
    """No default timezone. A guessed one silently shifts a delivery start.

    The offset is the difference between an ad that started at 11:15 and one
    that started at 05:45, and duration is displayed from this field.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(rejected["date_without_an_offset"]["ad"])

    assert raised.value.error.kind is NormalizationErrorKind.INVALID_DATE
    assert "offset" in raised.value.error.detail


# ============================================================
# Untrusted input must not become invented data, or forge a log line
# ============================================================


def test_a_label_that_is_not_a_string_is_refused_rather_than_stringified(
    rejected: dict[str, Any],
) -> None:
    """`{"name": "facebook"}` is not the platform `{'name': 'facebook'}`.

    Coercing it would put a value into a report that no one could explain and no
    one could correct, and it would be stored beside labels the provider really
    did send. A refused record is recoverable; an invented label is not.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(rejected["platform_item_not_a_string"]["ad"])

    assert raised.value.error.kind is NormalizationErrorKind.INVALID_TYPE
    assert raised.value.error.field == "platforms[0]"


def test_a_boolean_is_not_a_pixel_measurement(rejected: dict[str, Any]) -> None:
    """Python says a boolean is an `int`. A stored width of `1` would not.

    A creative reported as `true` pixels tall is a provider bug, and reading it
    as one pixel high is a measurement we would then display as fact.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(rejected["media_height_is_a_boolean"]["ad"])

    assert raised.value.error.field == "height"


def test_a_url_with_a_port_or_credentials_is_stored_verbatim() -> None:
    """Checking that a host exists must not become checking that a host is simple.

    A port, a query, a fragment and userinfo are all things real destinations
    legitimately have. The point of refusing `https:///offer` was that there was
    nothing to connect to -- not that the URL looked unfamiliar.
    """
    for link in (
        "https://example.invalid:8443/a?b=c#d",
        "https://user:pass@example.invalid/a",
        "https://example.invalid?query=only",
    ):
        record = normalize_record(
            {
                "ad_id": "mock-ad-000428",
                "ad_creative_bodies": [{"body": "Copy.", "link_url": link}],
            }
        )
        assert str(record.destination_url) == link


def test_a_url_carrying_a_control_character_is_refused(
    rejected: dict[str, Any],
) -> None:
    """A stored URL must not be able to split a request.

    The URL is kept verbatim or not at all: stripping the newline would mean
    storing a destination the provider never sent, and the whole point of this
    module is that what we store is what the provider said.
    """
    with pytest.raises(RecordRejectedError) as raised:
        normalize_record(rejected["url_with_a_newline"]["ad"])

    assert raised.value.error.kind is NormalizationErrorKind.INVALID_URL
    assert "control character" in raised.value.error.detail


def test_a_url_without_a_host_is_refused() -> None:
    """`https:///offer` passes a scheme check and means nothing.

    A prefix test is not a URL parser, and this is the case that shows it: the
    scheme is right and the value is not a destination. Written inline rather
    than as a fixture because a committed fixture containing a hostless URL
    would be rejected by the fixture safety scanner, which is right to be
    suspicious of one.
    """
    for link in (
        "https:///offer",
        "https://",
        "http:///a/b",
        "https://:8443/a",
        "https:// ",
        "https://.",
    ):
        with pytest.raises(RecordRejectedError) as raised:
            normalize_record(
                {
                    "ad_id": "mock-ad-000428",
                    "ad_creative_bodies": [{"body": "Copy.", "link_url": link}],
                }
            )
        assert raised.value.error.kind is NormalizationErrorKind.INVALID_URL, link
        assert "no host" in raised.value.error.detail, link


def test_an_error_detail_can_never_carry_a_newline(
    rejected: dict[str, dict[str, Any]],
) -> None:
    """A provider must not be able to write into our logs.

    `detail` is documented as safe to log and is going to be logged, so quoting
    a provider's creative body into it is a forged log record. Every rejection
    in the corpus is checked, so a reader added later inherits the guarantee
    instead of having to remember it.
    """
    for name, case in sorted(rejected.items()):
        with pytest.raises(RecordRejectedError) as raised:
            normalize_record(case["ad"])
        detail = raised.value.error.detail
        assert "\n" not in detail, name
        assert "\r" not in detail, name


def test_an_error_detail_is_bounded(rejected: dict[str, dict[str, Any]]) -> None:
    """A provider that fails cannot also bury the run it failed in.

    One record carrying a megabyte of junk must not be able to write a megabyte
    into a log line that a human is trying to read.
    """
    from app.providers.data.normalize import DETAIL_LIMIT

    def detail_for(junk: str) -> str:
        with pytest.raises(RecordRejectedError) as raised:
            normalize_record(
                {"ad_id": "mock-ad-000429", "ad_creative_bodies": junk},
            )
        return raised.value.error.detail

    short = detail_for("j" * 10)
    huge = detail_for("j" * 100_000)

    # The point is not the exact budget but that the two are the same order of
    # magnitude: a detail that grew with its input would be a provider choosing
    # how much of our log it takes.
    assert len(huge) <= len(short) + 2 * DETAIL_LIMIT
    assert len(huge) < 200
    assert "characters" in huge

    for name, case in sorted(rejected.items()):
        with pytest.raises(RecordRejectedError) as raised:
            normalize_record(case["ad"])
        assert len(raised.value.error.detail) < 200, name


def test_a_record_is_not_changed_by_editing_the_payload_afterwards(
    records: dict[str, Any],
) -> None:
    """The record is a reading of the payload, not a view onto it.

    The unmodelled fields are copied into a fresh mapping, so a caller that
    reuses and edits a payload dict cannot reach back and change a record that
    has already been normalised -- which is what makes two runs of the same
    collection comparable.
    """
    payload = json.loads(json.dumps(records["unknown_fields"]))
    record = normalize_record(payload)

    payload["auction_type"] = "changed"
    payload["ad_creative_bodies"][0]["link_title"] = "changed"

    assert record.provider_metadata["auction_type"] == "AUCTION"
    assert record.provider_metadata["link_title"] == "Unmodelled body key"


# ============================================================
# A batch is not all-or-nothing
# ============================================================


def test_one_unreadable_record_costs_one_record(
    normalizer_payloads: dict[str, Any],
) -> None:
    """The readable records around a bad one still come back.

    Dropping the whole page would lose good observations over a single bad ad;
    keeping only the good ones would lose the evidence that the bad one existed.
    """
    result = normalize_payload(normalizer_payloads["payloads"]["partial"])

    assert [record.external_ad_id for record in result.records] == [
        "mock-ad-000431",
        "mock-ad-000433",
    ]
    assert len(result.errors) == 1
    assert result.errors[0].index == 1
    assert result.errors[0].field == "ad_id"


def test_a_batch_of_unreadable_records_reports_every_one(
    normalizer_payloads: dict[str, Any],
) -> None:
    """Errors are collected, not just the first one.

    A provider debugging a broken feed needs the whole picture; returning only
    the first failure means one round trip per broken record.
    """
    result = normalize_payload(normalizer_payloads["payloads"]["all_unreadable"])

    assert result.records == ()
    assert [(error.index, error.field) for error in result.errors] == [
        (0, "ad_id"),
        (1, "link_url"),
    ]


def test_an_empty_response_is_not_a_failure(normalizer_payloads: dict[str, Any]) -> None:
    """A provider that reports no ads reports an empty list.

    Turning that into an error would fail every run on a quiet page, and the
    two are not the same event. Both fixture shapes are read here: an explicit
    empty list, and a response that simply never mentioned ads.
    """
    for name in ("empty", "no_ads_key"):
        result = normalize_payload(normalizer_payloads["payloads"][name])
        assert result == NormalizationResult((), ()), name


def test_a_payload_that_is_not_a_response_is_reported(
    normalizer_payloads: dict[str, Any],
) -> None:
    """A response envelope we do not recognise is an error, not an empty page.

    Reading an unrecognised shape as "no ads" is the failure mode that is
    hardest to notice: the run succeeds and the history quietly stops, and
    nothing in the run record says anything went wrong.
    """
    result = normalize_payload(normalizer_payloads["payloads"]["ads_key_not_a_list"])
    assert result.records == ()
    assert result.errors[0].kind is NormalizationErrorKind.MALFORMED_PAYLOAD
    assert result.errors[0].index is None

    for payload in ("a bare string", 42, []):
        reported = normalize_payload(payload)
        assert reported.records == ()
        assert reported.errors[0].kind is NormalizationErrorKind.MALFORMED_PAYLOAD


# ============================================================
# Determinism: the same payload always reads the same way
# ============================================================


def test_the_same_payload_reads_identically_every_time(
    normalizer_payloads: dict[str, Any],
) -> None:
    """A re-read is a check on the stored payload, so it must be a check we
    can trust.

    Nothing in the normalizer may depend on a clock, on ordering of a set, or
    on a previous call. If it did, a replay would produce a different answer
    than the original run and the snapshot it was taken from would no longer
    explain the record.
    """
    payload = normalizer_payloads["payloads"]["duplicate_identifier"]
    first = normalize_payload(payload)
    second = normalize_payload(payload)

    assert first.records == second.records
    assert first.errors == second.errors


def test_a_payload_read_from_stored_json_matches_the_one_in_memory(
    normalizer_payloads: dict[str, Any],
) -> None:
    """Round-tripping through JSON changes nothing.

    This is the shape of a real replay: the raw response went to
    `raw_responses.payload` as JSONB and is read back years later. If
    normalising the re-read value gave a different record, the stored evidence
    would not support the record built from it.
    """
    in_memory = normalize_record(normalizer_payloads["records"]["complete"])
    restored = normalize_record(json.loads(json.dumps(normalizer_payloads["records"]["complete"])))

    assert restored == in_memory


def test_a_duplicate_identifier_is_preserved_rather_than_merged(
    normalizer_payloads: dict[str, Any],
) -> None:
    """Two readings of one ad id are two observations.

    A provider may serve the same ad twice in one walk with revised copy, and
    that difference is the interesting part. Merging here would decide, before
    anything downstream has seen either copy, that the two were the same
    observation.
    """
    result = normalize_payload(normalizer_payloads["payloads"]["duplicate_identifier"])

    assert result.errors == ()
    assert [record.external_ad_id for record in result.records] == [
        "mock-ad-000441",
        "mock-ad-000441",
    ]
    assert result.records[0].primary_text != result.records[1].primary_text


def test_the_whole_corpus_the_mock_provider_serves_is_readable(
    mock_pages: dict[str, Any],
) -> None:
    """The corpus a real provider serves must survive the normalizer intact.

    Not a re-listing of `test_mock_provider.py`: that asserts the provider
    serves it, this asserts the *reading* is faithful, field by field, so a
    change to the mapping that made the records wrong would be caught here even
    though every count and every ad id still lined up.
    """
    for page in mock_pages.values():
        for batch in page.batches:
            result = normalize_payload(batch.raw)
            assert result.errors == (), result.errors
            assert len(result.records) == len(batch.raw.get("ads", []))
            for raw, record in zip(batch.raw["ads"], result.records, strict=True):
                assert record.external_ad_id == raw["ad_id"]
                assert record.page_id == raw.get("page_id")
                assert record.page_name == raw.get("page_name")
                assert record.ad_status == raw.get("status")
                assert list(record.platforms) == list(raw.get("platforms", []))
                assert list(record.countries) == list(raw.get("targeted_countries", []))
                body = raw["ad_creative_bodies"][0]
                assert record.primary_text == body.get("body")
                assert record.headline == body.get("title")
                assert record.description == body.get("link_description")
                assert [asset.provider_key for asset in record.media] == [
                    entry["key"] for entry in body.get("media") or []
                ]

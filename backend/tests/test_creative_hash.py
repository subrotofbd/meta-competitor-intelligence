"""The frozen S2.2 `creative_hash` v1 contract.

`creative_hash` is the creative half of the S2.2 split: it answers *do these two
ads use the same assets?*, which `content_hash` v1 cannot because it hashes
words and assets together.

The dominant fact about this module is a **limitation**, and these tests exist to
keep it visible rather than let it be forgotten: **v1 hashes provider media keys,
not media bytes.** `AGENTS.md` section 12 forbids media byte downloads in S0-S3,
so two ads re-served under a rotated provider key look different to this digest.
A creative duplicate is a *hint*, not proof. S2.4's byte hash becomes a v2 with a
different version literal; it never reinterprets a stored v1 value.

Hermetic, like the other hash tests.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest

from app.providers.data.models import AdFormat, MediaRef, RawAdRecord
from app.services.creative_hash import CREATIVE_HASH_VERSION, creative_hash_v1
from app.services.hashing import frame_collection

pytestmark = pytest.mark.unit


def _record(**overrides: Any) -> RawAdRecord:
    """One record, so a test changes exactly the field it names."""
    fields: dict[str, Any] = {
        "external_ad_id": "ad-001",
        "page_id": "100000000000001",
        "page_name": "Acme India",
        "platforms": ("facebook",),
        "countries": ("IN",),
        "ad_status": "active",
        "meta_delivery_start": datetime(2026, 1, 1, tzinfo=UTC),
        "primary_text": "Buy now",
        "headline": "Great offer",
        "description": "Limited time",
        "cta": "SHOP_NOW",
        "destination_url": "https://example.invalid/offer",
        "display_format": AdFormat.IMAGE,
        "media": (MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2")),
    }
    fields.update(overrides)
    return RawAdRecord(**fields)


# ============================================================
# Shape of the output
# ============================================================


def test_the_digest_is_a_lowercase_64_character_sha256() -> None:
    result = creative_hash_v1(_record())

    assert len(result) == 64
    assert result == result.lower()
    assert set(result) <= set("0123456789abcdef")


def test_the_digest_is_deterministic() -> None:
    assert creative_hash_v1(_record()) == creative_hash_v1(_record())


def test_two_different_media_sets_hash_differently() -> None:
    """The negative control every exclusion test below depends on."""
    assert creative_hash_v1(_record(media=(MediaRef(provider_key="a"),))) != creative_hash_v1(
        _record(media=(MediaRef(provider_key="b"),))
    )


# ============================================================
# The version literal
# ============================================================


def test_the_version_literal_is_the_s22_creative_value() -> None:
    """Spelled out, and distinct from the copy and content literals.

    S2.4's media-byte hash must become a *different* version rather than a
    reinterpretation of this one. This test is the first line of that guard.
    """
    from app.services.content_hash import CONTENT_HASH_VERSION
    from app.services.copy_hash import COPY_HASH_VERSION

    assert CREATIVE_HASH_VERSION == "s2.2-creative-v1"
    assert len({CONTENT_HASH_VERSION, COPY_HASH_VERSION, CREATIVE_HASH_VERSION}) == 3


def test_the_version_leads_the_hashed_input() -> None:
    """Recomputed independently, so this proves the version is really hashed."""
    record = _record()
    expected = hashlib.sha256(
        "\x1f".join(
            [
                CREATIVE_HASH_VERSION,
                frame_collection(sorted(asset.provider_key for asset in record.media)),
            ]
        ).encode("utf-8")
    ).hexdigest()

    assert creative_hash_v1(record) == expected


# ============================================================
# Only the provider key is hashed
# ============================================================


def test_nothing_but_the_media_key_is_hashed() -> None:
    """Every other attribute of a `MediaRef` is excluded.

    A `width`, a `mime` or a `source_url` changing is the provider correcting its
    own metadata, not the ad changing its creative. Including them would rewrite
    history the moment a feed corrected a dimension.
    """
    plain = creative_hash_v1(_record(media=(MediaRef(provider_key="img-1"),)))
    annotated = creative_hash_v1(
        _record(
            media=(
                MediaRef(
                    provider_key="img-1",
                    source_url="https://example.invalid/one.png",
                    mime="image/png",
                    width=1080,
                    height=1080,
                ),
            )
        )
    )

    assert plain == annotated


def test_only_the_media_is_hashed_and_not_the_copy() -> None:
    """The other half of the split, asserted from the creative side too."""
    changed = _record(primary_text="Different words", headline="Different headline")

    assert creative_hash_v1(changed) == creative_hash_v1(_record())


@pytest.mark.parametrize(
    "field",
    [
        "external_ad_id",
        "ad_status",
        "meta_delivery_start",
        "page_id",
        "page_name",
        "countries",
        "display_format",
        "platforms",
        "provider_metadata",
        "primary_text",
        "headline",
        "description",
        "cta",
        "destination_url",
    ],
)
def test_changing_a_non_creative_field_does_not_move_the_digest(field: str) -> None:
    """Delivery, targeting, attribution and copy are all not creative."""
    replacements: dict[str, Any] = {
        "external_ad_id": "ad-999",
        "ad_status": "inactive",
        "meta_delivery_start": datetime(2019, 6, 1, tzinfo=UTC),
        "page_id": "100000000000099",
        "page_name": "Acme Renamed",
        "countries": ("US",),
        "display_format": AdFormat.VIDEO,
        "platforms": ("instagram",),
        "provider_metadata": {"n": 7},
        "primary_text": "Different",
        "headline": "Different",
        "description": "Different",
        "cta": "LEARN_MORE",
        "destination_url": "https://example.invalid/other",
    }

    assert creative_hash_v1(_record(**{field: replacements[field]})) == creative_hash_v1(_record())


def test_an_unmodelled_provider_key_is_still_a_provider_key() -> None:
    """A shape this product does not model is still identified by its key.

    `AdFormat` maps an unrecognised shape to one frozen token so widening the enum
    cannot move a stored digest; the same reasoning applies here in the other
    direction. The key is opaque text and is hashed as given -- it is never
    interpreted, looked up in a vocabulary, or refused because we do not
    recognise it.
    """
    unmodelled = creative_hash_v1(_record(media=(MediaRef(provider_key="STORY_asset-9"),)))

    assert unmodelled == creative_hash_v1(_record(media=(MediaRef(provider_key="STORY_asset-9"),)))
    assert unmodelled != creative_hash_v1(_record(media=(MediaRef(provider_key="img-1"),)))


# ============================================================
# Sorting is for the representation only
# ============================================================


def test_media_order_does_not_change_the_digest() -> None:
    """The provider reorders its output -- `REPOSITORY_RESEARCH.md:47` -- and a
    shuffle is not a creative change.

    Without this, every walk returning the same assets in a different order would
    mint a false "this ad changed".
    """
    forward = (MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2"))
    backward = (MediaRef(provider_key="img-2"), MediaRef(provider_key="img-1"))

    assert creative_hash_v1(_record(media=forward)) == creative_hash_v1(_record(media=backward))


def test_hashing_does_not_reorder_the_record() -> None:
    """Sorting happens for the hash's own representation only.

    The stored `normalized` JSON is the evidence and keeps provider order. If
    hashing reordered the record, the stored evidence would stop matching what the
    provider sent.
    """
    shuffled = _record(media=(MediaRef(provider_key="img-2"), MediaRef(provider_key="img-1")))

    creative_hash_v1(shuffled)

    assert [asset.provider_key for asset in shuffled.media] == ["img-2", "img-1"]


# ============================================================
# Membership and multiplicity
# ============================================================


def test_adding_a_media_key_changes_the_digest() -> None:
    """Sorting must not become deduplication.

    A creative that gained an image is a different creative, and a digest that
    could not tell the difference would make a real change invisible.
    """
    assert creative_hash_v1(_record(media=(MediaRef(provider_key="img-1"),))) != creative_hash_v1(
        _record(media=(MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2")))
    )


def test_removing_a_media_key_changes_the_digest() -> None:
    """The other direction, which the collection count makes possible at all."""
    assert creative_hash_v1(
        _record(media=(MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2")))
    ) != creative_hash_v1(_record(media=(MediaRef(provider_key="img-1"),)))


def test_a_repeated_provider_key_remains_two_assets() -> None:
    """Duplicates are not collapsed.

    The provider sent two entries with the same key; that is what was observed,
    and a record's own duplication is a fact about the record. Sorting orders the
    collection -- it does not deduplicate it, and a `set()` here would make that
    duplication invisible.
    """
    once = creative_hash_v1(_record(media=(MediaRef(provider_key="img-1"),)))
    twice = creative_hash_v1(
        _record(media=(MediaRef(provider_key="img-1"), MediaRef(provider_key="img-1")))
    )

    assert once != twice


def test_an_empty_media_collection_is_its_own_digest() -> None:
    """An ad reported with no asset is a real observation, not an error.

    It must hash to something well defined -- and to something different from an
    ad that has assets, or "no creative" and "a creative" would be
    indistinguishable.
    """
    empty = creative_hash_v1(_record(media=()))

    assert empty != creative_hash_v1(_record())
    assert len(empty) == 64


def test_an_empty_media_collection_is_not_a_populated_one() -> None:
    """`()` and a collection holding something are different facts.

    `RawAdRecord.media` defaults to `()`, so an ad can legitimately arrive with no
    asset at all. That has to hash to its own value rather than to something that
    a populated collection could also produce.

    An *empty string* key is not used as the contrast, because `MediaRef`
    requires `min_length=1` -- the contract already refuses it, so the framing
    never has to represent it. The framing distinguishes empty collections from
    one-element collections holding `""` regardless, and that is covered in
    `test_hashing.py`.
    """
    assert creative_hash_v1(_record(media=())) != creative_hash_v1(_record())
    assert frame_collection([]) == "[0]"
    assert frame_collection([]) != frame_collection([""])


# ============================================================
# This is an identity, not a content digest
# ============================================================


def test_a_rotated_provider_key_changes_the_digest_even_for_identical_bytes() -> None:
    """The limitation, stated as a test so it cannot be quietly forgotten.

    v1 hashes the key, not the bytes, because `AGENTS.md` section 12 forbids media
    byte downloads in S0-S3. So the same image re-served under a new key is a
    *different* creative as far as this digest is concerned, and a creative
    duplicate report built on v1 is a hint rather than proof.

    When S2.4 hashes bytes this becomes a v2 with a different version literal.
    No stored `s2.2-creative-v1` value is reinterpreted, and this test is what
    will be left behind to say so.
    """
    rotated = creative_hash_v1(_record(media=(MediaRef(provider_key="rotated-key"),)))

    assert rotated != creative_hash_v1(_record(media=(MediaRef(provider_key="img-1"),)))


def test_the_record_is_not_mutated_by_hashing() -> None:
    record = _record()
    before = record.model_dump(mode="json")

    creative_hash_v1(record)

    assert record.model_dump(mode="json") == before

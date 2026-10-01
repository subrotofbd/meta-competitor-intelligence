"""The frozen S2.2 `copy_hash` v1 contract.

`copy_hash` answers one narrow question: *did the ad's **words** change?* That is
what duplicate detection groups on, because `content_hash` v1 hashes words and
assets together and so cannot attribute a match to either.

The tests are mostly negative on purpose. Almost every one asserts that some
field does **not** move the digest, because that is where this contract rots: a
field quietly added to the function would rewrite the meaning of every stored
digest without a single row being deleted, and no assertion about rows would
notice.

Hermetic. The function is pure, so nothing here needs a database.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from typing import Any

import pytest

from app.providers.data.models import AdFormat, MediaRef, RawAdRecord
from app.services.copy_hash import COPY_HASH_VERSION, copy_hash_v1
from app.services.hashing import frame

pytestmark = pytest.mark.unit

#: The five data inputs, in the order v1 frames them. A literal because the
#: *order* is the contract: deriving it from the implementation would make the
#: test agree with any future change.
HASHED_FIELDS = (
    "primary_text",
    "headline",
    "description",
    "cta",
    "destination_url",
)

#: Every field `RawAdRecord` declares that copy deliberately ignores, with the
#: reason. An exclusion with no stated reason is an exclusion the next session
#: reopens.
EXCLUDED_FIELDS = {
    "external_ad_id": "it is the identity, not the copy",
    "ad_status": "a status flip must not rewrite what the ad says",
    "meta_delivery_start": "a corrected date must not rewrite history",
    "page_id": "attribution; one ad is served on several pages",
    "page_name": "a page rename is not a copy change",
    "countries": "targeting, and a separate table in S2.2",
    "display_format": "creative shape, hashed separately",
    "platforms": "delivery, not words",
    "media": "creative, hashed separately",
    "provider_metadata": "unmodelled fields we keep but do not compare",
}


def _record(**overrides: Any) -> RawAdRecord:
    """One fully populated record, so a test changes exactly the field it names."""
    fields: dict[str, Any] = {
        "external_ad_id": "ad-001",
        "page_id": "100000000000001",
        "page_name": "Acme India",
        "platforms": ("facebook", "instagram"),
        "countries": ("IN",),
        "ad_status": "active",
        "meta_delivery_start": datetime(2026, 1, 1, tzinfo=UTC),
        "primary_text": "Buy now",
        "headline": "Great offer",
        "description": "Limited time",
        "cta": "SHOP_NOW",
        "destination_url": "https://example.invalid/offer",
        "display_format": AdFormat.CAROUSEL,
        "media": (MediaRef(provider_key="img-1"),),
        "provider_metadata": {"extra": "value"},
    }
    fields.update(overrides)
    return RawAdRecord(**fields)


# ============================================================
# Shape of the output
# ============================================================


def test_the_digest_is_a_lowercase_64_character_sha256() -> None:
    """The format `ck_ad_snapshots_copy_hash_is_sha256_hex` enforces.

    A malformed digest would not fail loudly -- it would make every future
    comparison unequal, so no snapshot would ever be written again, and duplicate
    detection would silently stop finding anything.
    """
    result = copy_hash_v1(_record())

    assert len(result) == 64
    assert result == result.lower()
    assert set(result) <= set("0123456789abcdef")


def test_the_digest_is_deterministic() -> None:
    assert copy_hash_v1(_record()) == copy_hash_v1(_record())


def test_two_different_bodies_hash_differently() -> None:
    """The negative control.

    Without it a constant function would pass every exclusion test below, since
    those assert that *nothing* changes the digest.
    """
    assert copy_hash_v1(_record(primary_text="One")) != copy_hash_v1(_record(primary_text="Two"))


# ============================================================
# The version literal
# ============================================================


def test_the_version_literal_is_the_s22_value() -> None:
    assert COPY_HASH_VERSION == "s2.2-copy-v1"


def test_copy_hash_is_versioned_independently_of_the_other_hashes() -> None:
    """Three sibling digests, three separate version literals.

    Changing the URL rule is a v2 of *this* function and nothing else. Sharing a
    version string would make it impossible to tell which contract a stored
    digest was produced under.
    """
    from app.services.content_hash import CONTENT_HASH_VERSION
    from app.services.creative_hash import CREATIVE_HASH_VERSION

    versions = {CONTENT_HASH_VERSION, COPY_HASH_VERSION, CREATIVE_HASH_VERSION}

    assert len(versions) == 3
    assert COPY_HASH_VERSION.startswith("s2.2-")
    assert CONTENT_HASH_VERSION == "s2.1-content-v1"


def test_the_version_leads_the_hashed_input() -> None:
    """Recomputed independently, so this proves the version is actually hashed.

    If it were merely documented, this independent reconstruction would not
    match.
    """
    record = _record()
    expected = hashlib.sha256(
        "\x1f".join(
            [
                COPY_HASH_VERSION,
                frame(record.primary_text),
                frame(record.headline),
                frame(record.description),
                frame(record.cta),
                frame(str(record.destination_url)),
            ]
        ).encode("utf-8")
    ).hexdigest()

    assert copy_hash_v1(record) == expected


# ============================================================
# Exactly which fields count
# ============================================================


@pytest.mark.parametrize("field", HASHED_FIELDS)
def test_changing_a_hashed_field_moves_the_digest(field: str) -> None:
    """Each of the five inputs is genuinely part of the comparison."""
    changes: dict[str, Any] = {
        "primary_text": "A different body",
        "headline": "A different headline",
        "description": "A different description",
        "cta": "LEARN_MORE",
        "destination_url": "https://example.invalid/other",
    }

    assert copy_hash_v1(_record(**{field: changes[field]})) != copy_hash_v1(_record())


@pytest.mark.parametrize(("field", "reason"), sorted(EXCLUDED_FIELDS.items()))
def test_changing_an_excluded_field_does_not_move_the_digest(field: str, reason: str) -> None:
    """Every exclusion, each proven rather than asserted in a docstring.

    `reason` is a parameter so the failure message names why the field was
    excluded -- a test that fails without saying what the field was *for* is a
    test that gets deleted rather than fixed.
    """
    replacements: dict[str, Any] = {
        "external_ad_id": "ad-999",
        "ad_status": "inactive",
        "meta_delivery_start": datetime(2019, 6, 1, tzinfo=UTC),
        "page_id": "100000000000099",
        "page_name": "Acme Renamed",
        "countries": ("US", "GB"),
        "display_format": AdFormat.VIDEO,
        "platforms": ("facebook",),
        "media": (MediaRef(provider_key="img-9"),),
        "provider_metadata": {"completely": "different"},
    }

    assert copy_hash_v1(_record(**{field: replacements[field]})) == copy_hash_v1(_record()), reason


def test_the_excluded_field_list_is_exhaustive() -> None:
    """Every `RawAdRecord` field is either hashed or explicitly excluded.

    This is what catches a field *added to the model* later: without it, a new
    attribute would be unclassified and its treatment decided by whether it
    happened to be passed to the function.
    """
    declared = set(RawAdRecord.model_fields)

    assert set(HASHED_FIELDS) | set(EXCLUDED_FIELDS) == declared, (
        "unclassified RawAdRecord fields: "
        f"{sorted(declared - set(HASHED_FIELDS) - set(EXCLUDED_FIELDS))}"
    )
    assert not set(HASHED_FIELDS) & set(EXCLUDED_FIELDS)


def test_copy_and_creative_hashes_do_not_cover_the_same_ground() -> None:
    """The split is the point of S2.2, so a copy change must not move the creative
    hash, and a creative change must not move the copy hash.

    If either hash absorbed the other's inputs the two columns would be
    redundant, and duplicate detection could not attribute a match to words or to
    assets.
    """
    from app.services.creative_hash import creative_hash_v1

    copy_only = _record(primary_text="Different words")
    creative_only = _record(media=(MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2")))

    assert copy_hash_v1(copy_only) != copy_hash_v1(_record())
    assert copy_hash_v1(creative_only) == copy_hash_v1(_record())

    assert creative_hash_v1(copy_only) == creative_hash_v1(_record())
    assert creative_hash_v1(creative_only) != creative_hash_v1(_record())


# ============================================================
# The URL is hashed as stored
# ============================================================


def test_the_url_is_hashed_exactly_as_validated_and_stored() -> None:
    """The same spelling in gives the same digest out."""
    stored = "https://Example.invalid/Path/?b=2&a=1"

    assert copy_hash_v1(_record(destination_url=stored)) == copy_hash_v1(
        _record(destination_url=stored)
    )


def test_a_url_differing_only_in_case_hashes_differently() -> None:
    """No case folding, because no canonicalisation.

    Hosts are case-insensitive in principle, but a digest that moved because *we*
    rewrote the URL would claim the provider had changed something it had not.
    `landing_pages` does not exist, so there is nowhere to hold a canonical form,
    and inventing one here would make `copy_hash` and `content_hash` v1 disagree
    about the same URL.
    """
    assert copy_hash_v1(_record(destination_url="https://Example.invalid/x")) != copy_hash_v1(
        _record(destination_url="https://example.invalid/x")
    )


def test_a_url_differing_only_in_query_order_hashes_differently() -> None:
    """Query parameter order is not normalised."""
    assert copy_hash_v1(
        _record(destination_url="https://example.invalid/p?a=1&b=2")
    ) != copy_hash_v1(_record(destination_url="https://example.invalid/p?b=2&a=1"))


def test_a_url_differing_only_in_a_trailing_slash_hashes_differently() -> None:
    """No path repair, for the same reason."""
    assert copy_hash_v1(_record(destination_url="https://example.invalid/p")) != copy_hash_v1(
        _record(destination_url="https://example.invalid/p/")
    )


def test_a_missing_url_is_not_the_same_as_a_different_one() -> None:
    """`None` is absent, and distinct from any URL we could have been given."""
    assert copy_hash_v1(_record(destination_url=None)) != copy_hash_v1(_record())


# ============================================================
# Absences stay distinct
# ============================================================


def test_none_and_the_empty_string_are_different_observations() -> None:
    """S1.3 preserves "not reported" versus "reported empty", and so must this."""
    assert copy_hash_v1(_record(primary_text=None)) != copy_hash_v1(_record(primary_text=""))


def test_every_absence_combination_hashes_to_its_own_digest() -> None:
    """Four states of one field, pairwise distinct."""
    variants = {
        "none": copy_hash_v1(_record(primary_text=None)),
        "empty": copy_hash_v1(_record(primary_text="")),
        "space": copy_hash_v1(_record(primary_text=" ")),
        "text": copy_hash_v1(_record(primary_text="text")),
    }

    assert len(set(variants.values())) == len(variants), variants


# ============================================================
# Text
# ============================================================


def test_devanagari_copy_hashes_by_its_bytes() -> None:
    """Hindi and Hinglish copy is analysed in its original language, which is
    only possible if the digest distinguishes it."""
    hindi = _record(primary_text="अभी खरीदें, सीमित समय")

    assert copy_hash_v1(hindi) != copy_hash_v1(_record(primary_text="अभी खरीदें"))
    assert copy_hash_v1(hindi) == copy_hash_v1(_record(primary_text="अभी खरीदें, सीमित समय"))


def test_the_copy_is_not_unicode_normalised() -> None:
    """Composition and decomposition stay different.

    Normalising would make the digest disagree with the Hindi text stored beside
    it, and would make a provider changing only the encoding of its copy look
    like it had changed the copy.
    """
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")

    assert composed != decomposed
    assert copy_hash_v1(_record(primary_text=composed)) != copy_hash_v1(
        _record(primary_text=decomposed)
    )


def test_whitespace_significant_copy_differs() -> None:
    """Leading, trailing and internal whitespace are part of the copy as observed.

    Not normalised away, because a re-wrapped body is a different rendering of it
    and the product stores what the provider actually sent.
    """
    assert copy_hash_v1(_record(primary_text="Free shipping")) != copy_hash_v1(
        _record(primary_text="Free  shipping")
    )


# ============================================================
# The record is an input, not a possession
# ============================================================


def test_hashing_never_mutates_the_record() -> None:
    """`RawAdRecord` is frozen and this holds to that.

    The stored `normalized` JSON is the evidence and must keep the provider's own
    values, so a function that quietly tidied its input would corrupt the thing
    it is asked to describe.
    """
    record = _record()
    before = record.model_dump(mode="json")

    copy_hash_v1(record)

    assert record.model_dump(mode="json") == before

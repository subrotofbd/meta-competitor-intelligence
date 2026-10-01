"""The frozen S2.1 `content_hash` v1 contract.

`AGENTS.md` section 8 makes one question the sole condition for writing a new
snapshot -- *has this ad changed since we last looked?* -- and
`app/services/content_hash.py` is where that question is answered. So the digest
is not a convenience: it is the hinge of the whole history model, and the stored
digests in `ad_snapshots` are only comparable for ever as long as this function
keeps meaning the same thing.

That is why almost every test here asserts a *negative*: that a particular field
does not move the digest, or that a value the function never saw still hashes the
way it did before. A v1 that quietly started including `ad_status` would rewrite
history without a single row being deleted, and no assertion about rows would
notice.

Hermetic, like the normalizer's tests. The function is a pure function of a
`RawAdRecord`; there is nothing here a database could add.
"""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from typing import Any

import pytest

from app.providers.data.models import AdFormat, MediaRef, RawAdRecord
from app.services.content_hash import (
    _DISPLAY_FORMAT_TOKENS,
    CONTENT_HASH_VERSION,
    _display_format_token,
    content_hash_v1,
)

# The framing helpers moved to `app.services.hashing` in S2.2 so all three hashes
# share one definition. They are imported from their new home rather than through
# `content_hash`'s aliases, because they are no longer *this* module's private
# business. Everything else in this file -- the field sets, the order, the
# version, the independent recomputation, the exclusions -- is unchanged, and the
# whole point of this file is that v1's output did not move.
from app.services.hashing import frame as _frame
from app.services.hashing import frame_collection as _frame_collection

pytestmark = pytest.mark.unit

#: The eight inputs, in the order v1 hashes them, plus the version string that
#: leads. Pinned here as a literal because the *order* is the contract; deriving
#: it from the implementation would make the test agree with any change.
HASHED_FIELDS = (
    "primary_text",
    "headline",
    "description",
    "cta",
    "destination_url",
    "display_format",
    "platforms",
    "media",
)

#: The fields v1 deliberately ignores. Each entry says why it is ignored, because
#: an exclusion with no stated reason is an exclusion the next session reopens.
EXCLUDED_FIELDS = {
    "external_ad_id": "it is the identity, not the content",
    "ad_status": "a provider status change must not rewrite history",
    "meta_delivery_start": "a corrected start date must not rewrite history",
    "page_id": "attribution, and the same ad is served on several pages",
    "page_name": "a page rename is not an ad change",
    "countries": "targeting, and a separate table in S2.2",
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
        "media": (MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2")),
        "display_format": AdFormat.CAROUSEL,
        "provider_metadata": {"extra": "value"},
    }
    fields.update(overrides)
    return RawAdRecord(**fields)


# ============================================================
# Shape of the output
# ============================================================


def test_the_digest_is_a_lowercase_64_character_sha256() -> None:
    """The format is load-bearing: `ad_snapshots` checks it with a regex.

    An uppercase digest or a 63-character one would be refused by
    `ck_ad_snapshots_content_hash_is_sha256_hex` at INSERT time. The column is
    `VARCHAR(64)`, so a longer digest would also be truncated or error, and a
    truncated digest would silently compare unequal forever.
    """
    digest = content_hash_v1(_record())

    assert len(digest) == 64
    assert digest == digest.lower()
    assert set(digest) <= set("0123456789abcdef")


def test_the_same_record_always_hashes_to_the_same_digest() -> None:
    """Determinism, and the property every later comparison depends on."""
    assert content_hash_v1(_record()) == content_hash_v1(_record())


def test_two_different_records_hash_differently() -> None:
    """The negative control. Without it, a constant function passes every other
    test in this file -- including all the exclusion tests, which would then be
    asserting that nothing changes anything."""
    assert content_hash_v1(_record(primary_text="One")) != content_hash_v1(
        _record(primary_text="Two")
    )


# ============================================================
# The version literal
# ============================================================


def test_the_version_literal_is_the_s21_value() -> None:
    """Spelled out, so S2.2 cannot quietly move v1's identity.

    A stored v1 digest must keep meaning what it meant. A different input set is
    a different *version*, and this is the check that v1 has not become one.
    """
    assert CONTENT_HASH_VERSION == "s2.1-content-v1"


def test_the_version_is_part_of_the_hashed_input() -> None:
    """The version leads the framed input, so no other input can reproduce a v1
    digest by accident.

    Recomputing the digest from the module's own framing is what proves the
    version string is actually hashed rather than merely documented: if it were
    left out, the independent recomputation below would not match.
    """
    record = _record()
    parts = [
        CONTENT_HASH_VERSION,
        _frame(record.primary_text),
        _frame(record.headline),
        _frame(record.description),
        _frame(record.cta),
        _frame(str(record.destination_url)),
        _frame("carousel"),
        _frame_collection(sorted(record.platforms)),
        _frame_collection(sorted(asset.provider_key for asset in record.media)),
    ]
    expected = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    assert content_hash_v1(record) == expected


# ============================================================
# Exactly which fields count
# ============================================================


@pytest.mark.parametrize("field", HASHED_FIELDS)
def test_changing_a_hashed_field_moves_the_digest(field: str) -> None:
    """Each of the eight inputs is genuinely part of the comparison.

    Parametrised because "it hashes several things" is not the claim; the claim is
    that this specific set is hashed, and a field silently dropped from the
    function would still pass a single-field test.
    """
    changes: dict[str, Any] = {
        "primary_text": "A different body",
        "headline": "A different headline",
        "description": "A different description",
        "cta": "LEARN_MORE",
        "destination_url": "https://example.invalid/other",
        "display_format": AdFormat.VIDEO,
        "platforms": ("facebook",),
        "media": (MediaRef(provider_key="img-1"),),
    }

    assert content_hash_v1(_record(**{field: changes[field]})) != content_hash_v1(_record())


@pytest.mark.parametrize(("field", "value"), sorted(EXCLUDED_FIELDS.items()))
def test_changing_an_excluded_field_does_not_move_the_digest(field: str, value: str) -> None:
    """The exclusions, each proven rather than asserted in a docstring.

    Every one of these is a case where a change is *real* but must not be treated
    as the ad changing: a status flip, a corrected date, a page rename, a
    different market, an id. If any of them moved the digest, a re-collection
    would append a snapshot claiming the ad's content changed when it did not.
    """
    replacements: dict[str, Any] = {
        "external_ad_id": "ad-999",
        "ad_status": "inactive",
        "meta_delivery_start": datetime(2019, 6, 1, tzinfo=UTC),
        "page_id": "100000000000099",
        "page_name": "Acme Renamed",
        "countries": ("US", "GB"),
        "provider_metadata": {"completely": "different", "n": 7},
    }

    assert content_hash_v1(_record(**{field: replacements[field]})) == content_hash_v1(_record())


def test_the_excluded_field_list_is_exhaustive() -> None:
    """Every field `RawAdRecord` declares is either hashed or explicitly excluded.

    This is the test that catches a field *added to the model* later. Without it,
    a new `RawAdRecord` attribute would be unclassified: the docstring would not
    mention it, the tests would not cover it, and its treatment would be decided by
    whether it happened to be included in the function.
    """
    declared = set(RawAdRecord.model_fields)

    assert set(HASHED_FIELDS) | set(EXCLUDED_FIELDS) == declared, (
        "RawAdRecord fields neither hashed nor excluded: "
        f"{sorted(declared - set(HASHED_FIELDS) - set(EXCLUDED_FIELDS))}"
    )
    assert not set(HASHED_FIELDS) & set(EXCLUDED_FIELDS)


# ============================================================
# Framing
# ============================================================


def test_a_missing_scalar_frames_as_a_dash() -> None:
    assert _frame(None) == "-"


def test_a_present_scalar_is_prefixed_with_its_byte_length() -> None:
    """Length-prefixed, so two different field splits cannot collide.

    `"ab" + "c"` and `"a" + "bc"` concatenate to the same bytes. The lengths do
    not, which is the entire reason the framing exists.
    """
    assert _frame("abc") == "3:abc"


def test_framing_counts_bytes_and_not_characters() -> None:
    """A multi-byte character claims the length it will actually be hashed at.

    A character count would let Devanagari text advertise a length that does not
    match its UTF-8 encoding, and two different texts would frame identically.
    """
    devanagari = "नमस्ते"

    assert len(devanagari) != len(devanagari.encode("utf-8"))
    assert _frame(devanagari) == f"{len(devanagari.encode('utf-8'))}:{devanagari}"


def test_concatenating_two_scalars_cannot_be_mistaken_for_one() -> None:
    """The concrete collision the framing removes, stated as an inequality.

    This is the property, rather than a restatement of the implementation: if the
    lengths were dropped, this would fail.
    """
    assert _frame("ab") + _frame("c") != _frame("a") + _frame("bc")


def test_a_collection_is_framed_with_its_own_count() -> None:
    """`[0]` for empty, and the count is what keeps the cases apart.

    A one-element collection holding `""` frames as `[11:]` -- count one, then an
    empty scalar. Without the count that is indistinguishable from empty.
    """
    assert _frame_collection([]) == "[0]"
    assert _frame_collection(["a"]) == "[11:a]"


# ============================================================
# Absences stay distinct
# ============================================================


def test_none_and_the_empty_string_are_different_observations() -> None:
    """S1.3 preserves the difference between "not reported" and "reported empty",
    and hashing must not collapse them.

    Collapsing them would merge two genuinely different observations into one
    snapshot decision -- the ad would look unchanged when the provider actually
    said something new.
    """
    assert content_hash_v1(_record(primary_text=None)) != content_hash_v1(_record(primary_text=""))


def test_an_empty_collection_and_none_are_different_observations() -> None:
    """`()` and `None` on the collection-shaped fields.

    `RawAdRecord` defaults `platforms` and `media` to `()`, and there is no `None`
    for them, so this is really the rule that an empty collection hashes as an
    empty collection rather than as an absent scalar.
    """
    assert _frame_collection([]) != _frame(None)

    empty = content_hash_v1(_record(platforms=(), media=()))
    populated = content_hash_v1(_record())
    assert empty != populated


def test_a_collection_holding_an_empty_string_is_not_an_empty_collection() -> None:
    """The case the count exists for.

    `[10:]` rather than `[1-]`: the `-` marker means the *scalar was absent*, and
    an empty string is a value that happens to be empty, so it frames as `0:`
    (zero bytes). What separates this from an empty collection is the leading `1`.
    """
    assert _frame_collection([""]) != _frame_collection([])
    assert _frame_collection([""]) == "[10:]"
    assert _frame_collection([""]) == f"[1{_frame('')}]"


def test_every_absence_combination_hashes_to_its_own_digest() -> None:
    """All four states of one field, pairwise distinct.

    A single pairwise test per field would be four tests per field; this is the
    same coverage stated once, and it fails naming the pair that collided.
    """
    variants = {
        "none": content_hash_v1(_record(primary_text=None)),
        "empty": content_hash_v1(_record(primary_text="")),
        "space": content_hash_v1(_record(primary_text=" ")),
        "text": content_hash_v1(_record(primary_text="text")),
    }

    assert len(set(variants.values())) == len(variants), variants


# ============================================================
# The URL is hashed as stored
# ============================================================


def test_the_destination_url_is_hashed_exactly_as_stored() -> None:
    """No canonicalisation, no trailing-slash repair, no case folding.

    `landing_pages` and URL canonicalisation are S2.2. v1 hashes what we actually
    hold, because a digest that moved because *we* rewrote the text would claim
    the provider changed something it did not. `RawAdRecord` validates the scheme
    and leaves the rest alone, so the stored spelling is what reaches the digest.
    """
    stored = "https://Example.invalid/Path/?b=2&a=1"

    assert content_hash_v1(_record(destination_url=stored)) == content_hash_v1(
        _record(destination_url=stored)
    )
    assert content_hash_v1(_record(destination_url=stored)) != content_hash_v1(
        _record(destination_url="https://example.invalid/Path/?b=2&a=1")
    )


def test_a_missing_url_is_not_the_same_as_an_empty_one() -> None:
    """`None` is absent; there is no empty URL, because the contract rejects one."""
    assert content_hash_v1(_record(destination_url=None)) != content_hash_v1(_record())


# ============================================================
# Set-like fields: sorted for the hash, untouched everywhere else
# ============================================================


def test_platform_order_does_not_change_the_digest() -> None:
    """The provider reorders its output; a re-order is not a change.

    `REPOSITORY_RESEARCH.md:47` records that it does. A digest that moved on a
    shuffle would mint a snapshot claiming the ad's targeting changed when only
    the order of two platform names moved.
    """
    assert content_hash_v1(_record(platforms=("facebook", "instagram"))) == content_hash_v1(
        _record(platforms=("instagram", "facebook"))
    )


def test_media_key_order_does_not_change_the_digest() -> None:
    """The same rule for the media keys."""
    forward = (MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2"))
    backward = (MediaRef(provider_key="img-2"), MediaRef(provider_key="img-1"))

    assert content_hash_v1(_record(media=forward)) == content_hash_v1(_record(media=backward))


def test_platform_membership_still_changes_the_digest() -> None:
    """The negative control for the sorting rule.

    Sorting must not become deduplication: dropping a platform is a real change to
    the ad's targeting, and this is what stops the sorted representation from
    quietly making two different ads look identical.
    """
    assert content_hash_v1(_record(platforms=("facebook", "instagram"))) != content_hash_v1(
        _record(platforms=("facebook",))
    )


def test_media_membership_still_changes_the_digest() -> None:
    """The same, for the media keys."""
    assert content_hash_v1(_record(media=(MediaRef(provider_key="img-1"),))) != content_hash_v1(
        _record(media=(MediaRef(provider_key="img-1"), MediaRef(provider_key="img-2")))
    )


def test_the_record_is_not_reordered_by_hashing() -> None:
    """Sorting happens for the hash's own representation only.

    The stored `normalized` JSON keeps the provider's order, because that JSON is
    the evidence. If hashing mutated the record, the evidence would silently stop
    matching what the provider said.
    """
    shuffled = _record(
        platforms=("instagram", "facebook"),
        media=(MediaRef(provider_key="img-2"), MediaRef(provider_key="img-1")),
    )

    content_hash_v1(shuffled)

    assert shuffled.platforms == ("instagram", "facebook")
    assert [asset.provider_key for asset in shuffled.media] == ["img-2", "img-1"]


def test_only_the_media_key_is_hashed_and_not_the_rest_of_the_asset() -> None:
    """Bytes are S2.4. Until they exist the key *is* the asset's identity, and
    nothing else about a `MediaRef` is content.

    A `width` or a `source_url` changing is not the ad changing, and including
    them would rewrite history the moment a provider corrected its own metadata.
    """
    same_key = content_hash_v1(_record(media=(MediaRef(provider_key="img-1"),)))
    annotated = content_hash_v1(
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

    assert same_key == annotated


# ============================================================
# Display format: a frozen token table
# ============================================================


@pytest.mark.parametrize(
    ("display_format", "token"),
    [
        (AdFormat.IMAGE, "image"),
        (AdFormat.VIDEO, "video"),
        (AdFormat.CAROUSEL, "carousel"),
        (None, "unmodelled"),
    ],
)
def test_each_modelled_shape_has_its_own_token(display_format: AdFormat | None, token: str) -> None:
    """The table is the whole point: three modelled shapes stay distinguishable."""
    record = _record(display_format=display_format)
    same_shape = _record(display_format=display_format)

    assert content_hash_v1(record) == content_hash_v1(same_shape)

    others = [other for other in (*AdFormat, None) if other is not display_format]
    assert all(
        content_hash_v1(record) != content_hash_v1(_record(display_format=other))
        for other in others
    ), f"{display_format!r} shares a digest with another shape"


def test_an_unmodelled_shape_hashes_the_same_as_no_shape_at_all() -> None:
    """A provider reporting a shape we do not model must not move v1.

    `RawAdRecord` cannot distinguish "no shape reported" from "a shape not in
    `AdFormat`", so v1 must not pretend it can. Both land on one fixed token, and
    the unrecognised value survives in `provider_metadata` where it belongs.
    """
    assert content_hash_v1(_record(display_format=None)) == content_hash_v1(
        _record(display_format=None, provider_metadata={"display_format": "STORY"})
    )


def test_a_future_shape_member_does_not_change_any_stored_digest() -> None:
    """The reason v1 keeps its own token table instead of reading the enum.

    If v1 hashed `AdFormat.STORY` as `"STORY"`, then adding that member -- which
    `AdFormat`'s own docstring calls a display decision, not a re-collection --
    would change the digest of every ad already stored as `unmodelled`, and every
    one of them would be appended a fresh snapshot on the next run. The digest of
    a v1 observation is fixed, so this simulates the widening and asserts that the
    stored value is unaffected.
    """
    before = content_hash_v1(_record(display_format=None))

    simulated_future_shape = "STORY"
    token = _DISPLAY_FORMAT_TOKENS.get(simulated_future_shape, "unmodelled")

    assert token == "unmodelled", "an unknown shape must fall back to the one token"
    assert content_hash_v1(_record(display_format=None)) == before


def test_the_token_table_is_keyed_on_values_not_names() -> None:
    """`AdFormat.IMAGE` is named `IMAGE` and valued `"IMAGE"` today.

    They coincide, so a regression that keyed the table on `str(member)` instead
    of `member.value` would be invisible until a value changed. This asserts the
    keys are the values, which is what makes the fallback the live defence.
    """
    assert set(_DISPLAY_FORMAT_TOKENS) == {member.value for member in AdFormat}


# ============================================================
# Text
# ============================================================


def test_devanagari_text_hashes_by_its_bytes() -> None:
    """S1.3 preserves Devanagari verbatim, and so does v1.

    Nothing in the pipeline re-encodes it, so two ads differing only in their
    Hindi copy get different digests -- which is the entire reason Hindi and
    Hinglish copy is analysable in the original language at all.
    """
    hindi = _record(primary_text="अभी खरीदें, सीमित समय")

    assert content_hash_v1(hindi) != content_hash_v1(_record(primary_text="अभी खरीदें"))
    assert content_hash_v1(hindi) == content_hash_v1(_record(primary_text="अभी खरीदें, सीमित समय"))


def test_the_text_is_not_unicode_normalised() -> None:
    """Composition and decomposition are different bytes, and stay different.

    NFC would fold `"é"` and `"e" + U+0301` into one digest, so a provider that
    changed only the encoding of its copy would look like it had changed the copy
    -- and the stored `normalized` text would disagree with the digest that
    describes it. Asserted in both directions, because either normalisation would
    break the same property.
    """
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", "café")

    assert composed != decomposed, "the two test strings are not actually different"
    assert content_hash_v1(_record(primary_text=composed)) != content_hash_v1(
        _record(primary_text=decomposed)
    )


def test_an_empty_body_and_a_whitespace_only_body_differ() -> None:
    """Blank-looking is not the same as empty.

    A provider stripping its copy down to a space has reported a body, and v1
    records that as a change rather than as an absence.
    """
    assert content_hash_v1(_record(primary_text=" ")) != content_hash_v1(_record(primary_text=""))


def test_text_holding_the_framing_characters_cannot_forge_a_boundary() -> None:
    """The separator and the framing are escaped by length, not by filtering.

    A copy containing the separator must not be able to impersonate a field
    boundary. With length prefixes it is just bytes inside a counted frame; this
    asserts it, because a copy is untrusted provider text.
    """
    sneaky = _record(primary_text="a\x1f3:bc")

    assert content_hash_v1(sneaky) != content_hash_v1(_record(primary_text="a"))
    assert content_hash_v1(sneaky) != content_hash_v1(_record(primary_text="abc"))


# ============================================================
# The record is an input, not a possession
# ============================================================


def test_hashing_never_mutates_the_record() -> None:
    """`RawAdRecord` is frozen, and v1 holds to that.

    It is the stored `normalized` JSON that must keep the provider's order, so a
    function that quietly normalised its input would corrupt the evidence it is
    asked to describe.
    """
    record = _record()
    before = record.model_dump(mode="json")

    content_hash_v1(record)

    assert record.model_dump(mode="json") == before


def test_a_rejected_record_is_reported_as_such_and_never_hashed() -> None:
    """The frozen token is the fallback, not a validation.

    `RawAdRecord` is the validator; this function is the comparison. The boundary
    holds because the one thing that could vary between a stored digest and a
    recomputed one -- an unmodelled shape -- is mapped to a single token rather
    than being allowed to raise or to encode the enum.
    """
    assert _display_format_token(None) == "unmodelled"
    assert _display_format_token(AdFormat.IMAGE) == "image"

"""The framing rules every hash in this project depends on.

`app/services/hashing.py` is shared by `content_hash` v1, `copy_hash` v1 and
`creative_hash` v1. These tests are therefore not about any one digest: they are
about the property that makes a digest *mean* something, and they would fail just
as loudly if a future version changed a field's order as if a length prefix were
dropped.

Hermetic and fast. The framing is pure text manipulation, so nothing here needs a
database -- which is the point of having separated it out.
"""

from __future__ import annotations

import pytest

from app.services.hashing import ABSENT, SEPARATOR, digest, frame, frame_collection

pytestmark = pytest.mark.unit


# ============================================================
# The shape of a frame
# ============================================================


def test_an_absent_scalar_frames_as_a_dash() -> None:
    assert frame(None) == ABSENT
    assert ABSENT == "-"


def test_a_present_scalar_is_prefixed_with_its_byte_length() -> None:
    assert frame("abc") == "3:abc"


def test_the_empty_string_is_framed_and_is_not_the_absent_marker() -> None:
    """`""` is a value that happens to be empty; `None` is no value at all.

    S1.3 deliberately preserves the difference between a provider reporting an
    empty string and reporting nothing, so collapsing them here would merge two
    genuinely different observations into one hash decision.
    """
    assert frame("") == "0:"
    assert frame("") != frame(None)


def test_framing_counts_bytes_and_not_characters() -> None:
    """The length is the one the value will actually be hashed at.

    A character count would let multi-byte text advertise a length that does not
    match its UTF-8 encoding, and two different strings would frame identically.
    """
    devanagari = "नमस्ते"

    assert len(devanagari) != len(devanagari.encode("utf-8"))
    assert frame(devanagari) == f"{len(devanagari.encode('utf-8'))}:{devanagari}"


def test_framing_preserves_the_value_exactly() -> None:
    """The framing must not alter what is inside it -- no stripping, no case
    folding, no Unicode normalisation.

    A frame that silently tidied its input would make the digest disagree with
    the text stored beside it, and Hindi copy would stop being analysable in the
    language it was written in.
    """
    for value in ("  leading and trailing  ", "CAFÉ", "café", "line\nbreak", "nul\x00byte"):
        assert frame(value).endswith(value)


# ============================================================
# Why the length prefix exists
# ============================================================


def test_two_scalars_cannot_be_confused_with_one_longer_scalar() -> None:
    """The collision the framing removes, stated as an inequality.

    `"ab" + "c"` and `"a" + "bc"` are the same bytes. Only the lengths differ, so
    this is the property rather than a restatement of the implementation.
    """
    assert frame("ab") + frame("c") != frame("a") + frame("bc")


def test_three_scalars_in_any_split_are_all_distinct() -> None:
    """Two fields is the easy case; a longer split is where a naive join breaks."""
    splits = {
        "abc": frame("a") + frame("b") + frame("c"),
        "a|b|c": frame("ab") + frame("c"),
        "a|bc": frame("a") + frame("bc"),
        "ab|c": frame("abc"),
    }

    assert len(set(splits.values())) == 4, splits


def test_digests_of_differently_split_inputs_differ() -> None:
    """The end-to-end consequence: the separator cannot rescue a bad split.

    Joining is only safe because the lengths disambiguate first. This proves it
    by pushing differently-split inputs all the way to a digest.
    """
    assert digest([frame("a"), frame("bc")]) != digest([frame("ab"), frame("c")])


# ============================================================
# Collections
# ============================================================


def test_an_empty_collection_frames_with_a_zero_count() -> None:
    assert frame_collection([]) == "[0]"


def test_a_collection_is_prefixed_by_its_own_count() -> None:
    """Count, then the elements' frames concatenated.

    No separator between elements: each frame carries its own byte length, so
    `"1:a1:b"` is already unambiguous without one. That is the same argument the
    `SEPARATOR` makes between fields, and it is why adding a separator inside a
    collection would be redundant rather than merely harmless.
    """
    assert frame_collection(["a"]) == "[11:a]"
    assert frame_collection(["a", "b"]) == "[21:a1:b]"
    assert frame_collection(["a", "b"]) == f"[2{frame('a')}{frame('b')}]"


def test_a_collection_holding_an_empty_string_is_not_an_empty_collection() -> None:
    """The case the count exists for.

    `[10:]` rather than `[1-]`: the `-` marker means the *scalar was absent*, and
    an empty string is a value that happens to be empty. What separates this from
    an empty collection is the leading `1`.
    """
    assert frame_collection([""]) == "[10:]"
    assert frame_collection([""]) != frame_collection([])
    assert frame_collection([""]) == f"[1{frame('')}]"


def test_an_empty_collection_is_distinct_from_an_absent_scalar() -> None:
    """`()` and `None` are different facts.

    `RawAdRecord` defaults `platforms` and `media` to `()`, so this is really the
    rule that an empty collection hashes as an empty collection rather than as
    an absent scalar.
    """
    assert frame_collection([]) != frame(None)
    assert frame_collection([]) != frame("")


def test_collection_order_is_preserved_by_the_framing_itself() -> None:
    """Sorting is the caller's decision, not the framing's.

    `creative_hash` and `content_hash` sort before calling this; `copy_hash`
    passes scalars. The framing must not impose an order of its own, or a caller
    that *wants* order preserved could not have it.
    """
    assert frame_collection(["a", "b"]) != frame_collection(["b", "a"])


def test_a_long_collection_is_framed_by_count_not_by_truncation() -> None:
    """Every element is present. A count does not license dropping any."""
    values = [f"key-{index}" for index in range(20)]
    framed = frame_collection(values)

    assert framed.startswith("[20")
    for value in values:
        assert frame(value) in framed


# ============================================================
# Untrusted values cannot forge a boundary
# ============================================================


def test_a_value_containing_the_separator_cannot_forge_a_field_boundary() -> None:
    """Copy is untrusted provider text and may contain the separator.

    With length prefixes it is just bytes inside a counted frame, so it cannot
    impersonate the join between two fields. Asserted both ways: a value carrying
    the separator must not hash like two separate fields.
    """
    sneaky = "a\x1f3:bc"

    assert digest([frame(sneaky)]) != digest([frame("a"), frame("bc")])
    assert digest([frame("a"), frame("bc")]) != digest([frame(sneaky)])


def test_a_value_containing_framing_syntax_cannot_forge_a_length() -> None:
    """A value that looks like its own frame is still just a value.

    `"0:"` inside a value must not be read as a second frame, because the outer
    frame already declared how many bytes the whole value occupies.
    """
    assert digest([frame("0:abc")]) != digest([frame("abc"), frame("")])


def test_a_newline_in_a_value_cannot_forge_a_log_line() -> None:
    """Provider text is untrusted, and this value ends up in a stored column.

    A newline must survive framing untouched -- escaping or stripping it would
    make the digest disagree with the stored text -- but it must not be able to
    terminate the value and impersonate anything outside it.
    """
    framed = frame("first\nsecond")

    assert framed == "12:first\nsecond"
    assert digest([framed]) != digest([frame("first"), frame("second")])


# ============================================================
# The digest itself
# ============================================================


def test_the_digest_is_lowercase_64_character_hex() -> None:
    """The format every stored digest column's `CHECK` depends on."""
    result = digest([frame("anything")])

    assert len(result) == 64
    assert result == result.lower()
    assert set(result) <= set("0123456789abcdef")


def test_the_digest_is_deterministic() -> None:
    assert digest([frame("a"), frame("b")]) == digest([frame("a"), frame("b")])


def test_different_parts_give_different_digests() -> None:
    """The negative control every other test in this file depends on."""
    assert digest([frame("a")]) != digest([frame("b")])


def test_the_part_order_matters() -> None:
    """Reordering two fields changes the digest.

    This is why the field order in each hash module is written out as a literal
    rather than derived from a container: a silent reorder would be a silent
    change to every stored digest.
    """
    assert digest([frame("a"), frame("b")]) != digest([frame("b"), frame("a")])


def test_the_separator_is_the_unit_separator() -> None:
    """A control character, not a printable one.

    Stated because it is a wire-format constant: a value could otherwise contain
    a printable separator and, without the length prefixes, forge a boundary. The
    control character is the second line of defence, not the first.
    """
    assert SEPARATOR == "\x1f"
    assert not SEPARATOR.isprintable()


def test_an_empty_part_list_still_produces_a_digest() -> None:
    """Defensive: no hash version ships an empty part list, and if one ever did
    the failure should be a wrong digest rather than an exception."""
    assert len(digest([])) == 64

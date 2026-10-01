"""Length-prefixed framing: the one place a value becomes hashable bytes.

## Why this is its own module

Three hashes use it -- `content_hash` v1 (S2.1), `copy_hash` v1 and
`creative_hash` v1 (S2.2) -- and the framing is not incidental to any of them.
It is what stops two different field splits from producing the same digest:
`"ab" + "c"` and `"a" + "bc"` are the same bytes, and only the length prefixes
distinguish them. A rule that is load-bearing in three places and is written
three times is a rule that will drift, so it is written once here and imported.

`app/services/content_hash.py` was refactored to import from this module rather
than to keep its own copies. **Its output is byte-for-byte unchanged**, and
`backend/tests/test_content_hash.py` pins the exact v1 digests -- that test is
what makes the refactor safe rather than hopeful.

## The rules, and why each one is here

**Byte lengths, not character counts.** The length is in the bytes that will
actually be hashed. A character count would let Devanagari text advertise a
length that does not match its UTF-8 encoding, and two different strings would
frame identically.

**`-` for absent, not for empty.** `None` and `""` are different observations and
S1.3 deliberately preserves the difference, so collapsing them would merge two
genuinely different things into one hash decision. `-` therefore means only
"there was no value here"; an empty string is a value that happens to be empty
and frames as `0:`.

**A count on every collection.** `[0]` and `[10:]` differ by more than their
contents: the leading `1` is what keeps a one-element collection holding `""`
distinct from an empty one, which the per-element frames alone cannot do.

**A separator, as belt and braces.** The lengths already prevent accidental
concatenation. The separator exists so that no two framed values can ever be
run together even if the framing is changed carelessly later. A field's own
value may contain it -- a copy string is untrusted provider text -- and because
every value is length-prefixed, a value containing the separator is just bytes
inside a counted frame rather than a forged boundary.

**No Unicode normalisation, here or anywhere downstream.** S1.3 preserves
Devanagari verbatim, so normalising would make a digest disagree with the text
actually stored next to it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Final

#: Joins framed values. Every value is already length-prefixed, so this cannot
#: cause a collision on its own; it exists so that no two fields can ever be
#: concatenated by accident.
SEPARATOR: Final = "\x1f"

#: What an absent scalar frames as. Distinct from the empty string on purpose --
#: see the module docstring.
ABSENT: Final = "-"


def frame(value: str | None) -> str:
    """One framed scalar: `-` for absent, `<byte-length>:<value>` otherwise.

    Args:
        value: The text to frame, or `None` when the field was not reported.

    Returns:
        A string that cannot be confused with any other field's frame.
    """
    if value is None:
        return ABSENT
    return f"{len(value.encode('utf-8'))}:{value}"


def frame_collection(values: Sequence[str]) -> str:
    """One framed collection, with its own count.

    The count is what keeps `()` distinct from a one-element collection holding
    an empty string -- and both distinct from an absent scalar, which frames as
    `-`.
    """
    return f"[{len(values)}" + "".join(frame(value) for value in values) + "]"


def digest(parts: Sequence[str]) -> str:
    """The SHA-256 of joined, already-framed parts.

    Split out so that every hash in this package produces its digest identically.
    The version literal is not added here: it is the caller's first framed part,
    which is what keeps a v1 digest from ever being mistaken for a later
    version's digest over identical fields.
    """
    return hashlib.sha256(SEPARATOR.join(parts).encode("utf-8")).hexdigest()

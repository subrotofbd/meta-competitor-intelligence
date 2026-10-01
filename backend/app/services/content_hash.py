"""`content_hash` v1 -- the value S2.1 snapshots are compared by.

## What this is for

One question, asked once per observation: *has this ad changed since the last
time we saw it?* `AGENTS.md` section 8 makes the answer the sole condition for
writing a new snapshot, so this function is the hinge of the whole history
model. Everything else here follows from taking that one question seriously.

## The rules that are not obvious

**It is a pure function of a `RawAdRecord`,** and of nothing else -- not the
clock, not the database, not the stored JSONB. JSONB normalises key order and
whitespace, so hashing the stored form would tie the digest to a serialiser
rather than to the observation.

**It is frozen.** Version `1` is written down and does not change. A different
set of inputs is a different *version*, and comparing across versions is not a
thing this module does. That is what keeps a stored v1 digest meaning the same
thing forever: when S2.2 introduces `copy_hash`/`creative_hash` and S2.4
introduces media-byte hashing, those are v2, and no v1 row is recalculated.

**`display_format` carries a frozen token table rather than reading the enum.**
`AdFormat` is a closed enum whose own docstring says widening it is "a display
decision, not a re-collection". If v1 read the enum directly, a provider
reporting an unmodelled shape today (`None`) would start hashing differently the
moment a future value was added -- rewriting history with no new collection.
Mapping inside v1's own frozen table makes widening the enum incapable of
changing v1's output.

**Set-like fields are sorted *for hashing only*.** `platforms` and media keys
are tuples whose order comes from the provider, and this project has already
recorded that the provider reorders its output
(`REPOSITORY_RESEARCH.md:47`). A digest that moved when the provider shuffled
the same values would mint a snapshot claiming a change that did not happen.
`RawAdRecord` and the stored `normalized` JSON keep provider order; only this
function's own representation is sorted. Nothing stored is ever rewritten to
make a hash agree.

**Absences stay distinct.** `None`, `""` and `()` are three different facts that
S1.3 deliberately preserves, and collapsing any two of them here would merge two
genuinely different observations into one snapshot decision.

**No Unicode normalisation.** S1.3 preserves Devanagari verbatim, and normalising
would make the digest disagree with the text actually stored.

## What is deliberately not here

No copy/creative split, no duplicate detection, no media bytes. Those are S2.2
and S2.4. v1 is self-contained so that nothing in S2.1 depends on them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Final

from app.providers.data.models import AdFormat, RawAdRecord

#: Written into the hashed input, so a v1 digest can never be mistaken for a
#: future version's digest over identical fields.
CONTENT_HASH_VERSION: Final = "s2.1-content-v1"

#: Frozen display-shape tokens. Deliberately *not* derived from `AdFormat` at
#: call time -- see the module docstring. A shape this table does not name maps
#: to the unknown token, which is also where `None` maps: `RawAdRecord` cannot
#: tell "the provider reported no shape" from "it reported a shape we do not
#: model", so v1 must not pretend to.
_DISPLAY_FORMAT_TOKENS: Final[dict[str, str]] = {
    "IMAGE": "image",
    "VIDEO": "video",
    "CAROUSEL": "carousel",
}
_UNMODELLED_DISPLAY_FORMAT: Final = "unmodelled"

#: Joins framed values. Every value is already length-prefixed, so this cannot
#: cause a collision on its own; it exists so that no two fields can ever be
#: concatenated by accident.
_SEPARATOR: Final = "\x1f"


def _frame(value: str | None) -> str:
    """One framed scalar: `-` for absent, `<byte-length>:<value>` otherwise.

    The length is in **bytes**, not characters, because that is what gets
    hashed. A character count would let a multi-byte string claim a length that
    does not match its encoding, which is precisely the ambiguity this framing
    exists to remove.
    """
    if value is None:
        return "-"
    return f"{len(value.encode('utf-8'))}:{value}"


def _frame_collection(values: Sequence[str]) -> str:
    """One framed collection, with its own count.

    The count is what keeps `()` distinct from a one-element collection holding
    an empty string -- and both distinct from an absent scalar, which frames as
    `-`.
    """
    return f"[{len(values)}" + "".join(_frame(value) for value in values) + "]"


def _display_format_token(display_format: AdFormat | None) -> str:
    if display_format is None:
        return _UNMODELLED_DISPLAY_FORMAT
    return _DISPLAY_FORMAT_TOKENS.get(display_format.value, _UNMODELLED_DISPLAY_FORMAT)


def content_hash_v1(record: RawAdRecord) -> str:
    """The S2.1 comparison digest for one normalized record.

    Args:
        record: The provider's report, as S1.3 read it. Never mutated.

    Returns:
        A lowercase 64-character SHA-256 hex digest. Two records share a digest
        if and only if the eight S2.1 content inputs are equal under v1's rules
        -- provider ordering of set-like fields excluded, every other absence
        preserved.

    Fields that are *not* content, and so are not hashed: `external_ad_id` (it
    is the identity, not the content), `ad_status` and `meta_delivery_start`
    (a provider status change or a corrected start date must not rewrite
    history), `page_id`/`page_name` (attribution; a page rename is not an ad
    change), `countries` (targeting, and a separate table in S2.2), and
    `provider_metadata`.
    """
    parts: list[str] = [
        CONTENT_HASH_VERSION,
        # The order of these nine entries *is* the contract, so it is written out
        # rather than derived: a field cannot move by accident if nothing is
        # looping over a container to decide the order.
        _frame(record.primary_text),
        _frame(record.headline),
        _frame(record.description),
        _frame(record.cta),
        # The stored, validated URL. Canonicalisation is S2.2 and `landing_pages`
        # is its table; v1 hashes what we actually hold.
        _frame(None if record.destination_url is None else str(record.destination_url)),
        _frame(_display_format_token(record.display_format)),
        _frame_collection(sorted(record.platforms)),
        # Provider media keys only. Bytes are S2.4; until they exist the key is
        # the asset's identity, which is ARCHITECTURE.md's own documented
        # fallback.
        _frame_collection(sorted(asset.provider_key for asset in record.media)),
    ]
    return hashlib.sha256(_SEPARATOR.join(parts).encode("utf-8")).hexdigest()

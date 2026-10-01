"""`copy_hash` v1 -- the S2.2 digest of an ad's *words*.

## What this is for, and how it differs from `content_hash`

`content_hash` v1 answers "did anything about this ad change?". `copy_hash` v1
answers the narrower question: "did the **text** change?". That narrower question
is what duplicate detection needs -- two different advertisers running identical
words are a finding, and `content_hash` alone cannot surface it, because their
media keys and destination URLs will differ.

So the two hashes are **siblings, not parts**. `content_hash` v1 stays frozen at
`s2.1-content-v1` and does not become a composition of these values; every digest
it has already written keeps meaning exactly what it meant. An earlier
`ARCHITECTURE.md` described `content_hash` as `sha256(copy_hash +
creative_hash + display_format + platforms)`. That line was never built, and
building it now would either rewrite history or force a v2 of a contract that S2.1
froze on purpose. `ARCHITECTURE.md` has been corrected to match what shipped.

## The rules that are not obvious

**The version string is the first framed part**, so a v1 digest can never be
mistaken for a later version's digest over identical fields. `copy_hash` is
versioned **independently** of `content_hash` and of `creative_hash`: a future
change to the URL rule is a v2 of this function and nothing else.

**The URL is hashed exactly as validated and stored.** No canonicalisation, no
lowercasing, no query reordering, no trailing-slash repair. Two decisions made
this explicit. `landing_pages` is not built, so there is nowhere to put a
canonical form; and a digest that moved because *we* rewrote the URL would claim
the provider had changed something it had not. `RawAdRecord` already rejects any
scheme that is not http(s), so the value reaching the digest is a URL we could
legitimately fetch, and that is exactly how much trust the hash places in it.

**Everything that is not words is excluded, deliberately.** `display_format`,
`platforms` and `media` belong to `creative_hash` or to delivery, not to copy. A
provider changing a creative's aspect ratio has not changed what the ad says, and
a duplicate-detection report full of ads that differ only in image size is a
report nobody reads. `ad_status` and `meta_delivery_start` are excluded for the
same reason S2.1 excludes them: a status flip or a corrected date must not
rewrite history. `page_id`/`page_name` are attribution -- one ad is served on
several pages, and a page rename is not a copy change.

**No Unicode normalisation**, exactly as in v1. S1.3 preserves Devanagari
verbatim, so normalising would make the digest disagree with the Hindi text
stored beside it.

**The record is never mutated.** `RawAdRecord` is frozen, and this holds to that:
the stored `normalized` JSON must keep the provider's own values.
"""

from __future__ import annotations

from typing import Final

from app.providers.data.models import RawAdRecord
from app.services.hashing import digest, frame

#: Written into the hashed input, so a v1 digest can never be mistaken for a
#: future version's digest over identical fields. Versioned independently of
#: `content_hash` and `creative_hash` -- changing this contract means a v2 here
#: and nowhere else, and no stored v1 value is ever recomputed.
COPY_HASH_VERSION: Final = "s2.2-copy-v1"


def copy_hash_v1(record: RawAdRecord) -> str:
    """The S2.2 copy digest for one normalized record.

    Args:
        record: The provider's report, as S1.3 read it. Never mutated.

    Returns:
        A lowercase 64-character SHA-256 hex digest. Two records share a digest
        if and only if their five copy inputs are equal under v1's rules, with
        every absence preserved and no field reordered.

    Fields that are *not* copy, and so are not hashed: `external_ad_id` (the
    identity), `ad_status` and `meta_delivery_start` (a status change or a
    corrected date must not rewrite history), `page_id`/`page_name`
    (attribution), `countries` (targeting), `display_format` and `media` (the
    creative, hashed separately), `platforms` (delivery), and
    `provider_metadata`.
    """
    parts: list[str] = [
        COPY_HASH_VERSION,
        # The order of these five entries *is* the contract, so it is written out
        # rather than derived from a container: a field cannot move by accident
        # if nothing is looping over something to decide the order.
        frame(record.primary_text),
        frame(record.headline),
        frame(record.description),
        frame(record.cta),
        # The stored, validated URL, verbatim. No canonicalisation -- see the
        # module docstring for why that is a decision rather than an omission.
        frame(None if record.destination_url is None else str(record.destination_url)),
    ]
    return digest(parts)

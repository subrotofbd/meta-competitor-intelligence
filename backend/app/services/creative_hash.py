"""`creative_hash` v1 -- the S2.2 digest of an ad's *assets*.

## What this is for

The creative half of the S2.2 split. Together with `copy_hash` it lets duplicate
detection ask two different questions -- "do these two ads say the same thing?"
and "do these two ads use the same assets?" -- which `content_hash` v1 cannot,
because it hashes both at once and so cannot attribute a match to either.

## The one rule that matters: this is an identity, not a content digest

`creative_hash` v1 hashes **provider media keys**, never media bytes. Bytes are
S2.4, and `AGENTS.md` section 12 forbids media byte downloads in S0-S3
outright, so the "sha256 of media bytes" that an earlier `ARCHITECTURE.md`
described is not reachable in this checkpoint. The provider key is the asset's
identity until the bytes exist, which is the fallback that same document names.

The consequence is worth stating plainly, because it bounds what duplicate
detection can claim: **two ads re-served under a rotated provider key look
different to this hash.** That is a real limitation, not a rounding error, and a
duplicate report built on it is a *hint*, not proof. When S2.4 hashes the actual
bytes, that becomes a **v2** of this function -- a new version literal, new
columns or a re-derivation, and **never** a reinterpretation of the v1 values
already stored. The same versioning discipline `content_hash` v1 established
applies here from the start rather than being retrofitted.

**Keys are sorted for the hash representation only.** The provider reorders its
output -- `REPOSITORY_RESEARCH.md:47` records that it does -- and a digest that
moved on a shuffle would mint a false "this ad changed" every time a walk
returned the same media in a different order. `RawAdRecord.media` and the stored
`normalized` JSON keep provider order, because those are the evidence; only this
function's own representation is sorted.

**Membership matters; counts are not collapsed.** Sorting is not deduplication.
`[a, b]` and `[a]` are different assets and must hash differently, or a creative
that lost an image would look unchanged.

**Duplicates stay duplicates.** Two entries with the same key frame as two
framed values, because the provider sent two and that is what was observed.
Collapsing them would make a record's own duplication invisible.
"""

from __future__ import annotations

from typing import Final

from app.providers.data.models import RawAdRecord
from app.services.hashing import digest, frame_collection

#: Written into the hashed input, so a v1 digest can never be mistaken for a
#: later version's digest over identical fields. S2.4's media-byte hash becomes
#: a v2 with a different literal; no stored v1 value is ever reinterpreted.
CREATIVE_HASH_VERSION: Final = "s2.2-creative-v1"


def creative_hash_v1(record: RawAdRecord) -> str:
    """The S2.2 creative digest for one normalized record.

    Args:
        record: The provider's report, as S1.3 read it. Never mutated.

    Returns:
        A lowercase 64-character SHA-256 hex digest over the record's provider
        media keys, sorted. An ad with no media hashes to a well-defined value
        rather than failing -- an ad reported without an asset is a real
        observation, not a malformed one, and the framed collection keeps it
        distinct from every ad that has assets.

    Everything except `media[].provider_key` is excluded: copy belongs to
    `copy_hash`, delivery and targeting are not creative, and `page_id` /
    `page_name` are attribution. `provider_metadata` is excluded because v1
    treats an unmodelled shape as a single frozen token rather than hashing the
    provider's own wording.
    """
    return digest(
        [
            CREATIVE_HASH_VERSION,
            # Sorted for the representation only -- `record.media` itself is not
            # touched, and the stored `normalized` JSON keeps provider order.
            frame_collection(sorted(asset.provider_key for asset in record.media)),
        ]
    )

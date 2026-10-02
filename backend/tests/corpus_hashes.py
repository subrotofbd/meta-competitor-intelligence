"""The demo corpus's real `copy_hash` values, computed with production logic.

## Why this module exists

`tests/fixtures/ai/analyses.json` is keyed by `copy_hash`, so its keys have to be the
digests production would actually compute. They used to be placeholders --
`mock-copy-hash-en-001` and friends -- which is worse than useless: they could never
be stored, because `ad_analysis.copy_hash` carries
`CHECK (copy_hash ~ '^[0-9a-f]{64}$')`. Every `MockAIProvider` lookup therefore missed,
the provider returned its all-null analysis, and `test_offline_guard`'s assertion that
the English fixture yields `language == "en"` was passing against a default rather
than against stored data.

Nothing here hand-writes a digest. Every value is produced by
`providers.data.normalize.normalize_record` followed by `services.copy_hash.copy_hash_v1`
-- the same two functions the collection pipeline uses -- so a test that imports this
module is asserting against what production computes, not against a constant someone
copied once.

## "Latest" means the sighting S2.1 actually stores

The corpus holds two sightings of `mock-ad-000101` with different wording, so it has
two copy digests. `_one_sighting_per_ad` keeps one sighting per ad per run, and the
**last** one wins. `corpus_copy_hash` returns that last digest, which is what ends up
in `ad_snapshots.copy_hash`, and therefore what `GET /ads/{id}` resolves an analysis
against. Verified against the seeded database: for all eight ads the stored digest
equals the last computed one.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.providers.data.normalize import normalize_record
from app.services.copy_hash import copy_hash_v1

#: The sanitised provider corpus. Already read by `MockProvider`; read again here
#: rather than imported so this module depends on nothing but the file itself.
CORPUS_PATH = Path(__file__).resolve().parent / "fixtures" / "ad_provider" / "corpus.json"


@lru_cache(maxsize=1)
def copy_hashes_by_ad() -> dict[str, tuple[str, ...]]:
    """Every copy digest the corpus yields, per ad id, in corpus order.

    Returns:
        `ad_id -> (digest, ...)` in the order the ads appear across the corpus's
        batches. More than one digest means the ad's wording changed between
        sightings.
    """
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    collected: dict[str, list[str]] = {}
    for entry in corpus["pages"]:
        for batch in entry["batches"]:
            for raw in batch["raw"].get("ads", []):
                record = normalize_record(raw)
                collected.setdefault(record.external_ad_id, []).append(copy_hash_v1(record))
    return {ad_id: tuple(digests) for ad_id, digests in collected.items()}


def corpus_copy_hash(ad_id: str) -> str:
    """The digest production would store for `ad_id` -- the last sighting.

    Raises:
        KeyError: The corpus holds no such ad. A typo must not silently become a
            digest that matches nothing.
    """
    digests = copy_hashes_by_ad()[ad_id]
    return digests[-1]

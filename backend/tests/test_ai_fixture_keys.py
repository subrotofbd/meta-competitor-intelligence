"""S3.3 step 3: the AI fixture is keyed by REAL production `copy_hash` digests.

## The defect this closes

`tests/fixtures/ai/analyses.json` was keyed `mock-copy-hash-en-001` and friends.
Those placeholders could never be stored, because `ad_analysis.copy_hash` carries
`CHECK (copy_hash ~ '^[0-9a-f]{64}$')`. So every `MockAIProvider` lookup missed, the
provider returned its all-null analysis, and `test_offline_guard` -- which asserts
the English fixture yields `language == "en"` -- was passing against a **default**
rather than against stored data. The guard it provided was real; the evidence behind
it was not.

## How the keys are derived

Not written by hand. `corpus_hashes.corpus_copy_hash(ad_id)` runs the corpus ad
through `providers.data.normalize.normalize_record` and then
`services.copy_hash.copy_hash_v1` -- the same two production functions the collection
pipeline uses. So these tests assert that the fixture agrees with production, rather
than that it agrees with a constant somebody once pasted.

## Which ad each analysis belongs to, and why

Chosen by matching the stored interpretation to the corpus copy, not by convenience:

| Fixture entry | Ad | Why |
|---|---|---|
| English, `high` | `mock-ad-000101` | "A kettle that actually whistles" |
| Hindi, `medium` | `mock-ad-000302` | "Haritaki, ashwagandha, neem" |
| all-null, sparse | `mock-ad-000203` | no title, empty body |

The English entry names the failing kettle, the 5,000 boil-cycle claim and the
published test log, which is what ad-000101 says. The Hindi one names both herbs and
reads ingredient disclosure as the headline, which is what ad-000302 says. The sparse
ad has nothing to read, which is what an all-null entry is for.

`mock-ad-000101` appears **twice** in the corpus with different wording, so it has two
copy digests. `_one_sighting_per_ad` keeps one sighting per ad and the **last** wins,
so the stored digest is the second. `corpus_copy_hash` returns that one, which is
what `GET /ads/{id}` resolves an analysis against.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.providers.ai.base import AIProvider
from app.providers.ai.mock import MockAIProvider
from app.providers.ai.models import CopyAnalysis
from app.services.copy_hash import copy_hash_v1
from tests.corpus_hashes import CORPUS_PATH, copy_hashes_by_ad, corpus_copy_hash

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ai" / "analyses.json"

#: A lowercase SHA-256 digest, exactly as `ad_analysis.copy_hash` demands.
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _fixture() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return loaded


def _responses() -> dict[str, Any]:
    responses: dict[str, Any] = _fixture()["responses"]
    return responses


# ============================================================
# The keys are real digests
# ============================================================


def test_every_fixture_key_is_a_64_char_lowercase_hex_digest() -> None:
    """The exact shape `ad_analysis.copy_hash`'s CHECK constraint requires.

    A key that fails this cannot be written, so an analysis stored under it would be
    unreachable through the product's only join path.
    """
    keys = list(_responses())
    assert keys, "the AI fixture must not be empty"
    for key in keys:
        assert _HEX64.fullmatch(key), f"{key!r} is not a 64-char lowercase hex digest"


def test_no_placeholder_keys_survive() -> None:
    """The old keys are named explicitly so their return is not silent."""
    keys = set(_responses())
    for gone in (
        "mock-copy-hash-en-001",
        "mock-copy-hash-hi-001",
        "mock-copy-hash-sparse-001",
    ):
        assert gone not in keys, gone


# ============================================================
# The keys are what production computes
# ============================================================


def test_each_key_equals_the_production_copy_hash_of_its_source_ad() -> None:
    """Recomputed here from production logic, not read from the helper.

    If the helper and this test both went wrong the same way, deriving the digests in
    one place and comparing them to itself would prove nothing. So this rebuilds the
    digest from `normalize_record` + `copy_hash_v1` directly.
    """
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    from app.providers.data.normalize import normalize_record

    latest: dict[str, str] = {}
    for entry in corpus["pages"]:
        for batch in entry["batches"]:
            for raw in batch["raw"].get("ads", []):
                record = normalize_record(raw)
                latest[record.external_ad_id] = copy_hash_v1(record)

    for digest, ad_id in _fixture()["source_ads"].items():
        assert ad_id in latest, f"{ad_id} is not in the corpus"
        assert digest == latest[ad_id], f"{ad_id}: fixture {digest} != production {latest[ad_id]}"
        assert digest in _responses(), f"{digest} is not a fixture key"


def test_the_helper_returns_the_last_sighting_digest() -> None:
    """`_one_sighting_per_ad` keeps one sighting and the last one wins.

    `mock-ad-000101` is the ad that proves this: two wordings, two digests, one stored
    snapshot.
    """
    digests = copy_hashes_by_ad()["mock-ad-000101"]
    assert len(digests) == 2, "the corpus no longer has two sightings of this ad"
    assert corpus_copy_hash("mock-ad-000101") == digests[-1]


def test_an_unknown_ad_id_raises_rather_than_returning_a_digest() -> None:
    """A typo must not become a well-formed digest that matches nothing."""
    with pytest.raises(KeyError):
        corpus_copy_hash("mock-ad-999999")


# ============================================================
# MockAIProvider actually finds them
# ============================================================


def test_the_mock_provider_finds_a_real_demo_analysis(ai_provider: AIProvider) -> None:
    """The point of the whole change: a lookup by computed digest returns data.

    Before, this returned the all-null default and every assertion about it was
    really an assertion about the default.
    """
    analysis = ai_provider.analyze_copy(_request(corpus_copy_hash("mock-ad-000101"))).analysis
    assert analysis.language == "en"
    assert analysis.hook is not None
    assert analysis.proof is not None


def test_all_three_stored_analyses_are_reachable(ai_provider: AIProvider) -> None:
    """Every key in the fixture resolves to itself, including the sparse one."""
    for key in _responses():
        analysis = ai_provider.analyze_copy(_request(key)).analysis
        assert analysis == CopyAnalysis(**_responses()[key]), key


def test_the_sparse_entry_is_still_fully_empty(ai_provider: AIProvider) -> None:
    """Re-keying must not have changed what the entry *says*.

    The all-null entry exists for the case where there is no copy to read. If it grew
    a field it would stop meaning that.
    """
    analysis = ai_provider.analyze_copy(_request(corpus_copy_hash("mock-ad-000203"))).analysis
    assert analysis == CopyAnalysis()


def test_an_unrelated_digest_still_misses(ai_provider: AIProvider) -> None:
    """Re-keying must not make every lookup succeed.

    A miss has to remain possible, or the dedupe logic that depends on it is untested.
    """
    analysis = ai_provider.analyze_copy(_request("0" * 64)).analysis
    assert analysis == CopyAnalysis()


def test_the_mock_can_be_built_straight_from_the_fixture(ai_provider: AIProvider) -> None:
    """The `conftest` loading path, built directly, resolves the same content."""
    stored = {key: CopyAnalysis(**value) for key, value in _responses().items()}
    provider = MockAIProvider(stored)
    for key in _responses():
        assert provider.analyze_copy(_request(key)).analysis == stored[key]


# ============================================================
# Nothing performance-shaped crept in
# ============================================================


def test_no_fixture_entry_mentions_a_performance_metric() -> None:
    """Spend, ROAS, leads, clicks, reach, impressions, CPM, revenue, conversions.

    These are not public for commercial ads (`AGENTS.md` section 5), so an
    interpretation that named one would be a claim this product cannot make. The
    fixture is stored text, which is exactly where such a claim would hide.
    """
    forbidden = (
        "roas",
        "spend",
        "cost per",
        "cpm",
        "cpc",
        "impression",
        "reach",
        "conversion",
        "lead gen",
        "revenue",
        "sales made",
        "click",
    )
    for key, entry in _responses().items():
        for field, value in entry.items():
            if not isinstance(value, str):
                continue
            lowered = value.lower()
            for word in forbidden:
                assert word not in lowered, f"{key}.{field} mentions {word!r}"


def test_no_field_outside_the_agreed_schema_was_added() -> None:
    """Fourteen analysis fields plus `language` and `confidence`. Nothing else.

    Re-keying a fixture is exactly the kind of edit that quietly grows a field.
    """
    allowed = set(CopyAnalysis.model_fields)
    for key, entry in _responses().items():
        assert set(entry) == allowed, f"{key}: {sorted(set(entry) ^ allowed)}"


def test_the_analysis_version_is_unchanged() -> None:
    """S3.1 pinned `s3.1-analysis-v1` as the served contract; the fixture's own
    `analysis_version` is a separate, mock-local label and must not drift silently
    either."""
    assert _fixture()["analysis_version"] == "mock-v1"


# ============================================================
# Contracts unchanged
# ============================================================


def test_re_keying_did_not_touch_the_analysis_provider_interface() -> None:
    """The change was to a data file. The Protocol is untouched.

    Asserted against the Protocol's own members rather than a list written here, so
    the test describes what the interface is rather than restating a snapshot of it.
    Read out of the class namespace: `__protocol_attrs__` is set by the Protocol
    metaclass, and reaching it through `vars()` keeps both ruff and mypy out of it.
    """
    protocol_attrs = vars(AIProvider).get("__protocol_attrs__", ())
    assert set(protocol_attrs) == {"name", "analyze_copy"}


def _request(copy_hash: str) -> Any:
    from app.providers.ai.models import CopyAnalysisRequest

    return CopyAnalysisRequest(copy_hash=copy_hash, analysis_version="mock-v1")

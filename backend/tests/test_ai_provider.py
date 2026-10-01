"""`AIProvider`, `MockAIProvider`, and the shape of a copy analysis.

The load-bearing assertions are the negative ones: which fields must be
absent, and which must stay `null`. A schema that grows a performance field, or
a mock that fills an unsupported slot, breaks the two rules this product cannot
bend -- never claim results that are not public, and never invent a value the
source did not contain.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.providers.ai.base import AIProvider
from app.providers.ai.mock import MockAIProvider
from app.providers.ai.models import (
    Confidence,
    CopyAnalysis,
    CopyAnalysisRequest,
)

#: The fourteen agreed analysis fields, plus the two that describe the analysis.
EXPECTED_FIELDS = {
    "hook",
    "problem",
    "promise",
    "offer",
    "cta",
    "persona",
    "pain_point",
    "angle",
    "proof",
    "urgency",
    "awareness_level",
    "funnel_stage",
    "copy_structure",
    "why_it_may_work",
    "language",
    "confidence",
}

#: Words that would turn an interpretation into a performance claim. Spend,
#: leads, sales, ROAS, conversions and reach are not public for commercial ads.
PERFORMANCE_CLAIM = "roas"


def _request(copy_hash: str, **overrides: str) -> CopyAnalysisRequest:
    return CopyAnalysisRequest(
        copy_hash=copy_hash,
        analysis_version="mock-v1",
        primary_text="A kettle that actually whistles.",
        **overrides,
    )


# ============================================================
# The schema
# ============================================================


def test_the_analysis_has_exactly_the_agreed_fields() -> None:
    assert set(CopyAnalysis.model_fields) == EXPECTED_FIELDS


def test_no_field_exists_for_a_performance_claim() -> None:
    """Their absence is the control. A schema cannot warn about a claim it cannot hold.

    This is asserted rather than documented because a future field named
    `conversions` or `estimated_roas` would be added without anyone re-reading
    AGENTS.md section 5.
    """
    forbidden = {
        "spend",
        "revenue",
        "roas",
        "leads",
        "conversions",
        "reach",
        "impressions",
        "clicks",
        "ctr",
        "performance",
    }
    assert not forbidden & set(CopyAnalysis.model_fields)


def test_every_analysis_field_is_optional() -> None:
    """An ad with no urgency has no urgency in its analysis. That is the design."""
    analysis = CopyAnalysis()
    for field in EXPECTED_FIELDS:
        assert getattr(analysis, field) is None


def test_an_analysis_is_frozen_and_closed() -> None:
    analysis = CopyAnalysis(hook="Opens on a familiar failure.")
    with pytest.raises(ValidationError):
        # Frozen: the assignment itself is legal to a type checker, and the
        # refusal is Pydantic's at runtime. Hence no ignore here.
        analysis.hook = "something else"
    with pytest.raises(ValidationError):
        CopyAnalysis(best_performing_variant="b")  # type: ignore[call-arg]


def test_a_request_must_carry_its_copy_hash_and_version() -> None:
    """Without both, an interpretation cannot be traced or de-duplicated."""
    with pytest.raises(ValidationError):
        CopyAnalysisRequest(analysis_version="mock-v1")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        CopyAnalysisRequest(copy_hash="mock-copy-hash-en-001")  # type: ignore[call-arg]


def test_a_request_keeps_the_copy_slots_separate() -> None:
    """A headline and body reading alike are two different signals."""
    request = _request("mock-copy-hash-en-001", headline="A kettle that whistles")
    assert request.primary_text is not None
    assert request.headline == "A kettle that whistles"


# ============================================================
# The protocol and the mock
# ============================================================


def test_the_mock_satisfies_the_protocol(ai_provider: AIProvider) -> None:
    assert isinstance(ai_provider, AIProvider)


def test_a_class_without_analyze_copy_does_not_satisfy_the_protocol() -> None:
    class NotAProvider:
        name = "not-a-provider"

    assert not isinstance(NotAProvider(), AIProvider)


def test_english_copy_is_analysed(ai_provider: AIProvider) -> None:
    analysis = ai_provider.analyze_copy(_request("mock-copy-hash-en-001")).analysis
    assert analysis.language == "en"
    assert analysis.confidence is Confidence.high
    assert analysis.hook is not None
    assert analysis.proof is not None


def test_hindi_copy_is_analysed_and_recorded_in_its_own_language(ai_provider: AIProvider) -> None:
    """Interpreted in Hindi, summarised in English, and labelled `hi`."""
    request = _request("mock-copy-hash-hi-001", language_hint="hi")
    analysis = ai_provider.analyze_copy(request).analysis
    assert analysis.language == "hi"
    assert analysis.hook is not None
    assert analysis.confidence is Confidence.medium


def test_an_unsupported_field_stays_null(ai_provider: AIProvider) -> None:
    """The English fixture has no urgency claim, and none is written for it."""
    analysis = ai_provider.analyze_copy(_request("mock-copy-hash-en-001")).analysis
    assert analysis.urgency is None
    assert analysis.offer is not None


def test_a_sparse_source_produces_a_fully_empty_analysis(ai_provider: AIProvider) -> None:
    """Copy with nothing in it yields fourteen nulls, not fourteen sentences."""
    analysis = ai_provider.analyze_copy(_request("mock-copy-hash-sparse-001")).analysis
    assert analysis == CopyAnalysis()


def test_unknown_copy_yields_an_empty_analysis_rather_than_a_guess() -> None:
    """No stored analysis means nobody has read this copy. Fourteen nulls say so."""
    provider = MockAIProvider({})
    analysis = provider.analyze_copy(_request("mock-copy-hash-never-analysed")).analysis
    assert analysis == CopyAnalysis()


def test_the_mock_never_claims_performance(ai_provider: AIProvider) -> None:
    for copy_hash in ("mock-copy-hash-en-001", "mock-copy-hash-hi-001"):
        analysis = ai_provider.analyze_copy(_request(copy_hash)).analysis
        for field in EXPECTED_FIELDS:
            value = getattr(analysis, field)
            if isinstance(value, str):
                assert PERFORMANCE_CLAIM not in value.lower()


def test_interpretation_is_framed_as_possibility(ai_provider: AIProvider) -> None:
    """`why_it_may_work` is a reading of the words, never a prediction.

    The field name carries the hedge, and the stored text has to keep carrying
    it too -- an analysis that concluded anything would be a claim the copy
    cannot support.
    """
    assert "why_it_may_work" in CopyAnalysis.model_fields
    hedge = ("may", "might", "could", "whether", "it is a reading")
    for copy_hash in ("mock-copy-hash-en-001", "mock-copy-hash-hi-001"):
        text = ai_provider.analyze_copy(_request(copy_hash)).analysis.why_it_may_work
        assert text is not None
        assert any(word in text.lower() for word in hedge), text


def test_analysis_is_deterministic(ai_provider: AIProvider) -> None:
    request = _request("mock-copy-hash-en-001")
    assert ai_provider.analyze_copy(request) == ai_provider.analyze_copy(request)


def test_the_response_table_is_copied_at_construction() -> None:
    """Mutating the caller's dictionary after construction changes nothing."""
    responses = {"hash-a": CopyAnalysis(hook="first")}
    provider = MockAIProvider(responses)
    responses["hash-b"] = CopyAnalysis(hook="added later")
    assert provider.analyze_copy(_request("hash-b")).analysis == CopyAnalysis()
    assert provider.analyze_copy(_request("hash-a")).analysis.hook == "first"

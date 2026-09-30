"""What copy analysis returns, and what it is asked for.

## The rule this file exists to enforce

**A field the source did not support is `None`.** Not a plausible sentence, not
a generic observation, not a restatement of the input. An ad with no urgency in
its copy has no urgency in its analysis.

`CopyAnalysis` is therefore almost entirely optional, and that is the correct
shape rather than a gap to be filled in later. A fully-populated result is
evidence that a model read the copy; a sparse one is evidence that the copy did
not say more.

## The rule this file also enforces

**There is no performance field, and there must never be one.** Spend, leads,
sales, ROAS, conversions and reach are not public for commercial ads
(AGENTS.md section 5). Their absence is deliberate, and `test_ai_provider.py`
asserts the field set so a future field cannot be added by accident.

The schema describes how the copy *reads*. `why_it_may_work` is named for the
uncertainty it carries: it is one reading of the words, not a prediction.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Confidence(StrEnum):
    """How firmly the analysis holds, as the model states it.

    Confidence in *interpretation*, never in a number about results.
    """

    low = "low"
    medium = "medium"
    high = "high"


class CopyAnalysisRequest(BaseModel):
    """One ad's copy, handed to a model for interpretation.

    The copy fields are the ad's own, kept separate rather than concatenated, so
    a provider can see which string came from where -- "Free shipping" as a
    headline and as body text are different signals.

    They repeat the names used by `RawAdRecord` on purpose, but they are a
    separate type on purpose too: a record is what a provider reported, and this
    is what we chose to interpret. Copy can also arrive from a CSV import or a
    snapshot without a provider ever being involved, and nothing here should
    have to import a provider to describe it.

    Attributes:
        copy_hash: The hash of the exact copy analysed. Required, because
            every `AI_INTERPRETATION` value must be traceable back to the
            snapshot it was derived from (AGENTS.md section 7). Without it, an
            interpretation cannot be tied to the words that produced it.
        analysis_version: Version of the analysis prompt and schema. Results are
            deduplicated on `(copy_hash, analysis_version)`, so changing either
            must change this value.
        language_hint: The operator's guess at the copy's language. A hint, not
            an instruction -- Hindi and Hinglish copy is analysed in its own
            language and summarised in English alongside.
        country: Market the ad ran in, when known.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    copy_hash: str = Field(min_length=1)
    analysis_version: str = Field(min_length=1)
    primary_text: str | None = None
    headline: str | None = None
    description: str | None = None
    cta: str | None = None
    language_hint: str | None = None
    country: str | None = None


class CopyAnalysis(BaseModel):
    """How one ad's copy reads, field by field.

    Every field is optional because every field can be genuinely unsupported.
    English and Hindi results share this schema; the non-English text stays in
    its own language and `language` records which it was.

    Attributes:
        hook: The line or device that opens the ad.
        problem: The pain the copy puts forward, if it names one.
        promise: What the copy says the reader will get.
        offer: Price, discount, bundle or trial, if one is stated.
        cta: The action the copy asks for.
        persona: Who the copy addresses.
        pain_point: The specific frustration it leans on, if any.
        angle: The framing -- urgency, status, fear, curiosity, and so on.
        proof: Claims of evidence: numbers, credentials, demonstrations.
        urgency: Scarcity or time pressure, if present.
        awareness_level: How familiar the copy assumes the reader is.
        funnel_stage: Where in the buying path the copy aims.
        copy_structure: How the copy is built, in words.
        why_it_may_work: One reading of why these words might land, framed as
            possibility. Never a result, a forecast, or a verdict.
        language: The language the analysis was produced in.
        confidence: The model's own confidence in the interpretation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hook: str | None = None
    problem: str | None = None
    promise: str | None = None
    offer: str | None = None
    cta: str | None = None
    persona: str | None = None
    pain_point: str | None = None
    angle: str | None = None
    proof: str | None = None
    urgency: str | None = None
    awareness_level: str | None = None
    funnel_stage: str | None = None
    copy_structure: str | None = None
    why_it_may_work: str | None = None
    language: str | None = None
    confidence: Confidence | None = None

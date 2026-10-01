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

## Language: one set of fields, in the copy's own language

Every analysis field is written in **the language the analysed copy is in**, and
`language` records which that was. Hindi and Hinglish copy is analysed in
Hindi/Hinglish.

There are deliberately **no `*_en` companion fields**. `AGENTS.md` section 10
and `ARCHITECTURE.md` once promised "English summary fields produced alongside";
no such field has ever existed in this schema, and adding fourteen of them would
double the contract, force a UI rule about which column to show, and put two
translations of one interpretation side by side with nothing to say which is
authoritative. Both documents were corrected to describe what ships. English
summary generation, if it is ever wanted, is a **new analysis version with its
own schema** -- not fourteen nullable columns bolted onto v1.

## Why `CopyAnalysis` alone is not what a provider returns

`CopyAnalysis` is the *content*. A provider call also produces facts about the
call itself -- which model answered, and what it said it was used -- and S3.1 is
required to track tokens and cost per call (`AGENTS.md` section 10). A bare
`CopyAnalysis` return had nowhere to put any of that, so the protocol now
returns `AIResult`, which carries the analysis beside `AIUsage`.

**Usage is nullable throughout and never defaulted to zero.** A provider that
reports no token counts has told us nothing about cost, and `0` is a claim about
cost that nobody made.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

#: Ceiling on one analysis field's text. A fourteen-field reading of a short ad
#: is a few hundred characters, so this is generous while still bounding a
#: pathological answer before it reaches a `Text` column. Bounded here rather
#: than only in the prompt because a prompt instruction is a request and a
#: `max_length` is a refusal.
MAX_ANALYSIS_FIELD_CHARS = 2_000

#: ISO-639-ish tag for `language`. Short on purpose: this records what the model
#: says it wrote in, not a language tag the product validates against a registry.
MAX_LANGUAGE_CHARS = 32

#: One copy field handed to the model. The same ceiling as an analysis field, for
#: the same reason: the request is stored nowhere, but a runaway request is a
#: runaway bill.
MAX_COPY_FIELD_CHARS = 20_000


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
        corrective_error: Why the previous answer could not be used, set only for
            the one permitted retry. `None` on a first ask.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    copy_hash: str = Field(min_length=1, max_length=128)
    analysis_version: str = Field(min_length=1, max_length=64)
    primary_text: str | None = Field(default=None, max_length=MAX_COPY_FIELD_CHARS)
    headline: str | None = Field(default=None, max_length=MAX_COPY_FIELD_CHARS)
    description: str | None = Field(default=None, max_length=MAX_COPY_FIELD_CHARS)
    cta: str | None = Field(default=None, max_length=MAX_COPY_FIELD_CHARS)
    language_hint: str | None = Field(default=None, max_length=MAX_LANGUAGE_CHARS)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    corrective_error: str | None = Field(default=None, max_length=1_000)
    """Set only for the single permitted retry, naming why the last answer failed.

    The `AIProvider` protocol is one method taking a request, so the retry has to
    travel *in* the request rather than as a second argument: the adapter selects
    `corrective_prompt` when this is present and `user_prompt` when it is not.

    Carries a Pydantic validation message, which names fields and value types and
    does not quote the offending input -- so the competitor's copy is not sent back
    to the provider to be criticised. Asserted by a test, not assumed.
    """


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
        awareness_level: How familiar the copy assumes the reader is. A free
            string, not an enum, on purpose: a closed vocabulary a model does not
            hit exactly would spend the single corrective retry and then fail the
            ad outright, which is a worse outcome than a slightly loose label.
        funnel_stage: Where in the buying path the copy aims. Free string for the
            same reason as `awareness_level`.
        copy_structure: How the copy is built, in words.
        why_it_may_work: One reading of why these words might land, framed as
            possibility. Never a result, a forecast, or a verdict.
        language: The language the analysis was produced in.
        confidence: The model's own confidence in the interpretation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Same `MAX_ANALYSIS_FIELD_CHARS` bound on all fourteen. Written out
    # rather than through a helper so each field's declaration reads the same
    # way to a person and to a type checker.
    hook: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    problem: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    promise: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    offer: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    cta: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    persona: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    pain_point: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    angle: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    proof: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    urgency: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    awareness_level: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    funnel_stage: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    copy_structure: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    why_it_may_work: str | None = Field(default=None, max_length=MAX_ANALYSIS_FIELD_CHARS)
    language: str | None = Field(default=None, max_length=MAX_LANGUAGE_CHARS)
    confidence: Confidence | None = None


class AIUsage(BaseModel):
    """What a provider said this call used.

    Every field is nullable and none defaults to a number. A provider that
    reports no usage has told us nothing about what the call cost, and writing
    `0` would be inventing a cost claim nobody made -- which is the same failure
    as inventing an analysis field, one level down.

    A partially-reported usage is kept as given: `total_tokens` present with the
    prompt and completion counts absent is a real shape some providers return,
    and filling the gaps from the parts we do have would be arithmetic dressed up
    as a report.

    Attributes:
        prompt_tokens: Tokens the provider billed for the request.
        completion_tokens: Tokens the provider billed for the answer.
        total_tokens: The provider's own total, when it states one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class AIResult(BaseModel):
    """One provider call's answer, and what is known about the call.

    Wraps `CopyAnalysis` rather than extending it, because the analysis is the
    content and everything else here is a fact *about* producing it. Keeping them
    apart is what stops a token count from ever being mistaken for a field the
    competitor's ad said.

    Attributes:
        analysis: The validated interpretation.
        provider: Stable provider name, recorded with the analysis so a stored
            result can always be traced to what produced it.
        model: The model that answered, or `None` when the provider reports none.
            Never a hard-coded name: it comes from settings.
        usage: What the provider reported it used, or `None` when it reported
            nothing at all.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    analysis: CopyAnalysis
    provider: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    usage: AIUsage | None = None

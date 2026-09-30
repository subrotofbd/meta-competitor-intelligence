"""The two provenance axes, and the fact that they stay apart.

`DataOrigin` and `EvidenceClass` answer different questions. The tests below
are mostly about the separation: a change that quietly merged them, or that let
one stand in for the other, would pass every test of the values themselves.
"""

from __future__ import annotations

import json

import pytest

from app.providers.data.provenance import (
    DataOrigin,
    EvidenceClass,
    evidence_class_for,
)

# Pinned deliberately. These values are stored in the database and rendered in
# the UI; a new member needs a migration and a label, not a quiet append here.
EXPECTED_ORIGINS = {"official_api", "public_ui", "third_party", "user_import"}
EXPECTED_EVIDENCE = {
    "VERIFIED_PUBLIC_DATA",
    "PROVIDER_DATA",
    "ESTIMATE",
    "AI_INTERPRETATION",
}


def test_origin_members_are_exactly_the_documented_four() -> None:
    assert {member.value for member in DataOrigin} == EXPECTED_ORIGINS


def test_evidence_members_are_exactly_the_documented_four() -> None:
    assert {member.value for member in EvidenceClass} == EXPECTED_EVIDENCE


def test_the_two_axes_share_no_values() -> None:
    """Merging them would be easy and would destroy the distinction."""
    origins = {member.value for member in DataOrigin}
    evidence = {member.value for member in EvidenceClass}
    assert origins.isdisjoint(evidence)


def test_origin_is_not_a_confidence_ranking() -> None:
    """`official_api` is not "more trustworthy than" `third_party`.

    It is a statement about who answered. The test asserts the axes never name
    each other: no origin carries a confidence word, and no evidence class
    names a source.
    """
    origin_words = {"low", "medium", "high", "confidence", "trust", "verified"}
    evidence_words = EXPECTED_ORIGINS
    assert not {member.name.lower() for member in DataOrigin} & origin_words
    assert not {member.name.lower() for member in EvidenceClass} & evidence_words


def test_evidence_class_is_not_a_collection_method() -> None:
    """`ESTIMATE` and `AI_INTERPRETATION` describe our own work, not a source."""
    for computed in (EvidenceClass.ESTIMATE, EvidenceClass.AI_INTERPRETATION):
        assert computed.value.lower() not in EXPECTED_ORIGINS


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (DataOrigin.official_api, EvidenceClass.VERIFIED_PUBLIC_DATA),
        (DataOrigin.public_ui, EvidenceClass.PROVIDER_DATA),
        (DataOrigin.third_party, EvidenceClass.PROVIDER_DATA),
        (DataOrigin.user_import, EvidenceClass.PROVIDER_DATA),
    ],
)
def test_each_origin_maps_to_its_documented_class(
    origin: DataOrigin, expected: EvidenceClass
) -> None:
    assert evidence_class_for(origin) is expected


def test_a_paid_feed_is_never_badgeable_as_verified() -> None:
    """The mapping that matters most, stated as its own test.

    `third_party` maps to `PROVIDER_DATA`. If a future edit promoted it to
    `VERIFIED_PUBLIC_DATA`, this is the line that catches it.
    """
    assert evidence_class_for(DataOrigin.third_party) is not EvidenceClass.VERIFIED_PUBLIC_DATA


def test_every_origin_has_a_mapping() -> None:
    """A new origin must not fall through to a default and be silently trusted."""
    for origin in DataOrigin:
        assert isinstance(evidence_class_for(origin), EvidenceClass)


def test_values_serialise_as_plain_strings() -> None:
    """They are persisted and shipped to the browser, so they must round-trip."""
    payload = json.dumps(
        {"origin": DataOrigin.third_party, "evidence": EvidenceClass.AI_INTERPRETATION}
    )
    assert json.loads(payload) == {
        "origin": "third_party",
        "evidence": "AI_INTERPRETATION",
    }

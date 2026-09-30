"""Provenance: two independent axes that answer two different questions.

`DataOrigin` is *how a value was obtained*. `EvidenceClass` is *how much the
product can stand behind it*. They are stored, compared and rendered
separately, and collapsing them into one field loses the distinction that makes
the product honest (AGENTS.md section 7).

Neither is a trust ranking and neither substitutes for the other:

* `DataOrigin` is not a confidence score. A paid third-party feed is
  `third_party` however accurate it turns out to be, and Meta's own API is
  `official_api` however thin its coverage is.
* `EvidenceClass` is not a collection method. It says how far we will vouch
  for a number, never who we asked.

Values are fixed. New provenance needs a migration and a UI label, not a new
member appended here at the call site.
"""

from __future__ import annotations

from enum import StrEnum


class DataOrigin(StrEnum):
    """How a value reached us."""

    official_api = "official_api"
    """Meta's documented API. Verified public data, narrow coverage."""

    public_ui = "public_ui"
    """Read from Meta's public Ad Library pages. Public, but unversioned."""

    third_party = "third_party"
    """A paid intermediary. We cannot verify how they obtained it."""

    user_import = "user_import"
    """Supplied by the operator. Its accuracy is their claim, not ours."""


class EvidenceClass(StrEnum):
    """How far the product stands behind a value."""

    VERIFIED_PUBLIC_DATA = "VERIFIED_PUBLIC_DATA"
    """Served by Meta's own API. Quote it directly."""

    PROVIDER_DATA = "PROVIDER_DATA"
    """A provider's claim, passed through. Name the provider when showing it."""

    ESTIMATE = "ESTIMATE"
    """Computed by us. Always rendered with its method and confidence, never
    as a fact. No estimates exist yet."""

    AI_INTERPRETATION = "AI_INTERPRETATION"
    """Model output. Always badged, and always linked back to the snapshot and
    `copy_hash` it was derived from."""


#: The origin-to-evidence-class mapping applied to a freshly collected value.
#:
#: Only origins are keys. Computed and model-derived values do not come from a
#: provider, so they are stamped `ESTIMATE` and `AI_INTERPRETATION` by the code
#: that computes or requests them, never by looking up their origin.
_DEFAULT_EVIDENCE: dict[DataOrigin, EvidenceClass] = {
    DataOrigin.official_api: EvidenceClass.VERIFIED_PUBLIC_DATA,
    DataOrigin.public_ui: EvidenceClass.PROVIDER_DATA,
    DataOrigin.third_party: EvidenceClass.PROVIDER_DATA,
    DataOrigin.user_import: EvidenceClass.PROVIDER_DATA,
}


def evidence_class_for(origin: DataOrigin) -> EvidenceClass:
    """The evidence class a value collected from `origin` carries.

    Centralised so the mapping is applied once. Letting each call site pick its
    own class is how a third-party feed ends up badged as verified.
    """
    return _DEFAULT_EVIDENCE[origin]

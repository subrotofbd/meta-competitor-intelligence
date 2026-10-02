"""Response shapes for the ad read API.

## Separate from the ORM models, deliberately

These are not `model_config = {"from_attributes": True}` wrappers around the tables.
The ORM shapes carry things this API must not hand a client -- `raw_ref` into the raw
payload, queue ids, `storage_key` -- and adding a column to a table would silently
publish it. A hand-written schema means a new column is invisible until someone
decides to expose it.

## NULL means something different from "no"

`AGENTS.md` section 7: a missing value is `null` and renders as an em dash. It is
never `0`, never `"N/A"`, never a plausible placeholder. Every optional field below is
genuinely optional and nothing fills it in.

Two distinctions this file is careful about:

- **`provider_active` is tri-state.** `true`, `false`, and `null` meaning "the
  provider gave us nothing to say". Rounding `null` to `false` would invent a
  finding, so the field is `bool | None` and stays that way.
- **`analysis` is `null` when no analysis exists.** Not an object with fourteen null
  fields, which would look like "we analysed it and found nothing".

## Status is never flattened

There is deliberately **no `current_status` field on an ad**. S2.3 gives each
`(ad, Page, country)` context its own conclusion, and a single ad-level status would
be a claim about something the product does not know. `contexts` carries them all.

## AI output is badged, in the payload

Every AI field sits under `evidence_class: AI_INTERPRETATION`. That is not
decoration: the concrete risk is a client joining `ad.data_origin` (`PROVIDER_DATA`)
onto model output and presenting an interpretation as something the provider said.
The label travels with the data rather than living in a UI convention.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.providers.data.provenance import DataOrigin, EvidenceClass
from app.schemas.base import _Response
from app.services.ad_duration import DurationBucket, DurationSource


class DurationOut(_Response):
    """Elapsed running time, and which timestamp it was measured from.

    `source` is not optional context. `AGENTS.md` section 8 requires any duration
    display to state which of the two start timestamps it used, and the two can be
    months apart for a commercial ad.
    """

    days: int = Field(ge=0)
    bucket: DurationBucket
    source: DurationSource
    #: A longevity proxy. Never a performance claim, and the wording of any badge
    #: built from it ships with `services.ad_duration`'s documented tooltip.
    is_long_running_signal: bool


class ContextOut(_Response):
    """One ad's status in one Page + country context.

    This is where status lives. There is no ad-level status anywhere in this API.
    """

    facebook_page_id: uuid.UUID
    country: str
    #: `seen` / `not_seen_since` / `presumed_inactive` -- a presumption, never a
    #: verdict. `not_seen_since` is explicitly not "stopped".
    current_status: str
    #: Tri-state on purpose. `null` means the provider made no assertion.
    provider_active: bool | None
    #: When *we* last observed this ad in a complete run for this context. Never
    #: `meta_delivery_start`: that is the provider's claim, and merging them would
    #: assert a past we cannot support.
    not_seen_since_at: datetime | None
    last_status_run_id: uuid.UUID | None


class SnapshotSummaryOut(_Response):
    """The snapshot an ad currently looks like.

    Deliberately excludes `raw_ref` -- it is an internal pointer into the raw payload,
    and exposing it invites a client to fetch evidence this API does not serve.
    """

    id: uuid.UUID
    created_at: datetime
    content_hash: str
    #: `null` for a snapshot written before S2.2. It cannot be backfilled: the table
    #: is append-only and an `UPDATE` is refused by the trigger.
    copy_hash: str | None
    creative_hash: str | None
    #: The provider's own reported status, untranslated. Distinct from the derived
    #: `contexts[].current_status`, which is our conclusion.
    ad_status: str | None
    meta_delivery_start: datetime | None


class CopyFieldsOut(_Response):
    """The four copy fields, read straight out of `normalized`.

    Provider text, verbatim. No canonicalisation, no trimming, no rewriting: this is
    what the competitor ran.
    """

    primary_text: str | None
    headline: str | None
    description: str | None
    cta: str | None
    destination_url: str | None


class MediaReferenceOut(_Response):
    """One creative asset, as a reference.

    S2.4 stores references only. `bytes_available` is hard-coded `false` because that
    is the truth until an approved byte-acquisition phase exists, and saying so is
    clearer than emitting a `storage_key` that is always null -- a client would
    reasonably read a present-but-null key as a download path.
    """

    provider: str
    provider_key: str
    #: Stored verbatim and **never requested by this API**.
    source_url: str | None
    mime: str | None
    width: int | None
    height: int | None
    duration_seconds: Decimal | None
    first_seen_at: datetime
    last_seen_at: datetime
    bytes_available: bool = False


class AnalysisOut(_Response):
    """Model interpretation of this ad's copy.

    Copy-scoped and reusable: the same words on two ads resolve to one analysis, so
    this is a property of the *copy*, not of the ad. It is badged
    `AI_INTERPRETATION` because a client must never present it as provider data.

    The fourteen fields are returned as an opaque `interpretation` mapping rather than
    fourteen typed columns: they are model output whose shape is versioned by
    `analysis_version`, and flattening them here would freeze v1's field set into this
    API's contract when a v2 is already anticipated.
    """

    evidence_class: EvidenceClass = EvidenceClass.AI_INTERPRETATION
    copy_hash: str
    analysis_version: str
    prompt_version: str
    provider: str
    model: str | None
    language: str | None
    confidence: str | None
    #: The fourteen fields, or `{}` when a model answered with all of them null. An
    #: empty mapping is a real reading of sparse copy, not missing data.
    interpretation: dict[str, str | None]
    source_snapshot_id: uuid.UUID
    created_at: datetime


class AdListItemOut(_Response):
    """One ad in a list response.

    Identity, provenance, the current observation, the copy, the longevity signal, and
    every status context. Deliberately no `current_status`: see the module docstring.
    """

    id: uuid.UUID
    provider: str
    meta_ad_id: str
    data_origin: DataOrigin
    first_seen_at: datetime
    last_seen_at: datetime
    latest_snapshot: SnapshotSummaryOut | None
    duration: DurationOut | None
    contexts: tuple[ContextOut, ...]
    media: tuple[MediaReferenceOut, ...] = ()
    #: Where the provider reported this ad running, in the provider's own order.
    #:
    #: Read from the latest snapshot's `normalized` document -- no column was added
    #: and no hash moved. `[]` means **the stored record lists no platforms**, which
    #: is not the claim "this ad ran nowhere": a provider that reports nothing is
    #: recorded as nothing. `tuple` rather than `list` for consistency with
    #: `contexts` and `media`; it serialises to a JSON array either way.
    platforms: tuple[str, ...] = ()
    #: The copy of the **latest** snapshot, verbatim from `normalized`.
    #:
    #: Added at S3.3 step 6A. A competitor-research grid that cannot show what an ad
    #: says is not much use, and the alternative was a client fetching `/ads/{id}` per
    #: row -- one request per row to read a document the list query has *already*
    #: loaded. `ad_query` selects every page's latest snapshots in a single batched
    #: query, so this costs no additional round trip at all.
    #:
    #: `null` when the ad has no snapshot yet, which is a real state for an ad row that
    #: exists before its first observation is written. Individual fields inside stay
    #: `null` when the provider reported no text, which is not the same thing and is not
    #: filled with a placeholder.
    #:
    #: The **same** `CopyFieldsOut` the detail and snapshot responses use, so the three
    #: cannot drift. It carries `destination_url` as well; that field already belongs to
    #: the approved copy contract and no client is required to render it.
    copy_fields: CopyFieldsOut | None


class AdListOut(_Response):
    """A page of ads.

    `page` beyond the end returns `items: []` with the real `total`, not a 404 -- the
    request was well formed, there is simply nothing on that page.
    """

    items: tuple[AdListItemOut, ...]
    total: int
    page: int
    page_size: int


class AdDetailOut(_Response):
    """One ad in full.

    A superset of the list item: the same identity and contexts, plus the copy text,
    the AI interpretation, and the media references. Everything internal --
    `raw_ref`, queue ids, prompts, raw responses, `storage_key` -- is absent.
    """

    id: uuid.UUID
    provider: str
    meta_ad_id: str
    data_origin: DataOrigin
    first_seen_at: datetime
    last_seen_at: datetime
    latest_snapshot: SnapshotSummaryOut | None
    duration: DurationOut | None
    contexts: tuple[ContextOut, ...]
    copy_fields: CopyFieldsOut | None
    analysis: AnalysisOut | None
    media: tuple[MediaReferenceOut, ...] = ()
    #: The latest snapshot's reported platforms, provider order preserved. `[]` means
    #: the stored record lists none -- never that the ad ran on no platform.
    platforms: tuple[str, ...] = ()


class SnapshotListItemOut(_Response):
    """One observation, as stored.

    The copy fields are included here and not in the list endpoint: a snapshot page
    *is* a history page, and showing what the ad said at a point in time is the point
    of it.
    """

    id: uuid.UUID
    created_at: datetime
    collection_run_id: uuid.UUID
    content_hash: str
    copy_hash: str | None
    creative_hash: str | None
    ad_status: str | None
    meta_delivery_start: datetime | None
    copy_fields: CopyFieldsOut
    media: tuple[MediaReferenceOut, ...] = ()
    #: This snapshot's own reported platforms, provider order preserved.
    #:
    #: Per snapshot rather than per ad, because a snapshot is an *observation*: it
    #: records what the provider said at a moment, and the platforms an ad ran on can
    #: legitimately differ between two observations of the same ad. Reading the
    #: latest value for every row would make history claim things it never saw.
    platforms: tuple[str, ...] = ()
    #: Referenced, not embedded. Copy-scoped analysis means the analysis an ad
    #: currently resolves to may originate from a *different* snapshot, and saying so
    #: honestly is better than pretending this observation produced it.
    analysis_copy_hash: str | None = None


class SnapshotListOut(_Response):
    """A page of one ad's history, newest first."""

    items: tuple[SnapshotListItemOut, ...]
    total: int
    page: int
    page_size: int

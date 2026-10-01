"""Response shapes for the competitor directory.

## Why this endpoint exists

Until S3.3 the only handle on a competitor or a Page anywhere in the API was an
opaque UUID: `/ads` filters accept `competitor_id` and `facebook_page_id`, and
`contexts[].facebook_page_id` returns a UUID, but nothing ever named them. A client
could filter by a value it could not obtain a value *for* -- a competitor directory
that cannot be listed is not a directory.

So this is a read-only listing of what the operator already told us, nested the way
the data actually nests.

## No provenance fields, deliberately

Neither `data_origin` nor `evidence_class` appears here, and adding either would be
a lie. `models/tracking.py` is explicit: a competitor is something the operator told
us about and a page is something a provider reports, but **neither is collected
data**, so neither carries an origin. The first collected value enters the schema at
`collection_runs`, and everything below it inherits the origin from there.

Stamping `PROVIDER_DATA` on a Page would also be wrong twice over: it would imply
the Page is a provider claim, and it would suggest the *operator's* competitor list
is third-party data.

## No counts, and no `updated_at`

No ad counts, no collection-run counts. Those are aggregates this product has never
computed, and a count on a directory response is an invitation to read it as
performance -- "42 ads" next to a competitor name invites the question "and how well
did they do", which this product cannot answer at all.

No `updated_at` either. It exists on the table and would be trivially available, but
nothing in the product acts on it yet, and shipping a field implies a freshness
guarantee nobody has defined.

## Untracked pages are returned

A page the operator stopped tracking is still returned, with `is_tracked: false`. It
is **not** hidden, and it is not soft-deleted: `ad_snapshots` is append-only with
`RESTRICT` foreign keys, so its history remains real and visible. Hiding the page
would hide that history behind a flag that the schema does not otherwise define --
a soft delete the database does not have.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.base import _Response


class FacebookPageOut(_Response):
    """One Meta Page belonging to a competitor.

    `id` is this project's internal key and is what `/ads?facebook_page_id=` takes.
    `page_id` is the provider's own identity for the same Page. Both are exposed
    because they are different things and conflating them is the duplication
    `models/tracking.py` refuses to store.
    """

    #: Internal key. Reuse it verbatim as `/ads?facebook_page_id=`.
    id: uuid.UUID = uuid.uuid4()
    #: The provider's identity for this Page. Globally unique across competitors.
    page_id: str
    #: Provider-reported. `None` when the provider reported no name -- never `""`.
    name: str | None
    #: `None` when unknown. Always `http(s)`; the column refuses anything else.
    url: str | None
    #: ISO 3166 alpha-2. Mandatory, unlike `name` -- a run cannot be judged complete
    #: without it.
    country: str
    #: Whether the operator still collects this Page. Not a delete flag: the Page and
    #: its history stay, and an untracked Page is reported as untracked.
    is_tracked: bool
    #: Free text, not a closed vocabulary. A scheduling decision, not a fact.
    tracking_frequency: str
    created_at: datetime


class CompetitorOut(_Response):
    """One competitor the operator tracks, with every Page they advertise from.

    `pages` is always present and may be empty: a competitor with no Pages yet is a
    real, incomplete thing the operator created, and omitting them would hide it.
    """

    #: Reuse it verbatim as `/ads?competitor_id=`.
    id: uuid.UUID
    #: **Not unique.** Two brands may share a name in different markets, so a
    #: competitor is identified by `id`, never by its name.
    name: str
    created_at: datetime
    pages: tuple[FacebookPageOut, ...]


class CompetitorListOut(_Response):
    """Every tracked competitor.

    An envelope rather than a bare array because `items` is the shape every other
    list response in this API uses, and a client should not have to learn two. There
    is deliberately no `total`/`page`/`page_size`: the directory is small, is not
    paged, and inventing a page it can never need would be a promise the code does
    not keep.
    """

    items: tuple[CompetitorOut, ...]

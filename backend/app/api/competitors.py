"""The competitor directory: `GET /competitors`.

## One endpoint, and one reason it exists

Until now the only handle on a competitor anywhere in this API was an opaque UUID.
`/ads` accepts `competitor_id` and `facebook_page_id`, and `contexts[]` returns a
`facebook_page_id`, but nothing ever produced a *name*. A client could filter by a
value it had no way to obtain, which is the same as not being able to filter at all.

This is the smallest read that fixes it: every competitor, with the Pages each one
advertises from.

## Thin on purpose

`api/__init__.py` sets the rule -- parse and validate, delegate to `services`,
serialise. There is **no SQL in this file** and no business decision either, so the
ordering and grouping live in `services/competitor_query.py` where they can be tested
without an HTTP layer.

## Every route here is a `GET`

No route in this package calls `AIProvider`, enqueues a job, fetches media, or writes
anything. This one in particular sits in the same process that *can* schedule
collection runs, so "it only reads" is a claim worth stating explicitly: it performs
two `SELECT`s and nothing else.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.competitors import CompetitorListOut, CompetitorOut, FacebookPageOut
from app.services.competitor_query import CompetitorRecord, list_competitors

router = APIRouter(tags=["competitors"])

SessionDep = Annotated[Session, Depends(get_session)]


def _page_out(page: Any) -> FacebookPageOut:
    """One Page, selected field by field.

    Written out rather than built from the ORM with a config flag, because the point
    of the response schemas is that adding a column to `facebook_pages` does not
    publish it. `updated_at` exists on the table and is deliberately not copied.
    """
    return FacebookPageOut(
        id=page.id,
        page_id=page.page_id,
        # Nullable because a provider need not report them. Passed straight through:
        # `None` means "not reported", and converting it to `""` would invent a name.
        name=page.name,
        url=page.url,
        country=page.country,
        is_tracked=page.is_tracked,
        tracking_frequency=page.tracking_frequency,
        created_at=page.created_at,
    )


def _competitor_out(record: CompetitorRecord) -> CompetitorOut:
    return CompetitorOut(
        id=record.competitor.id,
        name=record.competitor.name,
        created_at=record.competitor.created_at,
        # Empty tuple, not omitted: a competitor with no Pages yet is a real and
        # visibly incomplete thing the operator created.
        pages=tuple(_page_out(page) for page in record.pages),
    )


@router.get("/competitors", response_model=CompetitorListOut, summary="List competitors")
def get_competitors(session: SessionDep) -> CompetitorListOut:
    """Every competitor the operator tracks, with their Meta Pages.

    The `id` of a competitor is what `/ads?competitor_id=` takes, and the `id` of a
    page is what `/ads?facebook_page_id=` takes -- the same UUIDs, so a client can
    select here and filter there without translating anything.

    Pages the operator has stopped tracking are still returned, with
    `is_tracked: false`. They are not deleted and not hidden: their snapshot history
    is append-only and still real.
    """
    records = list_competitors(session)
    return CompetitorListOut(items=tuple(_competitor_out(record) for record in records))

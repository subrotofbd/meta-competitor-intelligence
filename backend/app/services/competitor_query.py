"""Reading the competitor directory: operators' own tracking list.

## What this is, and is not

A listing of what the operator told us -- which brands they watch, and which Meta
Pages each of those brands advertises from. **No collection, no provider call, no
analysis, no media, no queue.** It is two `SELECT`s against `competitors` and
`facebook_pages` and nothing else, which is what "read-only" has to mean when the
same process can also schedule collection runs and submit AI jobs.

## Two queries, not one join

A single `SELECT competitors JOIN facebook_pages` would be one query, and it would
also multiply rows: a competitor with three Pages comes back three times, and
assembling that into a nested structure in Python means re-grouping a result the
database already de-normalised for us. Two batched queries -- all competitors, then
all their Pages -- read each table once and never multiply anything.

`ix_facebook_pages_competitor_id` serves the second query. It has existed since S1.1,
and its own comment says it exists for the reverse lookup this module performs.

## Ordering is deterministic or it is a bug

`competitors.name` is **not unique** -- `models/tracking.py` says so outright, and
adds that a competitor is identified by its id and never by its name. An ORDER BY on
name alone would therefore be arbitrary among ties, and two requests could return two
different directories. Every ordering here ends with the unique `id`.

The same applies to `facebook_pages.name`, which is additionally **nullable**, so it
carries an explicit `NULLS LAST`: a Page whose provider reported no name belongs at
the end of its competitor's list, not the beginning, where it would push every named
Page down a line.

## Read-only in fact, not just in intent

Nothing here writes, and nothing here calls anything that could. That is worth
stating because `models/tracking.py` carries `RESTRICT` foreign keys precisely so
this data cannot be quietly deleted out from under its own history.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tracking import Competitor, FacebookPage


@dataclass(frozen=True, slots=True)
class CompetitorRecord:
    """One competitor and its Pages, already grouped.

    A plain dataclass rather than the ORM objects: the router must not reach into a
    lazy relationship and trigger a query per competitor, which is the N+1 this
    shape exists to prevent.
    """

    competitor: Competitor
    pages: tuple[FacebookPage, ...]


def list_competitors(session: Session) -> tuple[CompetitorRecord, ...]:
    """Every competitor, in a deterministic order, with its Pages pre-grouped.

    Returns:
        One record per competitor, ordered by name then id. A competitor with no
        Pages yields `pages == ()` -- it is present and visibly empty, never omitted.

    A competitor whose `name` ties with another's is separated by `id`, so two
    identical requests always return the identical directory.
    """
    competitors = (
        session.execute(select(Competitor).order_by(Competitor.name.asc(), Competitor.id.asc()))
        .scalars()
        .all()
    )

    if not competitors:
        return ()

    ids = [row.id for row in competitors]
    pages_by_competitor: dict[uuid.UUID, list[FacebookPage]] = {row_id: [] for row_id in ids}
    for page in session.execute(
        select(FacebookPage)
        .where(FacebookPage.competitor_id.in_(ids))
        .order_by(
            FacebookPage.name.asc().nulls_last(),
            FacebookPage.id.asc(),
        )
    ).scalars():
        pages_by_competitor[page.competitor_id].append(page)

    return tuple(
        CompetitorRecord(competitor=row, pages=tuple(pages_by_competitor[row.id]))
        for row in competitors
    )

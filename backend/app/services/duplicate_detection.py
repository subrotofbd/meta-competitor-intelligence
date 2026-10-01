"""Finding ads that share copy, or share creative assets.

## What a duplicate is here, and what it is not

A duplicate is **two different ads that hash alike**, not a value that must be
unique. This is the whole reason there is no `UNIQUE` constraint anywhere in
this module: two competitors running the identical offer is a *finding*, the
single most useful thing this product can surface about a competitor's strategy.
A uniqueness constraint would forbid exactly the observation worth having.

`content_hash` v1 already detects identical ads -- identical words, assets,
shape and platforms. S2.2's split exists to attribute a match to one of the two,
because "these two ads say the same thing" and "these two ads use the same
images" are different findings with different implications.

## Three rules the queries must not get wrong

**`IS NOT NULL` is mandatory.** `copy_hash` and `creative_hash` are nullable
because `ad_snapshots` is append-only: a row written before S2.2 can never be
backfilled, and an `UPDATE` is refused by the append-only trigger. Every such row
carries `NULL` in both columns. Grouping without the filter would place all of
them in a single NULL bucket and report every pre-S2.2 ad as a duplicate of
every other pre-S2.2 ad -- a spectacularly wrong answer that looks like a result.

**`count(DISTINCT ad_id) > 1`, never `count(*) > 1`.** One ad accumulates
snapshots over time -- that is what the history model is for -- so a single ad
with four snapshots has four rows sharing one hash. Counting rows would report
that ad as a duplicate of itself, on every collection, forever.

**Groups are not attributed to a competitor or a page.** Doing so needs
`seen_in_run` -> `collection_run` -> `facebook_page` -> `competitor`, a four-hop
join, and it is an API concern. Deferred deliberately: a duplicate group that
cannot yet say *whose* ad it is is still a correct answer to the question this
module asks, whereas a guessed attribution would not be.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdSnapshot

#: Which digest to group by. Both are handled by one implementation because
#: they differ only in the column, and a second implementation would be a second
#: place for the `IS NOT NULL` rule to be forgotten.
DuplicateAxis = Literal["copy", "creative"]

_COLUMNS: dict[DuplicateAxis, Any] = {
    "copy": AdSnapshot.copy_hash,
    "creative": AdSnapshot.creative_hash,
}


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """Ads that share one digest.

    Attributes:
        content_hash: The shared digest. This is the group's identity, and it is
            the value a reader can join on to reach the two ads.
        ad_ids: Every distinct ad in the group, deduplicated. An ad appears once
            however many snapshots it contributed, because the question is "how
            many ads share this copy", not "how many rows do".
    """

    content_hash: str
    ad_ids: tuple[uuid.UUID, ...]

    @property
    def ad_count(self) -> int:
        """How many *ads* are involved, which is the number worth showing."""
        return len(self.ad_ids)


def duplicate_groups(
    session: Session,
    *,
    axis: DuplicateAxis,
    limit: int | None = None,
) -> tuple[DuplicateGroup, ...]:
    """Ads sharing a copy digest or a creative digest.

    Args:
        session: The read session. Nothing is written.
        axis: `"copy"` to group by what the ads say, `"creative"` by what assets
            they use.
        limit: Cap on how many groups to return, largest first. A duplicate report
            is only useful while it is short, and an uncapped one over a large
            corpus is a full scan of the whole history.

    Returns:
        Groups of two or more distinct ads, largest first. Ties are broken by
        digest so the order is stable across calls -- an unstable ordering would
        make a paginated report reshuffle itself between pages.
    """
    column = _COLUMNS[axis]

    # The database does the filtering and the `DISTINCT`, so a large history is
    # never shipped to Python whole. Grouping by both columns reduces one ad's
    # many snapshots to one row per ad, which is what makes the `DISTINCT` count
    # below correct rather than a count of rows.
    distinct_pairs = (
        select(column.label("content_hash"), AdSnapshot.ad_id.label("ad_id"))
        # Mandatory: pre-S2.2 rows are NULL and would otherwise all group
        # together. See the module docstring.
        .where(column.is_not(None))
        .distinct()
        .subquery()
    )

    rows = session.execute(select(distinct_pairs.c.content_hash, distinct_pairs.c.ad_id)).all()

    grouped: dict[str, list[uuid.UUID]] = {}
    for digest, ad_id in rows:
        grouped.setdefault(str(digest), []).append(ad_id)

    groups = [
        DuplicateGroup(content_hash=digest, ad_ids=tuple(sorted(set(ad_ids))))
        for digest, ad_ids in grouped.items()
        # Two or more *distinct ads*. The `distinct()` above already collapsed an
        # ad's many snapshots to one row, so a single ad cannot produce two ids
        # here and can never qualify as its own duplicate.
        if len(set(ad_ids)) > 1
    ]
    groups.sort(key=lambda group: (-group.ad_count, group.content_hash))

    return tuple(groups[:limit] if limit is not None else groups)

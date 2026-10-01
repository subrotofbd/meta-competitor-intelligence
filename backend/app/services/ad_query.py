"""Reading ads for the API: filtering, ordering, paging, and batching.

## One row per ad, and why the status lives in a list

An ad is served on several Pages, in several countries, and S2.3 gives each
`(ad, Page, country)` context its **own independent** status. Flattening that to a
single `current_status` on the ad would be a false global claim -- the exact error
`AGENTS.md` section 7 warns about. So the list returns one row per ad with a
`contexts` array, and there is deliberately no ad-level status field to misread.

## No N+1, in four queries regardless of page size

A naive implementation asks for each ad's latest snapshot, contexts and media
separately: four-plus queries *per ad*, so a 100-row page is 400 queries. Instead:

1. one query pages `ads`, filtered and ordered, returning ids and identity columns;
2. one batched query fetches the latest snapshots for every id on the page;
3. one batched query fetches every context row for those ids;
4. one batched query fetches media references for those ids.

Four queries, whatever the page size. `total` adds a fifth, and only when the caller
asks for it.

## Duration needs a snapshot, and that is not optional

`meta_delivery_start` lives on `ad_snapshots`, not on `ads`, so the Ad Library's
longevity signal cannot be computed from the `ads` table alone. The latest snapshot
is therefore part of the page query rather than a detail-only extra -- and
`duration_of` is called **unchanged** from `services/ad_duration.py`, which already
takes `now` explicitly so a report stays reproducible.

## Ordering is deterministic or it is a bug

`last_seen_at` is advanced by `greatest(last_seen_at, now())` in a batch upsert, so
**many ads genuinely share a timestamp**. `ORDER BY last_seen_at DESC` alone is
therefore non-deterministic at a page boundary: the same page can return different
ads on two identical requests. Every ordering ends with `id`, which is unique.

Sort input is an **allowlist** mapped to SQLAlchemy expressions, never a string
interpolated into `ORDER BY`. The route parses the parameter; this module is the
only place a column can be chosen.

## NULL ordering is stated, not inherited

PostgreSQL's default is `NULLS FIRST` for `DESC` and `NULLS LAST` for `ASC`, which
is almost never what a reader wants. `meta_delivery_start` is the nullable column
here, and a null there means the provider reported no start -- so nulls go last on
every sort, explicitly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.ad_status import AD_STATUS_VALUES, AdStatusByContext
from app.models.ads import Ad, AdSnapshot
from app.models.analysis import AdAnalysis
from app.models.media import AdSnapshotMedia, MediaAsset
from app.models.tracking import FacebookPage
from app.providers.data.provenance import DataOrigin
from app.services.ad_duration import Duration, duration_of
from app.services.ad_search import (
    copy_tsvector,
    plainto_tsquery,
    trigram_match,
)

#: Hard ceiling on a page. A client asking for more gets the maximum, not an error:
#: the request was well formed, and refusing it would make a valid page size look
#: like a client bug.
MAX_PAGE_SIZE: Final = 100

#: The page size used when the caller does not ask for one. A grid shows a screenful,
#: not a table dump.
DEFAULT_PAGE_SIZE: Final = 25

#: The analysis contract this API serves. Pinned here so a v2 analysis arriving later
#: does not silently start answering v1 queries -- and so the join below is explicit
#: about which contract it matched.
ANALYSIS_VERSION: Final = "s3.1-analysis-v1"

SortField = Literal["last_seen_at", "first_seen_at", "meta_delivery_start", "meta_ad_id"]

#: The only orderings a caller may choose. A mapping, not a list, so an unlisted
#: value cannot reach SQL at all -- `resolve_sort` raises rather than falling back.
_SORT_COLUMNS: Final[dict[str, Any]] = {
    "last_seen_at": Ad.last_seen_at,
    "first_seen_at": Ad.first_seen_at,
    # Nullable: an ad whose provider reported no start date.
    "meta_delivery_start": AdSnapshot.meta_delivery_start,
    "meta_ad_id": Ad.meta_ad_id,
}

DEFAULT_SORT: Final = "last_seen_at"


def resolve_sort(field: str | None, direction: str | None) -> Any:
    """Turn allowlisted sort input into one SQLAlchemy ordering expression.

    Raises:
        ValueError: The field is not in the allowlist, or the direction is neither
            `asc` nor `desc`. A caller error, surfaced by the route as 400.
    """
    column_name = field or DEFAULT_SORT
    if column_name not in _SORT_COLUMNS:
        raise ValueError(f"unknown sort field {column_name!r}; allowed: {sorted(_SORT_COLUMNS)}")
    resolved = _SORT_COLUMNS[column_name]
    order = (direction or "desc").lower()
    if order not in ("asc", "desc"):
        raise ValueError(f"unknown sort direction {direction!r}; allowed: asc, desc")

    # Nulls last on both directions: a missing provider start date is an absence,
    # and an absence should not lead a sorted table.
    ordering = resolved.asc().nulls_last() if order == "asc" else resolved.desc().nulls_last()
    # The tie breaker, always, and always last. `id` is unique, so this is what makes
    # paging repeatable.
    return ordering, Ad.id.desc() if order == "desc" else Ad.id.asc()


@dataclass(frozen=True, slots=True)
class AdFilters:
    """Every filter `/ads` accepts, all optional.

    Deliberately absent: `platform`, `display_format`, `media_type`,
    `funnel_stage`, duration buckets, `language`, `confidence` and the hashes. Those
    live in JSONB or need an extra join, and each would need its own index and
    validation story. S3.2 ships the filters that map to real columns.
    """

    provider: str | None = None
    competitor_id: uuid.UUID | None = None
    country: str | None = None
    facebook_page_id: uuid.UUID | None = None
    current_status: str | None = None
    provider_active: bool | None = None
    data_origin: str | None = None
    first_seen_from: datetime | None = None
    first_seen_to: datetime | None = None
    last_seen_from: datetime | None = None
    last_seen_to: datetime | None = None
    q: str | None = None


@dataclass(frozen=True, slots=True)
class AdPage:
    """One page of ads.

    Attributes:
        items: The ads on this page, in the requested order.
        total: How many ads match the filter across all pages.
        page: Echoed back, 1-based.
        page_size: Echoed back, after the maximum was applied.
    """

    items: tuple[AdRecord, ...]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True, slots=True)
class AdRecord:
    """One ad with everything the list endpoint shows, assembled in Python.

    Assembled from four queries rather than one wide join because the relations are
    one-to-many; joining them all would multiply rows and corrupt the page. Keeping
    the assembly here means the router never touches SQL.
    """

    ad: Ad
    snapshot: AdSnapshot | None
    duration: Duration | None
    contexts: tuple[AdStatusByContext, ...]
    media: tuple[MediaAsset, ...]


def _search_condition(term: str) -> Any:
    """Match `term` against ad copy, returning a condition over `Ad.id`.

    Two strategies, OR-ed: full text for whole words, trigram for partial ones.
    A snapshot that matches resolves to its **ad**, and `DISTINCT` inside the
    subquery is what stops an ad with five matching snapshots from appearing five
    times.

    Ranking is applied by the caller's `ORDER BY` over the same expression; the
    default ordering (`last_seen_at DESC, id DESC`) governs the list, so relevance
    does not reorder a paged result set underneath the caller.
    """
    return (
        select(AdSnapshot.ad_id)
        .where(
            or_(
                copy_tsvector().op("@@")(plainto_tsquery(term)),
                trigram_match(term),
            )
        )
        .distinct()
    )


def _apply_filters(statement: Select[Any], filters: AdFilters) -> Select[Any]:
    """Narrow `statement` by every filter that was supplied.

    Context filters (`country`, `page`, `current_status`, `provider_active`) go
    through `ad_status_by_context`, and use `EXISTS` rather than a join so filtering
    by one context does not multiply the rows of a multi-context ad.
    """
    if filters.provider:
        statement = statement.where(Ad.provider == filters.provider)
    if filters.data_origin:
        statement = statement.where(Ad.data_origin == filters.data_origin)

    # Context filters. Each becomes an EXISTS subquery rather than a join, so
    # filtering by one context cannot multiply the rows of a multi-context ad --
    # a join would return the ad once per matching context and silently corrupt
    # `total` and the page boundaries.
    context_conditions = []
    if filters.country:
        context_conditions.append(AdStatusByContext.country == filters.country)
    if filters.facebook_page_id:
        context_conditions.append(AdStatusByContext.facebook_page_id == filters.facebook_page_id)
    if filters.current_status:
        context_conditions.append(AdStatusByContext.current_status == filters.current_status)
    if filters.provider_active is not None:
        # An explicit `true`/`false`, never "not null". Rounding the tri-state to a
        # boolean test would make "the provider said nothing" indistinguishable from
        # "the provider said no".
        context_conditions.append(AdStatusByContext.provider_active.is_(filters.provider_active))
    if context_conditions:
        statement = statement.where(
            exists(
                select(AdStatusByContext.id).where(
                    AdStatusByContext.ad_id == Ad.id,
                    and_(*context_conditions),
                )
            )
        )

    # A competitor filter needs one more hop: page -> competitor.
    if filters.competitor_id:
        statement = statement.where(
            exists(
                select(FacebookPage.id).where(
                    FacebookPage.id == AdStatusByContext.facebook_page_id,
                    AdStatusByContext.ad_id == Ad.id,
                    FacebookPage.competitor_id == filters.competitor_id,
                )
            )
        )
    if filters.first_seen_from:
        statement = statement.where(Ad.first_seen_at >= filters.first_seen_from)
    if filters.first_seen_to:
        statement = statement.where(Ad.first_seen_at <= filters.first_seen_to)
    if filters.last_seen_from:
        statement = statement.where(Ad.last_seen_at >= filters.last_seen_from)
    if filters.last_seen_to:
        statement = statement.where(Ad.last_seen_at <= filters.last_seen_to)

    if filters.q:
        statement = statement.where(Ad.id.in_(select(_search_condition(filters.q).c.ad_id)))

    return statement


def snapshot_platforms(snapshot: AdSnapshot | None) -> tuple[str, ...]:
    """The platforms a provider reported for one snapshot, in the stored order.

    Read from `normalized`, which already holds the full `RawAdRecord` -- so this adds
    no column, changes no hash, and rewrites no stored evidence. `normalized` is
    append-only and stays exactly as S2.1 wrote it.

    **Order is the provider's, not ours.** It is neither sorted nor de-duplicated:
    `creative_hash` sorts its keys before hashing precisely because order is *not*
    significant to identity, but the display order is still what the provider gave,
    and quietly re-sorting it would make the API disagree with the stored evidence.

    Returns:
        The reported platform names, or `()` when the snapshot has none or the value
        is not a list of strings. `()` means **"the stored record lists no
        platforms"**, which is not the same claim as "this ad ran on no platform" --
        a provider that reports nothing is recorded as nothing, never as "none".

    Only `str` members are taken. Anything else is skipped rather than coerced:
    `str(123)` would invent the platform name "123".
    """
    if snapshot is None:
        return ()
    normalized = snapshot.normalized if isinstance(snapshot.normalized, dict) else {}
    value = normalized.get("platforms")
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def matching_ad_ids(filters: AdFilters) -> Select[Any]:
    """The filtered ad-id query, as the single definition of "which ads match".

    Exposed because the CSV exporter needs to count the *contexts* belonging to the
    matching ads, not just the ads. Having one function build that subquery is what
    keeps the export's row count and its rows themselves in agreement -- restating the
    filter conditions in a second place is exactly how a preflight ends up counting a
    different set from the one that is exported.
    """
    return _apply_filters(select(Ad.id), filters)


def count_matching_ads(session: Session, filters: AdFilters) -> int:
    """How many ads match, without paging any of them."""
    return session.execute(
        select(func.count()).select_from(matching_ad_ids(filters).subquery())
    ).scalar_one()


def list_ads(
    session: Session,
    *,
    filters: AdFilters,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort: str | None = None,
    direction: str | None = None,
    now: datetime | None = None,
    with_media: bool = False,
) -> AdPage:
    """One page of ads, plus the total that match.

    Args:
        session: Read-only session. Nothing is written.
        filters: The requested filters. Unset filters are not applied.
        page: 1-based. Below 1 is clamped to 1 rather than rejected.
        page_size: Requested size, clamped to `MAX_PAGE_SIZE`.
        sort: Allowlisted field name. Raises `ValueError` on anything else.
        direction: `asc` or `desc`.
        now: Injected for a reproducible duration; defaults to the current UTC time.
        with_media: Whether to load media references. Off by default because the
            list is meant to stay lean.

    Raises:
        ValueError: The sort field or direction is not allowlisted.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    moment = now or datetime.now(UTC)
    ordering = resolve_sort(sort, direction)

    # No filter touches a snapshot column, so the total is the same whether or not
    # the page query needs the join for ordering. Computed once, from `ads` alone.
    total = session.execute(
        _apply_filters(select(func.count()).select_from(Ad), filters)
    ).scalar_one()

    # `meta_delivery_start` lives on the snapshot table, so sorting by it needs an
    # outer join. Every other sort is satisfied by `ads` and skips it.
    base = select(Ad)
    if (sort or DEFAULT_SORT) == "meta_delivery_start":
        base = base.outerjoin(AdSnapshot, Ad.latest_snapshot_id == AdSnapshot.id)
    base = _apply_filters(base, filters)

    rows = (
        session.execute(base.order_by(*ordering).limit(page_size).offset((page - 1) * page_size))
        .scalars()
        .all()
    )

    return AdPage(
        items=_assemble(session, list(rows), now=moment, with_media=with_media),
        total=total,
        page=page,
        page_size=page_size,
    )


def get_ad(
    session: Session,
    ad_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> AdRecord | None:
    """One ad with its latest snapshot, contexts and media, or `None`.

    A single ad justifies a single richer query, so this is allowed to be wider than
    the list path -- but it still assembles from batched reads rather than one
    N-row-multiplied join.
    """
    ad = session.get(Ad, ad_id)
    if ad is None:
        return None
    return _assemble(session, [ad], now=now or datetime.now(UTC), with_media=True)[0]


def _assemble(
    session: Session, ads: list[Ad], *, now: datetime, with_media: bool
) -> tuple[AdRecord, ...]:
    """Fill in every relation for a set of ads in a fixed number of queries.

    Three or four queries whatever `len(ads)` is. That is the entire point: the
    alternative is one query per relation per ad.
    """
    if not ads:
        return ()

    ids = [ad.id for ad in ads]
    by_id = {ad.id: ad for ad in ads}

    # 1. Latest snapshots, one query for the page.
    snapshots: dict[uuid.UUID, AdSnapshot] = {}
    latest_ids = [ad.latest_snapshot_id for ad in ads if ad.latest_snapshot_id is not None]
    if latest_ids:
        for row in session.execute(
            select(AdSnapshot).where(AdSnapshot.id.in_(latest_ids))
        ).scalars():
            snapshots[row.id] = row

    # 2. Contexts, one query for the page, ordered deterministically.
    contexts: dict[uuid.UUID, list[AdStatusByContext]] = {i: [] for i in ids}
    for context_row in session.execute(
        select(AdStatusByContext)
        .where(AdStatusByContext.ad_id.in_(ids))
        .order_by(
            AdStatusByContext.country,
            AdStatusByContext.facebook_page_id,
            AdStatusByContext.id,
        )
    ).scalars():
        contexts[context_row.ad_id].append(context_row)

    # 3. Media references, one query for the page. Only the *latest* snapshot's
    #    media is shown, because that is what the ad currently looks like; the full
    #    history belongs to the snapshots endpoint.
    media_by_ad: dict[uuid.UUID, list[MediaAsset]] = {i: [] for i in ids}
    if with_media:
        for ad_id, asset in session.execute(
            select(AdSnapshot.ad_id, MediaAsset)
            .join(AdSnapshotMedia, AdSnapshotMedia.media_asset_id == MediaAsset.id)
            .join(AdSnapshot, AdSnapshot.id == AdSnapshotMedia.ad_snapshot_id)
            .where(AdSnapshot.id.in_(latest_ids))
            .order_by(AdSnapshotMedia.position, MediaAsset.provider_key, MediaAsset.id)
        ):
            media_by_ad[ad_id].append(asset)

    records: list[AdRecord] = []
    for ad_id in ids:
        ad = by_id[ad_id]
        snapshot = snapshots.get(ad.latest_snapshot_id) if ad.latest_snapshot_id else None
        duration = (
            duration_of(
                meta_delivery_start=snapshot.meta_delivery_start,
                first_seen_at=ad.first_seen_at,
                now=now,
            )
            if snapshot is not None
            else None
        )
        records.append(
            AdRecord(
                ad=ad,
                snapshot=snapshot,
                duration=duration,
                contexts=tuple(contexts[ad_id]),
                media=tuple(media_by_ad[ad_id]),
            )
        )
    return tuple(records)


def analysis_for(
    session: Session, copy_hashes: list[str], *, analysis_version: str = ANALYSIS_VERSION
) -> dict[str, AdAnalysis]:
    """Analyses for a set of copy hashes, keyed by `copy_hash`.

    Joined on `copy_hash` and **not** on `source_ad_snapshot_id`: analysis is
    copy-scoped and reusable, so an ad that shares copy with an ad analysed yesterday
    resolves to that analysis. Joining through the source snapshot would hide it from
    every other ad running the same words, which defeats the reuse S3.1 exists to
    provide.

    `copy_hash` is `NOT NULL` on the table, so an empty input means nothing to look up.
    """
    if not copy_hashes:
        return {}
    return {
        row.copy_hash: row
        for row in session.execute(
            select(AdAnalysis).where(
                AdAnalysis.copy_hash.in_(copy_hashes),
                AdAnalysis.analysis_version == analysis_version,
            )
        ).scalars()
    }


def validate_status(value: str) -> str:
    """Check a `current_status` filter against the shipped vocabulary.

    Raises:
        ValueError: Not one of the three S2.3 states. A caller error, surfaced as 400.
    """
    if value not in AD_STATUS_VALUES:
        raise ValueError(f"unknown status {value!r}; allowed: {list(AD_STATUS_VALUES)}")
    return value


def validate_data_origin(value: str) -> str:
    """Check a `data_origin` filter against the shipped vocabulary.

    Raises:
        ValueError: Not a `DataOrigin` member.
    """
    try:
        return DataOrigin(value).value
    except ValueError as error:
        raise ValueError(
            f"unknown data_origin {value!r}; allowed: {[o.value for o in DataOrigin]}"
        ) from error


def validate_country(value: str) -> str:
    """Check a country filter: exactly two characters, upper-cased.

    The column's `CHECK` already enforces ISO alpha-2 at the database; this gives a
    400 with a useful message instead of a 500 or an empty page.
    """
    normalised = value.strip().upper()
    if len(normalised) != 2 or not normalised.isalpha():
        raise ValueError(f"country must be a two-letter ISO alpha-2 code, got {value!r}")
    return normalised

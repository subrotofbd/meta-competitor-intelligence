"""Turning query records into API responses.

## This layer is thin on purpose

`api/__init__.py` sets the rule: parse and validate, delegate to `services`,
serialise. There is **no SQL in this file** and no business decision either -- every
filter, ordering and join lives in `services/ad_query.py`, so the HTTP surface can
change without touching query semantics and vice versa.

The one judgement this layer does make is what to *not* send, and that is mostly
subtraction: `raw_ref`, queue ids, prompts, raw model responses, `storage_key` and
internal error text are simply absent from the response models, so forgetting to
exclude one is a schema change rather than a silent leak.

## Status is per context, and that is the shape

`contexts: [...]`, always a list, never a single ad-level `current_status`. An ad
served on three pages in two countries has up to six independent conclusions, and a
scalar would have to assert one of them falsely.

## Nothing here triggers work

Every route is a `GET`. No route calls `AIProvider`, enqueues a job, fetches media,
or writes anything. Analysis is *surfaced* here, never *caused* -- a page view must
not be able to spend money or start a collection because someone refreshed a grid.

## Filter errors are 400, not 422

A well-formed request naming a filter value that does not exist is a caller error,
and `422` is reserved for a request FastAPI could not parse at all. The distinction
is kept because a client that sees 422 retries the same request forever.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models.ad_status import AD_STATUS_VALUES
from app.models.ads import Ad, AdSnapshot
from app.models.analysis import AdAnalysis
from app.models.media import AdSnapshotMedia, MediaAsset
from app.providers.data.provenance import DataOrigin
from app.schemas.ads import (
    AdDetailOut,
    AdListItemOut,
    AdListOut,
    AnalysisOut,
    ContextOut,
    CopyFieldsOut,
    DurationOut,
    MediaReferenceOut,
    SnapshotListItemOut,
    SnapshotListOut,
    SnapshotSummaryOut,
)
from app.services.ad_csv import (
    MAX_EXPORT_ROWS,
    CsvExportTooLarge,
    count_export_rows,
    stream_ads_csv,
)
from app.services.ad_query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AdFilters,
    AdPage,
    AdRecord,
    analysis_for,
    get_ad,
    list_ads,
    snapshot_platforms,
    validate_country,
    validate_data_origin,
    validate_status,
)
from app.services.ad_search import normalise_query

#: All-null copy fields, for the unreachable branch where a row somehow has no
#: document. Explicit rather than `or`-chained so the fallback is visible.
_EMPTY_COPY = CopyFieldsOut(
    primary_text=None, headline=None, description=None, cta=None, destination_url=None
)

router = APIRouter(tags=["ads"])

SessionDep = Annotated[Session, Depends(get_session)]


# ============================================================
# Serialisation
# ============================================================


def _duration_out(record: AdRecord) -> DurationOut | None:
    if record.duration is None:
        # No latest snapshot yet, so there is nothing to measure a duration from.
        # Not a zero -- a zero would claim the ad started today.
        return None
    return DurationOut(
        days=record.duration.days,
        bucket=record.duration.bucket,
        source=record.duration.source,
        is_long_running_signal=record.duration.is_long_running_signal,
    )


def _snapshot_out(snapshot: AdSnapshot | None) -> SnapshotSummaryOut | None:
    if snapshot is None:
        return None
    return SnapshotSummaryOut(
        id=snapshot.id,
        created_at=snapshot.created_at,
        content_hash=snapshot.content_hash,
        copy_hash=snapshot.copy_hash,
        creative_hash=snapshot.creative_hash,
        ad_status=snapshot.ad_status,
        meta_delivery_start=snapshot.meta_delivery_start,
    )


def _contexts_out(record: AdRecord) -> tuple[ContextOut, ...]:
    return tuple(
        ContextOut(
            facebook_page_id=context.facebook_page_id,
            country=context.country,
            current_status=context.current_status,
            # Tri-state, passed straight through. `None` means the provider said
            # nothing, and rounding it to False would invent a finding.
            provider_active=context.provider_active,
            not_seen_since_at=context.not_seen_since_at,
            last_status_run_id=context.last_status_run_id,
        )
        for context in record.contexts
    )


def _media_out(record: AdRecord) -> tuple[MediaReferenceOut, ...]:
    return tuple(
        MediaReferenceOut(
            provider=asset.provider,
            provider_key=asset.provider_key,
            source_url=asset.source_url,
            mime=asset.mime,
            width=asset.width,
            height=asset.height,
            duration_seconds=asset.duration_seconds,
            first_seen_at=asset.first_seen_at,
            last_seen_at=asset.last_seen_at,
        )
        for asset in record.media
    )


def _copy_fields_out(snapshot: AdSnapshot | None) -> CopyFieldsOut | None:
    """Read the four copy fields out of `normalized`.

    `normalized` is the append-only evidence and is never rewritten; this reads it as
    stored. A snapshot predating nothing still has the key present with a null value,
    which is "not reported" rather than "missing document".
    """
    if snapshot is None:
        return None
    normalized = snapshot.normalized if isinstance(snapshot.normalized, dict) else {}

    def text(key: str) -> str | None:
        value = normalized.get(key)
        return value if isinstance(value, str) else None

    return CopyFieldsOut(
        primary_text=text("primary_text"),
        headline=text("headline"),
        description=text("description"),
        cta=text("cta"),
        destination_url=text("destination_url"),
    )


def _analysis_out(analysis: AdAnalysis | None) -> AnalysisOut | None:
    """Serialise an analysis, or `None` when there is not one.

    The fourteen fields go out as a mapping rather than fourteen typed columns: they
    are versioned model output, and flattening them here would freeze v1's field set
    into this API's contract when a v2 is already anticipated.

    `source_snapshot_id` is reported because analysis is copy-scoped -- the analysis a
    client is reading may have been produced from a *different* ad's snapshot, and
    saying so is more honest than implying this ad generated it.
    """
    if analysis is None:
        return None
    fields = {
        name: getattr(analysis, name)
        for name in (
            "hook",
            "problem",
            "promise",
            "offer",
            "cta",
            "persona",
            "pain_point",
            "angle",
            "proof",
            "urgency",
            "awareness_level",
            "funnel_stage",
            "copy_structure",
            "why_it_may_work",
        )
    }
    return AnalysisOut(
        copy_hash=analysis.copy_hash,
        analysis_version=analysis.analysis_version,
        prompt_version=analysis.prompt_version,
        provider=analysis.provider,
        model=analysis.model,
        language=analysis.language,
        confidence=analysis.confidence,
        interpretation=fields,
        source_snapshot_id=analysis.source_ad_snapshot_id,
        created_at=analysis.created_at,
    )


def _list_item_out(record: AdRecord) -> AdListItemOut:
    return AdListItemOut(
        id=record.ad.id,
        provider=record.ad.provider,
        meta_ad_id=record.ad.meta_ad_id,
        data_origin=DataOrigin(record.ad.data_origin),
        first_seen_at=record.ad.first_seen_at,
        last_seen_at=record.ad.last_seen_at,
        latest_snapshot=_snapshot_out(record.snapshot),
        duration=_duration_out(record),
        contexts=_contexts_out(record),
        media=_media_out(record),
        platforms=snapshot_platforms(record.snapshot),
    )


# ============================================================
# Query parameters
# ============================================================


def _filters(
    provider: str | None,
    competitor_id: uuid.UUID | None,
    country: str | None,
    facebook_page_id: uuid.UUID | None,
    current_status: str | None,
    provider_active: bool | None,
    data_origin: str | None,
    first_seen_from: datetime | None,
    first_seen_to: datetime | None,
    last_seen_from: datetime | None,
    last_seen_to: datetime | None,
    q: str | None,
) -> AdFilters:
    """Validate and normalise every filter, raising 400 on a bad value.

    Validating here rather than letting the query fail means a typo produces a
    message naming the field and its allowed values, instead of an empty page that
    reads as "no ads matched".
    """
    try:
        return AdFilters(
            provider=provider,
            competitor_id=competitor_id,
            country=validate_country(country) if country else None,
            facebook_page_id=facebook_page_id,
            current_status=validate_status(current_status) if current_status else None,
            # Tri-state survives the trip: absent stays `None`, so no filter.
            provider_active=provider_active,
            data_origin=validate_data_origin(data_origin) if data_origin else None,
            first_seen_from=first_seen_from,
            first_seen_to=first_seen_to,
            last_seen_from=last_seen_from,
            last_seen_to=last_seen_to,
            q=normalise_query(q),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


# ============================================================
# Routes
# ============================================================


@router.get("/ads", response_model=AdListOut, summary="List ads")
def get_ads(
    session: SessionDep,
    provider: Annotated[str | None, Query(description="Provider name, exact match")] = None,
    competitor_id: Annotated[uuid.UUID | None, Query()] = None,
    country: Annotated[str | None, Query(description="ISO alpha-2, e.g. IN")] = None,
    facebook_page_id: Annotated[uuid.UUID | None, Query()] = None,
    current_status: Annotated[
        str | None, Query(description=f"One of: {', '.join(AD_STATUS_VALUES)}")
    ] = None,
    provider_active: Annotated[
        bool | None,
        Query(description="Tri-state filter. Omit for 'any'; null is never rounded to false."),
    ] = None,
    data_origin: Annotated[
        str | None, Query(description=f"One of: {', '.join(o.value for o in DataOrigin)}")
    ] = None,
    first_seen_from: Annotated[datetime | None, Query()] = None,
    first_seen_to: Annotated[datetime | None, Query()] = None,
    last_seen_from: Annotated[datetime | None, Query()] = None,
    last_seen_to: Annotated[datetime | None, Query()] = None,
    q: Annotated[str | None, Query(description="Full text and partial copy search")] = None,
    page: Annotated[int, Query(ge=1, description="1-based")] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    sort: Annotated[str | None, Query(description="Allowlisted field name")] = None,
    direction: Annotated[str | None, Query(pattern="^(asc|desc)$")] = None,
) -> AdListOut:
    """One page of ads, newest observation first.

    There is deliberately no ad-level `current_status`: status belongs to an
    `(ad, Page, country)` context and is returned in `contexts`.

    A `page` past the end returns `items: []` with the true `total` -- the request was
    well formed, there is simply nothing there.
    """
    filters = _filters(
        provider,
        competitor_id,
        country,
        facebook_page_id,
        current_status,
        provider_active,
        data_origin,
        first_seen_from,
        first_seen_to,
        last_seen_from,
        last_seen_to,
        q,
    )
    try:
        page_result: AdPage = list_ads(
            session,
            filters=filters,
            page=page,
            page_size=page_size,
            sort=sort,
            direction=direction,
            # The list shows creatives. `with_media` is off by default in the
            # service, so it is asked for explicitly here rather than defaulting
            # to an always-empty array in the response.
            with_media=True,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return AdListOut(
        items=tuple(_list_item_out(record) for record in page_result.items),
        total=page_result.total,
        page=page_result.page,
        page_size=page_result.page_size,
    )


@router.get("/ads/{ad_id}", response_model=AdDetailOut, summary="One ad in full")
def get_one_ad(ad_id: uuid.UUID, session: SessionDep) -> AdDetailOut:
    """Identity, current observation, duration, every status context, the copy, the
    AI interpretation, and media references.

    Internal identifiers are absent by construction: `raw_ref`, queue ids, prompts,
    raw model responses and `storage_key` are not in the response model.
    """
    record = get_ad(session, ad_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"ad {ad_id} not found")

    analysis = (
        None
        if record.snapshot is None or record.snapshot.copy_hash is None
        else analysis_for(session, [record.snapshot.copy_hash]).get(record.snapshot.copy_hash)
    )
    return AdDetailOut(
        id=record.ad.id,
        provider=record.ad.provider,
        meta_ad_id=record.ad.meta_ad_id,
        data_origin=DataOrigin(record.ad.data_origin),
        first_seen_at=record.ad.first_seen_at,
        last_seen_at=record.ad.last_seen_at,
        latest_snapshot=_snapshot_out(record.snapshot),
        duration=_duration_out(record),
        contexts=_contexts_out(record),
        copy_fields=_copy_fields_out(record.snapshot),
        analysis=_analysis_out(analysis),
        media=_media_out(record),
        platforms=snapshot_platforms(record.snapshot),
    )


@router.get(
    "/ads/{ad_id}/snapshots",
    response_model=SnapshotListOut,
    summary="One ad's observation history",
)
def get_ad_snapshots(
    ad_id: uuid.UUID,
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> SnapshotListOut:
    """Every observation we hold for this ad, newest first.

    Read-only by construction. `ad_snapshots` is append-only and its trigger would
    refuse a write, but nothing here writes regardless -- and no hash is recomputed,
    so a `copy_hash` written before S2.2 stays `null` rather than being invented.
    """
    if session.get(Ad, ad_id) is None:
        raise HTTPException(status_code=404, detail=f"ad {ad_id} not found")

    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))

    total = session.query(AdSnapshot).filter(AdSnapshot.ad_id == ad_id).count()
    rows: list[AdSnapshot] = (
        session.query(AdSnapshot)
        .filter(AdSnapshot.ad_id == ad_id)
        # `id` as the tie breaker for the same reason as everywhere else: several
        # snapshots can share a `created_at` within one transaction.
        .order_by(AdSnapshot.created_at.desc(), AdSnapshot.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
        .all()
    )

    media_by_snapshot = _media_for_snapshots(session, [row.id for row in rows])
    items = tuple(
        SnapshotListItemOut(
            id=row.id,
            created_at=row.created_at,
            collection_run_id=row.collection_run_id,
            content_hash=row.content_hash,
            copy_hash=row.copy_hash,
            creative_hash=row.creative_hash,
            ad_status=row.ad_status,
            meta_delivery_start=row.meta_delivery_start,
            # `row` is a real snapshot, so this is never the `None` branch.
            copy_fields=_copy_fields_out(row) or _EMPTY_COPY,
            media=media_by_snapshot.get(row.id, ()),
            analysis_copy_hash=row.copy_hash,
            platforms=snapshot_platforms(row),
        )
        for row in rows
    )
    return SnapshotListOut(items=items, total=total, page=page, page_size=page_size)


def _media_for_snapshots(
    session: Session, snapshot_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[MediaReferenceOut, ...]]:
    """Media for a page of snapshots, in one query.

    Batched rather than per snapshot -- the same N+1 rule the list endpoint follows.
    An empty page short-circuits, because `IN ()` is valid but pointless.
    """
    if not snapshot_ids:
        return {}
    rows = session.execute(
        select(AdSnapshotMedia.ad_snapshot_id, MediaAsset)
        .join(MediaAsset, MediaAsset.id == AdSnapshotMedia.media_asset_id)
        .where(AdSnapshotMedia.ad_snapshot_id.in_(snapshot_ids))
        .order_by(AdSnapshotMedia.ad_snapshot_id, AdSnapshotMedia.position, MediaAsset.provider_key)
    ).all()

    found: dict[uuid.UUID, list[MediaReferenceOut]] = {}
    for snapshot_id, asset in rows:
        found.setdefault(snapshot_id, []).append(
            MediaReferenceOut(
                provider=asset.provider,
                provider_key=asset.provider_key,
                source_url=asset.source_url,
                mime=asset.mime,
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                first_seen_at=asset.first_seen_at,
                last_seen_at=asset.last_seen_at,
            )
        )
    return {key: tuple(value) for key, value in found.items()}


@router.get("/exports/ads.csv", summary="Export filtered ads as CSV")
def export_ads_csv(
    session: SessionDep,
    provider: str | None = None,
    competitor_id: uuid.UUID | None = None,
    country: str | None = None,
    facebook_page_id: uuid.UUID | None = None,
    current_status: str | None = None,
    provider_active: bool | None = None,
    data_origin: str | None = None,
    first_seen_from: datetime | None = None,
    first_seen_to: datetime | None = None,
    last_seen_from: datetime | None = None,
    last_seen_to: datetime | None = None,
    q: str | None = None,
) -> StreamingResponse:
    """The same filters as `/ads`, as CSV. One row per ad **per context**.

    A CSV cannot nest, and flattening status to one column would be the same
    false-global-status error the JSON shape avoids -- so a multi-context ad gets one
    row per context and a context-free ad gets one row with empty context columns.

    Accepts **every** filter `/ads` accepts, including the four observation-date
    ranges, so "export what I filtered" is literally true rather than nearly true.
    The date parameters are the fix for a docstring that claimed parity while
    dropping four of them -- the claim was not weakened, the code caught up.

    The cap is decided **before** the response starts. `count_export_rows` is a plain
    function precisely so that: `StreamingResponse` commits the status line and the
    headers before it iterates anything, so a check inside the body generator would
    arrive too late to answer with a 413, and the caller would be left holding a
    truncated file under a 200. Nothing is buffered to achieve this -- normal exports
    are still streamed row by row.
    """
    filters = _filters(
        provider,
        competitor_id,
        country,
        facebook_page_id,
        current_status,
        provider_active,
        data_origin,
        first_seen_from,
        first_seen_to,
        last_seen_from,
        last_seen_to,
        q,
    )
    try:
        # Deliberately outside the generator. Three count queries, before any byte is
        # sent -- the price of a 413 that arrives while it can still change the status.
        count_export_rows(session, filters=filters, max_rows=MAX_EXPORT_ROWS)
    except CsvExportTooLarge as error:
        # 413 rather than a silently truncated file: a partial export looks exactly
        # like a complete one, which is the worst thing to hand someone.
        raise HTTPException(status_code=413, detail=str(error)) from error
    return StreamingResponse(
        stream_ads_csv(session, filters=filters, max_rows=MAX_EXPORT_ROWS),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="ads.csv"'},
    )

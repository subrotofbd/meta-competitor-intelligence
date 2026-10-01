"""Streaming the ad list out as CSV.

## Why this is a service and not a route concern

Formula-injection defence, NULL rendering and the row cap are all rules about *how
data leaves this product*. Putting them in the router would make them a formatting
detail that a future route could forget, and the failure is silent: a spreadsheet
quietly executing a competitor's `=cmd|...`.

## One row per ad **per context**

A CSV has no way to nest. An ad served on three pages in two countries has up to six
independent status conclusions (S2.3), and flattening them into one column would
assert something the product does not know. So each context gets a row, and an ad
with no context still gets one row with the context columns left empty -- silently
dropping such an ad would be worse than an obviously-blank context.

## Formula injection: the rule, and why it is a rule

Any cell beginning with `=`, `+`, `-`, `@`, TAB or CR is prefixed with a single
quote.

**Why this is necessary:** provider ad copy is untrusted input, and it very often
begins with `-` (a bullet) or `+`. Opened in Excel or Sheets, such a cell is a
formula. `-2+3+cmd|' /C calc'!A0` in an ad's headline is a real payload shape, not a
hypothetical one.

**What it costs:** the exported cell then differs from the source by one leading
character. That is the deliberate trade. Stripping the character would corrupt data
and mean two different values; the single quote is a marker that spreadsheet
software understands as "this is text", and it is the convention every serious CSV
exporter uses. It is documented here and in `ARCHITECTURE.md` rather than chosen
silently.

## NULL is an empty cell

Never `0`, never `NULL`, never `N/A`. `AGENTS.md` section 7 requires absence to stay
absence, and a numeric zero in a duration column would be a measurement nobody took.

## The cap is a refusal, not a truncation

Above `MAX_EXPORT_ROWS` the export raises `CsvExportTooLarge`, which the route turns
into a **413**. A truncated file is indistinguishable from a complete one, and
someone will act on it.

## No internal anything

No `raw_ref`, no queue ids, no prompts, no raw model responses, no credentials, and
no performance metrics -- none of which exist to export in the first place.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

from sqlalchemy.orm import Session

from app.models.ad_status import AdStatusByContext
from app.models.analysis import AdAnalysis
from app.services.ad_query import (
    MAX_PAGE_SIZE,
    AdFilters,
    AdRecord,
    analysis_for,
    list_ads,
)

#: Hard ceiling on exported rows. Every ad with a context produces several rows, so
#: this bounds the *file*, which is what a reader has to open.
MAX_EXPORT_ROWS: Final = 50_000

#: The characters a spreadsheet treats as the start of a formula.
FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")

#: Columns, in order. Identity and provenance first, then observation, then status,
#: then duration, then interpretation, then media. A reader scanning left to right
#: meets "what is this" before "what do we think of it".
COLUMNS: Final[tuple[str, ...]] = (
    "ad_id",
    "provider",
    "meta_ad_id",
    "data_origin",
    "first_seen_at",
    "last_seen_at",
    "latest_snapshot_id",
    "meta_delivery_start",
    "content_hash",
    "copy_hash",
    "creative_hash",
    "context_page_id",
    "context_country",
    "current_status",
    "provider_active",
    "not_seen_since_at",
    "duration_days",
    "duration_bucket",
    "duration_source",
    "long_running_signal",
    "analysis_available",
    "analysis_evidence_class",
    "analysis_language",
    "analysis_confidence",
    "analysis_version",
    "media_provider_keys",
)


class CsvExportTooLarge(Exception):
    """The export would exceed `MAX_EXPORT_ROWS`.

    Raised rather than truncated: a partial export looks exactly like a complete one.
    """


def escape_cell(value: str | None) -> str | None:
    """Neutralise a leading formula character, or leave the value alone.

    Only the *first* character matters, and only when it is one of the six a
    spreadsheet treats as a formula. Everything else passes through byte for byte,
    because the alternative -- rewriting provider text to be "safe" -- would mean
    the export no longer showed what the competitor ran.
    """
    if value is None:
        return None
    if value[:1] in FORMULA_PREFIXES:
        return f"'{value}"
    return value


def render_timestamp(value: datetime | None) -> str | None:
    """ISO-8601 in UTC, so a spreadsheet and an API agree on what a timestamp is.

    Naive values are *assumed* UTC rather than localised: every timestamp this
    product stores comes from `now()` in PostgreSQL, and converting would introduce
    a timezone claim the value does not make.
    """
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


def render_cell(value: object) -> str | None:
    """Any value to a CSV cell, with NULL as an empty cell and no invented zeros."""
    if value is None:
        return None
    if isinstance(value, bool):
        # Tri-state `provider_active` reaches here as True, False or None; the last
        # becomes an empty cell and never the string "False".
        return "true" if value else "false"
    if isinstance(value, datetime):
        return render_timestamp(value)
    if isinstance(value, (int, float)):
        return str(value)
    return escape_cell(str(value))


def iter_export_rows(
    session: Session, *, filters: AdFilters, max_rows: int = MAX_EXPORT_ROWS
) -> Iterator[list[str | None]]:
    """Yield one row per ad per context, paging internally.

    Pages in `MAX_PAGE_SIZE` chunks rather than loading everything, so the memory
    cost is bounded by the page and not by the corpus. `total` is read first so the
    cap can be refused *before* any work is done, which is what makes a 413 cheap.
    """
    first = list_ads(session, filters=filters, page=1, page_size=MAX_PAGE_SIZE, with_media=True)
    if first.total > max_rows:
        raise CsvExportTooLarge(
            f"export would contain {first.total} ads, above the {max_rows} row limit; "
            f"narrow the filters or use the API's paging"
        )

    analyses = _analyses_for(session, list(first.items))

    page = 1
    emitted = 0
    while True:
        result = (
            first
            if page == 1
            else list_ads(
                session,
                filters=filters,
                page=page,
                page_size=MAX_PAGE_SIZE,
                with_media=True,
            )
        )
        if not result.items:
            return
        for record in result.items:
            analysis = (
                analyses.get(record.snapshot.copy_hash)
                if record.snapshot is not None and record.snapshot.copy_hash
                else None
            )
            duration = record.duration
            snapshot = record.snapshot
            ad = record.ad
            # A context-free ad still gets a row, with blank context columns. Dropping
            # it would hide an ad that exists.
            # An ad with no context still gets a row with blank context columns:
            # dropping it would hide an ad that exists. `context_rows` is a list of
            # "no context" placeholders rather than a sentinel inside the tuple.
            context_rows: list[AdStatusByContext | None] = list(record.contexts) or [None]
            for context in context_rows:
                emitted += 1
                if emitted > max_rows:
                    raise CsvExportTooLarge(f"export exceeded {max_rows} rows")
                yield [
                    render_cell(str(ad.id)),
                    render_cell(ad.provider),
                    # `meta_ad_id` is provider text and can begin with a formula
                    # character, so it goes through the same escape as copy.
                    render_cell(ad.meta_ad_id),
                    render_cell(str(ad.data_origin)),
                    render_timestamp(ad.first_seen_at),
                    render_timestamp(ad.last_seen_at),
                    render_cell(str(snapshot.id) if snapshot is not None else None),
                    render_timestamp(snapshot.meta_delivery_start if snapshot else None),
                    render_cell(snapshot.content_hash if snapshot else None),
                    render_cell(snapshot.copy_hash if snapshot else None),
                    render_cell(snapshot.creative_hash if snapshot else None),
                    render_cell(str(context.facebook_page_id) if context is not None else None),
                    render_cell(context.country if context is not None else None),
                    render_cell(context.current_status if context is not None else None),
                    render_cell(context.provider_active if context is not None else None),
                    render_timestamp(context.not_seen_since_at if context else None),
                    render_cell(duration.days if duration else None),
                    render_cell(duration.bucket.value if duration else None),
                    render_cell(duration.source.value if duration else None),
                    render_cell(duration.is_long_running_signal if duration else None),
                    render_cell(analysis is not None),
                    # The badge travels with the data rather than living in a UI
                    # convention, so an exported cell cannot be read as provider data.
                    render_cell("AI_INTERPRETATION" if analysis is not None else None),
                    render_cell(analysis.language if analysis else None),
                    render_cell(analysis.confidence if analysis else None),
                    render_cell(analysis.analysis_version if analysis else None),
                    render_cell(
                        "|".join(sorted(asset.provider_key for asset in record.media)) or None
                    ),
                ]
        page += 1


def _analyses_for(session: Session, records: list[AdRecord]) -> dict[str, AdAnalysis]:
    """Analyses for one page of records, in a single query.

    The `copy_hash` comes from the snapshot `_assemble` already loaded, so nothing
    here re-queries per ad -- an earlier draft did, which is the N+1 this checkpoint
    exists to avoid.

    Joined on `copy_hash`, not on the source snapshot: analysis is copy-scoped, so an
    ad sharing copy with an analysed ad resolves to that analysis.
    """
    hashes = [
        record.snapshot.copy_hash
        for record in records
        if record.snapshot is not None and record.snapshot.copy_hash
    ]
    if not hashes:
        return {}
    return analysis_for(session, list(set(hashes)))


def stream_ads_csv(
    session: Session, *, filters: AdFilters, max_rows: int = MAX_EXPORT_ROWS
) -> Iterator[str]:
    """The whole file as a stream of text chunks.

    Header always present, even for zero rows -- a headerless empty file is
    indistinguishable from a failed download.
    """
    yield _render_header()
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    for row in iter_export_rows(session, filters=filters, max_rows=max_rows):
        writer.writerow(["" if value is None else value for value in row])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def _render_header() -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow(COLUMNS)
    return buffer.getvalue()

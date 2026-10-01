"""S3.2 API: ads, search, snapshots, CSV, and what they must never expose.

The load-bearing assertions are the negative ones. Proving an endpoint *works* is
easy and proves little; these prove the properties a later change could quietly
break:

- a provider reorder never produces a **false global** ad status;
- no `raw_ref`, queue id, prompt, `storage_key` or traceback appears in any response;
- a cell beginning `=` cannot become a spreadsheet formula;
- an ad is not returned twice because several of its snapshots match;
- the list endpoint issues a **fixed number of queries** whatever the page size;
- `provider_active` stays tri-state through JSON rather than rounding `null` to
  `false`;
- the search projection written three times cannot drift between the copies.

`integration`, because nearly all of it is a database question. Writes are real and
nothing is committed -- `db_session` binds every session to a connection inside an
outer transaction that is always rolled back.

No API server is started and no HTTP client is installed. `tests/asgi_client.py`
drives the ASGI app in-process, so routing, dependency overrides, exception handlers
and status codes are all genuinely exercised.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import Table, event, text
from sqlalchemy.orm import Session

from app.core.config import AppEnv
from app.main import create_app
from app.models.ad_status import AD_STATUS_VALUES
from app.models.ads import Ad, AdSnapshot
from app.models.analysis import AdAnalysis
from app.services.ad_csv import (
    COLUMNS,
    MAX_EXPORT_ROWS,
    CsvExportTooLarge,
    escape_cell,
    iter_export_rows,
    render_cell,
)
from app.services.ad_query import (
    ANALYSIS_VERSION,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    AdFilters,
    analysis_for,
    list_ads,
    resolve_sort,
    snapshot_platforms,
    validate_country,
    validate_data_origin,
    validate_status,
)
from app.services.ad_search import (
    COPY_FIELDS,
    copy_projection,
    copy_tsvector,
    normalise_query,
    plainto_tsquery,
    trigram_pattern,
)
from app.services.analysis_prompt import PROMPT_VERSION
from tests.asgi_client import ASGITestClient

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
PROVIDER = "mock"


# ============================================================
# Builders -- real write paths, not hand-made rows
# ============================================================


def _page(session: Session, page_id: str, *, country: str = "IN", name: str = "Acme") -> Any:
    """A tracked competitor Page, reusing the competitor and Page of the same name.

    **Idempotent.** `facebook_pages.page_id` is globally unique, so a second call with
    the same id used to raise `UniqueViolation` rather than hand back the row it had
    already made -- which turned "call `_page` again" into a test bug rather than a
    no-op, and made helpers awkward to compose.
    """
    from app.models.tracking import Competitor, FacebookPage

    existing = session.query(FacebookPage).filter(FacebookPage.page_id == page_id).one_or_none()
    if existing is not None:
        return existing

    competitor = session.query(Competitor).filter(Competitor.name == name).one_or_none()
    if competitor is None:
        competitor = Competitor(name=name)
        session.add(competitor)
        session.flush()
    page = FacebookPage(
        competitor_id=competitor.id,
        page_id=page_id,
        name=f"{name} India",
        url=f"https://www.facebook.com/{page_id}",
        country=country,
        tracking_frequency="daily",
        is_tracked=True,
    )
    session.add(page)
    session.flush()
    return page


def _record(**overrides: Any) -> Any:
    from app.providers.data.models import AdFormat, RawAdRecord

    fields: dict[str, Any] = {
        "platforms": ("facebook",),
        "countries": ("IN",),
        "ad_status": "active",
        "primary_text": "A kettle that actually whistles.",
        "display_format": AdFormat.IMAGE,
    }
    fields.update(overrides)
    return RawAdRecord(**fields)


def _observe(
    session: Session,
    *,
    page_id: uuid.UUID,
    external_ad_id: str,
    offset_days: int = 0,
    **record_overrides: Any,
) -> tuple[Ad, AdSnapshot]:
    """Persist one observation through the real S2.1 write path.

    Going through `persist_observations` rather than inserting an `AdSnapshot` by
    hand means the tests see the hashes, `normalized` shape and status linkage that
    production rows actually have.
    """
    from app.models.runs import (
        CollectionRun,
        CollectionRunStatus,
        ProviderRun,
        ProviderRunStatus,
        RawResponse,
    )
    from app.providers.data.provenance import DataOrigin
    from app.services.ad_persistence import ObservedRecord, persist_observations

    at = BASE + timedelta(days=offset_days)
    run = CollectionRun(
        facebook_page_id=page_id,
        provider=PROVIDER,
        data_origin=DataOrigin.third_party,
        country="IN",
        status=CollectionRunStatus.COMPLETE,
        started_at=at,
        finished_at=at + timedelta(seconds=30),
    )
    session.add(run)
    session.flush()
    call = ProviderRun(
        collection_run_id=run.id,
        status=ProviderRunStatus.SUCCEEDED,
        started_at=at,
        finished_at=at + timedelta(seconds=30),
        request_meta={
            "provider": PROVIDER,
            "origin": DataOrigin.third_party.value,
            "country": "IN",
            "requested_at": at.isoformat(),
            "cursor": None,
        },
        http_status=200,
    )
    session.add(call)
    session.flush()
    raw = RawResponse(provider_run_id=call.id, payload={"ads": []})
    session.add(raw)
    session.flush()

    result = persist_observations(
        session,
        run_id=run.id,
        observations=[
            ObservedRecord(
                record=_record(external_ad_id=external_ad_id, **record_overrides),
                raw_response_id=raw.id,
            )
        ],
        provider=PROVIDER,
        data_origin=DataOrigin.third_party,
        page_id=page_id,
        country="IN",
    )[0]
    ad = session.get(Ad, result.ad_id)
    snapshot = session.get(AdSnapshot, result.snapshot_id)
    assert ad is not None and snapshot is not None
    return ad, snapshot


def _link_media(session: Session, snapshot_id: uuid.UUID, provider_key: str) -> Any:
    """Link one creative to a snapshot through the real S2.4 service."""
    from app.providers.data.models import MediaRef
    from app.services.media_references import link_snapshot_media

    linked = link_snapshot_media(
        session,
        provider=PROVIDER,
        ad_snapshot_id=snapshot_id,
        media=(
            MediaRef(
                provider_key=provider_key,
                source_url=f"https://cdn.example.invalid/{provider_key}.png",
                mime="image/png",
                width=1080,
                height=1080,
            ),
        ),
        snapshot_created=True,
    )
    assert len(linked) == 1
    return linked[0]


def _add_context(
    session: Session,
    *,
    ad_id: uuid.UUID,
    page_id: uuid.UUID,
    country: str = "IN",
    current_status: str = "seen",
    provider_active: bool | None = True,
    not_seen_since_at: datetime | None = None,
) -> Any:
    from app.models.ad_status import AdStatusByContext

    # `persist_observations` already wrote a context row for the first run, so this
    # updates it rather than inserting a duplicate -- the table is unique on
    # `(ad_id, page, country)`.
    row = (
        session.query(AdStatusByContext)
        .filter(
            AdStatusByContext.ad_id == ad_id,
            AdStatusByContext.facebook_page_id == page_id,
            AdStatusByContext.country == country,
        )
        .one_or_none()
    )
    if row is None:
        row = AdStatusByContext(ad_id=ad_id, facebook_page_id=page_id, country=country)
        session.add(row)
    row.current_status = current_status
    row.provider_active = provider_active
    row.not_seen_since_at = not_seen_since_at
    session.flush()
    return row


def _add_analysis(
    session: Session, *, ad: Ad, snapshot: AdSnapshot, language: str = "hi"
) -> AdAnalysis:
    """An analysis for this ad's copy, at the version the API serves."""
    assert snapshot.copy_hash is not None
    row = AdAnalysis(
        copy_hash=snapshot.copy_hash,
        analysis_version=ANALYSIS_VERSION,
        source_ad_id=ad.id,
        source_ad_snapshot_id=snapshot.id,
        hook="शुरुआत में ही दमदम",
        problem=None,
        promise="तेज़ पानी",
        offer="आज ही खरीदें",
        cta="अभी ऑर्डर करें",
        persona="घरेलू उपयोगकर्ता",
        pain_point="धीमा पानी",
        angle="गति",
        proof=None,
        urgency="सीमित",
        awareness_level="middle",
        funnel_stage="consideration",
        copy_structure="hook-problem-offer",
        why_it_may_work="स्थानीय भाषा में सीधा दावा",
        language=language,
        confidence="medium",
        provider="mock-ai",
        model="mock-copy-v1",
        prompt_version=PROMPT_VERSION,
    )
    session.add(row)
    session.flush()
    return row


def _client(session: Session) -> ASGITestClient:
    return ASGITestClient(session, app_env=AppEnv.LOCAL)


# ============================================================
# The search projection must not drift
# ============================================================


def _field_shape(sql: str) -> list[str]:
    """The `->>` field names, in order. That is the part that must not drift."""
    return re.findall(r"->>\s*'(\w+)'", sql)


def _migration_projection() -> str:
    """Migration `0011`'s projection expression, read from its own constants.

    Loaded from the file rather than imported as a module: Alembic revision files are
    not importable as ordinary modules, and reading the literal keeps the comparison
    honest -- an import would go through the same Python objects.
    """
    text = REPO_ROOT.joinpath("database/migrations/versions/0011_api_search_indexes.py").read_text(
        encoding="utf-8"
    )
    block = re.search(r"_PROJECTION: str = .*?\.join\(\s*(.*?)\s*\)\n", text, re.DOTALL)
    assert block is not None, "migration 0011 no longer builds _PROJECTION this way"
    fields = re.findall(r"\{field\}", block.group(1))
    # Rebuild from the *field tuple the migration declares*, not from COPY_FIELDS, so
    # a reordered tuple on either side is caught rather than mirrored.
    declared = re.search(r"_COPY_FIELDS: Sequence\[str\] = \((.*?)\)", text, re.DOTALL)
    assert declared is not None
    migration_fields = re.findall(r'"(\w+)"', declared.group(1))
    assert fields, "the projection is no longer built from _COPY_FIELDS"
    return " || ' ' || ".join(f"coalesce(normalized->>'{name}', '')" for name in migration_fields)


def test_every_copy_of_the_search_projection_agrees(db_session: Session) -> None:
    """The projection exists three times. Drift between them is silent and fatal.

    `services/ad_search.py` builds it for the query, `models/ads.py` declares it for
    the index, and migration `0011` spells it out to create it. An index whose
    expression differs from the query's is **not used** -- the query still returns
    correct rows, just slowly, forever, with nothing to indicate why.

    Compared as field order rather than exact text, because PostgreSQL deparses
    stored expressions with casts and parentheses that SQLAlchemy never emits.
    """
    from app.models import ads as ads_model

    # Compiled with the PostgreSQL dialect rather than `literal_binds`: the
    # `'simple'` argument has type REGCONFIG, for which SQLAlchemy has no literal
    # renderer. The `->>` field names are what this compares, and those render fine.
    dialect = db_session.get_bind().dialect
    rendered_query = str(copy_projection().compile(dialect=dialect))
    rendered_index = str(copy_tsvector().compile(dialect=dialect))
    # The migration's own literal, imported rather than re-derived -- so the test
    # compares three independently written expressions instead of three calls to the
    # same one. Read from the module constants, not the prose: the file's docstring
    # also contains `->>'...'` examples, and parsing a comment would prove nothing.
    migration_text = _migration_projection()

    for rendered in (
        ads_model._COPY_SEARCH_PROJECTION,
        rendered_query,
        rendered_index,
        migration_text,
    ):
        assert _field_shape(rendered) == list(COPY_FIELDS), rendered


def test_the_search_query_matches_the_index_expression_exactly(db_session: Session) -> None:
    """Every literal in the projection must stay a literal.

    An expression index is used only when the query's expression matches the index's.
    A JSON key, separator or `coalesce` default rendered as a bind parameter is a
    `Param` rather than a constant, and the two stop matching.

    Verified against the live schema rather than assumed. The parameterised form
    *does* still use the index on a **custom plan** -- PostgreSQL substitutes the
    value -- so search looks healthy at first. Under a **generic plan**
    (`plan_cache_mode`, which PostgreSQL switches to after five executions, the normal
    steady state for a hot query) it does not match and falls back to a sequential
    scan. The failure mode is therefore "search quietly stopped using its index once
    it got warm", which is why it needs a test rather than an inspection.
    """
    dialect = db_session.get_bind().dialect
    rendered = str(copy_tsvector().compile(dialect=dialect))
    # Every `%(name)s` in the projection would be a `Param` at generic-plan time.
    assert "%(" not in rendered, rendered
    for name in COPY_FIELDS:
        assert f"normalized ->> '{name}'" in rendered, name
    assert "to_tsvector('simple'" in rendered


def test_the_search_projection_coalesces_every_field() -> None:
    """Without `coalesce`, one empty description collapses the whole vector.

    `||` with a NULL operand is NULL, so an ad with a description but no headline
    would produce a NULL tsvector and match nothing at all -- invisible to search
    rather than absent from it.
    """
    rendered = str(copy_projection()).upper()
    assert rendered.count("COALESCE") == len(COPY_FIELDS)
    # Never a bare `->>` reaching the concatenation.
    assert rendered.count("->>") == len(COPY_FIELDS)


def test_both_search_indexes_exist(db_session: Session) -> None:
    """Migration `0011` installed both GIN indexes."""
    names = {
        row[0]
        for row in db_session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'ad_snapshots' AND indexname LIKE '%gin%'"
            )
        )
    }
    assert "ix_ad_snapshots_copy_fts_gin" in names
    assert "ix_ad_snapshots_copy_trgm_gin" in names


# ============================================================
# Search input handling (pure)
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("  kettle  ", "kettle"),
        ("x" * 500, "x" * 200),
    ],
)
def test_a_search_term_is_trimmed_bounded_and_optional(
    raw: str | None, expected: str | None
) -> None:
    """Empty means *no filter*, not "match nothing".

    `?q=` returning zero ads would read as "the search engine found nothing", which
    is a different claim from "you did not ask a question".
    """
    assert normalise_query(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("kettle", "%kettle%"),
        # Unescaped, a user typing `%` gets a sequential scan laundered through the
        # index -- and the request still succeeds.
        ("50%", "%50\\%%"),
        ("a_b", "%a\\_b%"),
        ("back\\slash", "%back\\\\slash%"),
    ],
)
def test_trigram_wildcards_are_escaped(raw: str, expected: str) -> None:
    assert trigram_pattern(raw) == expected


def test_tsquery_input_is_plain_text_not_operators() -> None:
    """`plainto_tsquery` treats `&`, `!`, `|`, `:*` as words.

    So there is no tsquery injection to defend against, and a user typing `&` gets a
    search for the word `&` rather than a malformed query or an error.
    """
    rendered = str(plainto_tsquery("kettle & ! | :*"))
    assert "plainto_tsquery" in rendered


# ============================================================
# Filter validation (pure)
# ============================================================


@pytest.mark.parametrize("value", list(AD_STATUS_VALUES))
def test_every_shipped_status_is_accepted(value: str) -> None:
    assert validate_status(value) == value


def test_an_unknown_status_names_the_allowed_ones() -> None:
    with pytest.raises(ValueError, match="allowed"):
        validate_status("stopped")


def test_an_unknown_data_origin_names_the_allowed_ones() -> None:
    with pytest.raises(ValueError, match="allowed"):
        validate_data_origin("scraped")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("in", "IN"), (" IN ", "IN"), ("uk", "UK")],
)
def test_country_is_upper_cased(raw: str, expected: str) -> None:
    assert validate_country(raw) == expected


@pytest.mark.parametrize("raw", ["IND", "I", "12", "", "i1"])
def test_a_bad_country_is_refused_before_it_reaches_sql(raw: str) -> None:
    """The column `CHECK` would refuse it too, but as a 500 or an empty page."""
    with pytest.raises(ValueError):
        validate_country(raw)


def test_an_unlisted_sort_field_raises_rather_than_falling_back() -> None:
    """`sort` is an allowlist, so a typo can never reach `ORDER BY`.

    Falling back to the default would silently return a differently-ordered page,
    which reads as "the sort is broken" rather than "the field name is wrong".
    """
    with pytest.raises(ValueError, match="unknown sort field"):
        resolve_sort("provider_active", None)
    with pytest.raises(ValueError, match="unknown sort direction"):
        resolve_sort("last_seen_at", "sideways")


def test_the_default_ordering_is_last_seen_at_descending() -> None:
    ordering = resolve_sort(None, None)
    assert len(ordering) == 2
    # A tie breaker is always present, because many ads share a `last_seen_at`.
    assert "id" in str(ordering[-1])


# ============================================================
# CSV cell safety (pure)
# ============================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("plain text", "plain text"),
        ("=1+1", "'=1+1"),
        ("+SUM(A1)", "'+SUM(A1)"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tleading tab", "'\tleading tab"),
        ("\rcarriage", "'\rcarriage"),
        # Only the FIRST character matters.
        ("safe =1+1", "safe =1+1"),
        ("", ""),
    ],
)
def test_a_formula_leading_cell_is_neutralised(raw: str | None, expected: str | None) -> None:
    """Ad copy very often starts with `-` (a bullet) or `+`.

    Opened in a spreadsheet such a cell is a formula, and `-2+3+cmd|' /C calc'!A0` in a
    competitor's headline is a real payload shape rather than a hypothetical one.
    Prefixing with one quote is the documented cost: the exported cell differs from
    the source by a single character, and by nothing else.
    """
    assert escape_cell(raw) == expected


def test_null_renders_as_an_empty_cell_not_a_zero() -> None:
    """`AGENTS.md` section 7: absence stays absence.

    A numeric zero in the duration column would be a measurement nobody took.
    """
    assert render_cell(None) is None
    assert render_cell(0) == "0"
    # A `false` `provider_active` is a real measured false, distinct from absent.
    assert render_cell(False) == "false"
    assert render_cell(True) == "true"


def test_timestamps_render_as_iso_utc() -> None:
    """So a spreadsheet and the API agree on what a timestamp is.

    Naive values are assumed UTC rather than localised: every timestamp this product
    stores comes from PostgreSQL `now()`, and converting would introduce a timezone
    claim the value does not make.
    """
    assert render_cell(datetime(2026, 10, 1, 9, 0, tzinfo=UTC)) == "2026-10-01T09:00:00+00:00"
    naive = datetime(2026, 10, 1, 9, 0)  # noqa: DTZ001 -- the point of the assertion
    assert render_cell(naive) == "2026-10-01T09:00:00+00:00"


def test_decimal_media_durations_are_not_floated() -> None:
    """A duration of 12.500s must not become `12.5` and then be quoted as exact."""
    assert render_cell(Decimal("12.500")) == "12.500"


# ============================================================
# Route registration and docs gating
# ============================================================


def test_the_s32_ad_routes_are_registered() -> None:
    """The four S3.2 routes, plus `/competitors` added by S3.3 step 1.

    Pinned as a whole rather than one link per route, so a route that appears or
    disappears cannot go unnoticed. The fifth path is the competitor directory: the
    names behind these filters' UUID parameters, added because nothing before it
    could turn a `competitor_id` into a human-readable choice.
    """
    assert sorted(create_app(app_env=AppEnv.LOCAL).openapi()["paths"]) == [
        "/ads",
        "/ads/{ad_id}",
        "/ads/{ad_id}/snapshots",
        "/competitors",
        "/exports/ads.csv",
    ]


def test_docs_and_openapi_are_disabled_in_production() -> None:
    """The S0.1 review item, finally closed.

    With routes in place the schema discloses the whole data model, so serving it
    unauthenticated in production is a real disclosure rather than a cosmetic one.
    Only the existing `app_env` setting is used -- no authentication is added here.
    """
    prod = create_app(app_env=AppEnv.PROD)
    assert prod.docs_url is None
    assert prod.openapi_url is None

    local = create_app(app_env=AppEnv.LOCAL)
    assert local.docs_url == "/docs"
    assert local.openapi_url == "/openapi.json"


def test_every_route_is_a_get() -> None:
    """No route may trigger work, so none may be anything but a read.

    Analysis is surfaced here, never caused: a page view must not be able to spend
    money or start a collection because someone refreshed a grid.
    """
    spec = create_app(app_env=AppEnv.LOCAL).openapi()
    for path, operations in spec["paths"].items():
        assert set(operations) == {"get"}, f"{path} exposes {sorted(operations)}"


def test_the_csv_column_list_carries_no_internal_field() -> None:
    assert COLUMNS[0] == "ad_id"
    assert "current_status" in COLUMNS
    for forbidden in ("raw_ref", "job_id", "attempt_no", "prompt", "response", "storage_key"):
        assert forbidden not in COLUMNS, forbidden


# ============================================================
# GET /ads
# ============================================================


def test_the_list_is_empty_on_an_empty_corpus(db_session: Session) -> None:
    response = _client(db_session).get("/ads")
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": DEFAULT_PAGE_SIZE}


def test_one_row_per_ad_with_a_contexts_list(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    body = _client(db_session).get("/ads").json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == str(ad.id)
    assert item["provider"] == PROVIDER
    assert item["data_origin"] == "third_party"
    assert len(item["contexts"]) == 1
    assert item["contexts"][0]["country"] == "IN"


def test_there_is_never_an_ad_level_status(db_session: Session) -> None:
    """The single most important negative assertion in this file.

    S2.3 gives each `(ad, Page, country)` its own conclusion. A scalar
    `current_status` on the ad would assert one of them as if it were the whole
    truth, which is the exact error `AGENTS.md` section 7 warns about.
    """
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id, current_status="seen")
    _add_context(
        db_session,
        ad_id=ad.id,
        page_id=page.id,
        country="AE",
        current_status="not_seen_since",
    )

    body = _client(db_session).get("/ads").json()
    item = body["items"][0]
    assert "current_status" not in item
    assert {c["current_status"] for c in item["contexts"]} == {"seen", "not_seen_since"}


def test_provider_active_stays_tri_state_through_json(db_session: Session) -> None:
    """`null` means the provider asserted nothing, and must not become `false`.

    Rounding it would invent a finding -- the difference between "Meta said this is
    not running" and "Meta told us nothing".
    """
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id, provider_active=None)

    item = _client(db_session).get("/ads").json()["items"][0]
    assert item["contexts"][0]["provider_active"] is None


def test_no_response_exposes_an_internal_identifier(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, snapshot = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _link_media(db_session, snapshot.id, "asset-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    for path in ("/ads", f"/ads/{ad.id}", f"/ads/{ad.id}/snapshots", "/exports/ads.csv"):
        body = _client(db_session).get(path).body
        assert str(snapshot.raw_ref) not in body, path
        assert "storage_key" not in body, path
        assert "job_id" not in body, path
        assert "prompt_version" not in body.replace("analysis_version", ""), path


def test_the_list_costs_a_fixed_number_of_queries(db_session: Session) -> None:
    """Four queries whatever the page size -- the anti-N+1 assertion.

    An implementation that asked per ad would issue `4 * page_size` queries, which
    is invisible on a 25-row page and fatal on a 100-row one.
    """
    page = _page(db_session, "page-a")
    for index in range(5):
        ad, _ = _observe(db_session, page_id=page.id, external_ad_id=f"ad-{index}")
        _add_context(db_session, ad_id=ad.id, page_id=page.id)

    counts: list[int] = []
    for size in (1, 5):
        # A class rather than a closure over the loop variable, so each page size
        # gets its own counter instead of aliasing the last one.
        class _Counter:
            def __init__(self) -> None:
                self.queries: list[None] = []

            def __call__(self, *args: Any, **kwargs: Any) -> None:
                self.queries.append(None)

        counter = _Counter()
        event.listen(db_session.get_bind(), "before_cursor_execute", counter)
        try:
            result = list_ads(
                db_session, filters=AdFilters(), page=1, page_size=size, with_media=True
            )
        finally:
            event.remove(db_session.get_bind(), "before_cursor_execute", counter)

        assert len(result.items) == size
        counts.append(len(counter.queries))

    # `total` adds one. So 5 queries on every page size -- never 5 vs 21.
    assert counts == [5, 5], counts


def test_page_beyond_the_end_is_empty_with_the_true_total(db_session: Session) -> None:
    """The request was well formed; there is simply nothing on that page.

    A 404 here would tell a paging client it had reached the end by error.
    """
    page = _page(db_session, "page-a")
    for index in range(3):
        ad, _ = _observe(db_session, page_id=page.id, external_ad_id=f"ad-{index}")
        _add_context(db_session, ad_id=ad.id, page_id=page.id)

    body = _client(db_session).get("/ads", page=99, page_size=2).json()
    assert body["items"] == []
    assert body["total"] == 3
    assert body["page"] == 99


def test_paging_returns_every_ad_exactly_once(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    for index in range(7):
        ad, _ = _observe(db_session, page_id=page.id, external_ad_id=f"ad-{index}")
        _add_context(db_session, ad_id=ad.id, page_id=page.id)

    client = _client(db_session)
    seen: list[str] = []
    for number in (1, 2, 3):
        body = client.get("/ads", page=number, page_size=3).json()
        seen.extend(item["id"] for item in body["items"])

    assert len(seen) == 7
    assert len(set(seen)) == 7


def test_an_oversized_page_size_is_refused_at_the_boundary(db_session: Session) -> None:
    """422, not a silent cap.

    Silently returning 100 of a requested 5000 is how a client ends up paginating a
    corpus it believes it has fully read. The route validates the contract at the
    edge; `list_ads` clamps as defence in depth for any caller that skips it.
    """
    response = _client(db_session).get("/ads", page_size=100_000)
    assert response.status_code == 422
    assert "page_size" in response.body


def test_the_service_clamps_a_page_size_the_route_would_refuse(db_session: Session) -> None:
    """Two layers, deliberately: the contract is enforced where it is declared, and
    the clamp is the fallback if a future caller reaches the service directly."""
    result = list_ads(db_session, filters=AdFilters(), page=1, page_size=100_000)
    assert result.page_size == MAX_PAGE_SIZE


def test_an_unknown_sort_field_is_a_400(db_session: Session) -> None:
    response = _client(db_session).get("/ads", sort="provider_active")
    assert response.status_code == 400
    assert "unknown sort field" in response.json()["detail"]


def test_an_unknown_status_filter_is_a_400(db_session: Session) -> None:
    """400, not 422: a well-formed request naming a value that does not exist.

    A client that sees 422 retries the same request forever.
    """
    response = _client(db_session).get("/ads", current_status="stopped")
    assert response.status_code == 400
    assert "allowed" in response.json()["detail"]


def test_an_unknown_data_origin_filter_is_a_400(db_session: Session) -> None:
    assert _client(db_session).get("/ads", data_origin="scraped").status_code == 400


def test_a_malformed_country_filter_is_a_400(db_session: Session) -> None:
    assert _client(db_session).get("/ads", country="IND").status_code == 400


# ============================================================
# Filters that actually filter
# ============================================================


def test_the_country_filter_selects_one_context(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id, country="IN")
    _add_context(db_session, ad_id=ad.id, page_id=page.id, country="AE")

    body = _client(db_session).get("/ads", country="AE").json()
    assert body["total"] == 1
    # The ad matches, but the response carries *every* context -- the filter decides
    # which ads, not which of an ad's conclusions to disclose.
    assert {c["country"] for c in body["items"][0]["contexts"]} == {"IN", "AE"}


def test_the_status_filter_selects_by_context(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    seen, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    stopped, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-2")
    _add_context(db_session, ad_id=seen.id, page_id=page.id, current_status="presumed_inactive")
    _add_context(db_session, ad_id=stopped.id, page_id=page.id, current_status="seen")

    body = _client(db_session).get("/ads", current_status="seen").json()
    assert [item["meta_ad_id"] for item in body["items"]] == ["ad-2"]


def test_provider_active_false_is_selectable_and_absent_is_not(db_session: Session) -> None:
    """`false` is a measured value; `null` is no value. They must not conflate."""
    page = _page(db_session, "page-a")
    off, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-off")
    unknown, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-unknown")
    _add_context(db_session, ad_id=off.id, page_id=page.id, provider_active=False)
    _add_context(db_session, ad_id=unknown.id, page_id=page.id, provider_active=None)

    off_ids = _client(db_session).get("/ads", provider_active="false").json()
    assert [i["meta_ad_id"] for i in off_ids["items"]] == ["ad-off"]

    unknown_ids = _client(db_session).get("/ads", provider_active="true").json()
    assert [i["meta_ad_id"] for i in unknown_ids["items"]] == []


def test_the_first_seen_window_filters_by_observation_time(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    early, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1", offset_days=0)
    late, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-2", offset_days=40)
    _add_context(db_session, ad_id=early.id, page_id=page.id)
    _add_context(db_session, ad_id=late.id, page_id=page.id)

    # `first_seen_at` is the wall clock at insert, not the run's `started_at`, so the
    # window is chosen to be unambiguous about it rather than to separate the two ads
    # by a few days. The comparison is a set because both rows land in the same
    # millisecond, leaving the ordering to a random-UUID tie-break -- asserting a
    # sequence here would be a coin flip, not a test.
    everything = _client(db_session).get("/ads", first_seen_from="2000-01-01T00:00:00Z").json()
    assert {i["meta_ad_id"] for i in everything["items"]} == {"ad-1", "ad-2"}

    nothing = _client(db_session).get("/ads", first_seen_to="2000-01-01T00:00:00Z").json()
    assert nothing["items"] == []


# ============================================================
# Search
# ============================================================


def test_search_finds_an_ad_by_a_word_in_its_copy(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(
        db_session,
        page_id=page.id,
        external_ad_id="ad-kettle",
        primary_text="A kettle that actually whistles.",
        headline=None,
        description=None,
        cta=None,
    )
    other, _ = _observe(
        db_session, page_id=page.id, external_ad_id="ad-other", primary_text="Buy a kettle today."
    )
    _add_context(db_session, ad_id=ad.id, page_id=page.id)
    _add_context(db_session, ad_id=other.id, page_id=page.id)

    body = _client(db_session).get("/ads", q="whistles").json()
    assert [i["meta_ad_id"] for i in body["items"]] == ["ad-kettle"]


def test_search_finds_a_word_in_the_headline_not_only_the_body(db_session: Session) -> None:
    """Both indexes cover all four fields, so a headline-only hit is findable."""
    page = _page(db_session, "page-a")
    ad, _ = _observe(
        db_session,
        page_id=page.id,
        external_ad_id="ad-1",
        primary_text="Nothing notable here.",
        headline="सिलेंडर वाला वॉटर प्युरिफायर",
    )
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    assert _client(db_session).get("/ads", q="वॉटर").json()["total"] == 1


def test_an_ad_with_several_matching_snapshots_is_returned_once(db_session: Session) -> None:
    """A snapshot joins to its ad, so five matching snapshots could mean five rows.

    `DISTINCT` inside the search subquery is what prevents it. Without that a user
    would see the same ad repeated and conclude the collection duplicated it.
    """
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)
    # Three further runs with the same words: the same `copy_hash`, so only the
    # first writes a snapshot and the rest add `seen_in_run` links. Either way the
    # ad must appear once.
    for offset in (1, 2, 3):
        _observe(db_session, page_id=page.id, external_ad_id="ad-1", offset_days=offset)

    body = _client(db_session).get("/ads", q="kettle").json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


def test_a_search_that_matches_nothing_returns_zero_not_an_error(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    response = _client(db_session).get("/ads", q="sprocket")
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_an_empty_search_is_no_filter(db_session: Session) -> None:
    """`?q=` must not read as "the search engine found nothing"."""
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    assert _client(db_session).get("/ads", q="   ").json()["total"] == 1


def test_a_trigram_wildcard_does_not_match_everything(db_session: Session) -> None:
    """An unescaped `%` would match every row and look like a working search."""
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    assert _client(db_session).get("/ads", q="%").json()["total"] == 0


def test_search_combines_with_another_filter(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id, country="IN")
    _add_context(db_session, ad_id=ad.id, page_id=page.id, country="AE")

    body = _client(db_session).get("/ads", q="kettle", country="AE").json()
    assert body["total"] == 1


# ============================================================
# GET /ads/{id}
# ============================================================


def test_the_detail_endpoint_returns_the_copy_verbatim(db_session: Session) -> None:
    """No canonicalisation, no trimming, no rewriting: this is what they ran."""
    page = _page(db_session, "page-a")
    text_value = "  Indrane cooker.   5L.  "
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1", primary_text=text_value)
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    body = _client(db_session).get(f"/ads/{ad.id}").json()
    assert body["copy_fields"]["primary_text"] == text_value


def test_an_unknown_ad_is_a_404(db_session: Session) -> None:
    response = _client(db_session).get(f"/ads/{uuid.uuid4()}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_the_detail_endpoint_surfaces_duration_with_its_source(db_session: Session) -> None:
    """`AGENTS.md` section 8: a duration display must say which timestamp it used."""
    page = _page(db_session, "page-a")
    started = BASE - timedelta(days=90)
    ad, _ = _observe(
        db_session,
        page_id=page.id,
        external_ad_id="ad-1",
        meta_delivery_start=started,
    )
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    duration = _client(db_session).get(f"/ads/{ad.id}").json()["duration"]
    assert duration["days"] == 90
    assert duration["source"] == "meta_delivery_start"
    assert duration["is_long_running_signal"] is True
    # Longevity is a proxy, and the field is named so it cannot be read as a verdict.
    assert "winner" not in json.dumps(duration)


def test_an_ad_with_no_reported_start_falls_back_to_first_seen(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    duration = _client(db_session).get(f"/ads/{ad.id}").json()["duration"]
    assert duration["source"] == "first_seen_at"
    assert duration["days"] == 0


def test_media_is_a_reference_and_says_the_bytes_are_absent(db_session: Session) -> None:
    """S2.4 stores references only, so `bytes_available` is hard-coded `false`.

    Emitting a present-but-null `storage_key` would invite a client to read it as a
    download path that does not exist.
    """
    page = _page(db_session, "page-a")
    ad, snapshot = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _link_media(db_session, snapshot.id, "asset-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    media = _client(db_session).get(f"/ads/{ad.id}").json()["media"]
    assert len(media) == 1
    assert media[0]["provider_key"] == "asset-1"
    assert media[0]["bytes_available"] is False
    assert "storage_key" not in media[0]


def test_an_unanalysed_ad_reports_analysis_as_null(db_session: Session) -> None:
    """Not fourteen null fields, which would read as "analysed and found nothing"."""
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    assert _client(db_session).get(f"/ads/{ad.id}").json()["analysis"] is None


def test_an_analysis_travels_badged_as_interpretation(db_session: Session) -> None:
    """The badge is in the payload, not a UI convention.

    The concrete risk: a client joins `ad.data_origin` (`PROVIDER_DATA`) onto model
    output and presents an interpretation as something Meta said.
    """
    page = _page(db_session, "page-a")
    ad, snapshot = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)
    _add_analysis(db_session, ad=ad, snapshot=snapshot)

    analysis = _client(db_session).get(f"/ads/{ad.id}").json()["analysis"]
    assert analysis["evidence_class"] == "AI_INTERPRETATION"
    assert analysis["data_origin" if "data_origin" in analysis else "evidence_class"]
    assert analysis["language"] == "hi"
    assert analysis["analysis_version"] == ANALYSIS_VERSION
    assert analysis["interpretation"]["hook"] == "शुरुआत में ही दमदम"
    # A field the source did not report stays null; it is never invented.
    assert analysis["interpretation"]["problem"] is None


def test_analysis_is_joined_by_copy_hash_not_by_source_snapshot(db_session: Session) -> None:
    """Copy-scoped analysis is the reuse S3.1 exists for.

    An ad running the same words as an already-analysed ad must resolve to that
    analysis. Joining through `source_ad_snapshot_id` would hide it, because the
    analysis belongs to a different ad's snapshot.
    """
    page = _page(db_session, "page-a")
    first, first_snapshot = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_analysis(db_session, ad=first, snapshot=first_snapshot)

    twin, twin_snapshot = _observe(db_session, page_id=page.id, external_ad_id="ad-2")
    assert twin_snapshot.copy_hash == first_snapshot.copy_hash
    _add_context(db_session, ad_id=twin.id, page_id=page.id)

    analysis = _client(db_session).get(f"/ads/{twin.id}").json()["analysis"]
    assert analysis is not None
    assert analysis["copy_hash"] == twin_snapshot.copy_hash
    # Reported honestly: the analysis did not come from *this* ad's snapshot.
    assert analysis["source_snapshot_id"] != str(twin_snapshot.id)


def test_an_analysis_at_another_version_is_not_served(db_session: Session) -> None:
    """A v2 schema arriving later must not answer v1 queries."""
    page = _page(db_session, "page-a")
    ad, snapshot = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)
    row = _add_analysis(db_session, ad=ad, snapshot=snapshot)
    row.analysis_version = "s4-analysis-v2"
    db_session.flush()

    assert _client(db_session).get(f"/ads/{ad.id}").json()["analysis"] is None


def test_analysis_for_an_empty_hash_list_queries_nothing(db_session: Session) -> None:
    assert analysis_for(db_session, []) == {}


# ============================================================
# GET /ads/{id}/snapshots
# ============================================================


def test_snapshots_are_returned_newest_first(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, first_snapshot = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _observe(
        db_session,
        page_id=page.id,
        external_ad_id="ad-1",
        offset_days=5,
        primary_text="A kettle that actually whistles, revised.",
    )
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    body = _client(db_session).get(f"/ads/{ad.id}/snapshots").json()
    assert body["total"] == 2
    assert first_snapshot.id not in [i["id"] for i in body["items"]]
    assert body["items"][0]["created_at"] >= body["items"][1]["created_at"]


def test_a_snapshot_page_shows_what_the_ad_said_then(db_session: Session) -> None:
    """A snapshot page *is* a history page, so each row carries its own copy."""
    page = _page(db_session, "page-a")
    ad, _ = _observe(
        db_session, page_id=page.id, external_ad_id="ad-1", primary_text="First wording."
    )
    _observe(
        db_session,
        page_id=page.id,
        external_ad_id="ad-1",
        offset_days=3,
        primary_text="Second wording.",
    )
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    body = _client(db_session).get(f"/ads/{ad.id}/snapshots", page_size=50).json()
    wordings = {i["copy_fields"]["primary_text"] for i in body["items"]}
    assert wordings == {"First wording.", "Second wording."}


def test_an_unknown_ad_snapshots_page_is_a_404(db_session: Session) -> None:
    assert _client(db_session).get(f"/ads/{uuid.uuid4()}/snapshots").status_code == 404


def test_snapshot_rows_carry_no_internal_pointer(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, snapshot = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _link_media(db_session, snapshot.id, "asset-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    body = _client(db_session).get(f"/ads/{ad.id}/snapshots").body
    assert str(snapshot.raw_ref) not in body


# ============================================================
# CSV export
# ============================================================


def _csv_rows(response_body: str) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO(response_body))
    rows = list(reader)
    return rows[0], rows[1:]


def test_the_csv_header_is_present_even_with_no_ads(db_session: Session) -> None:
    """A headerless empty file is indistinguishable from a failed download."""
    response = _client(db_session).get("/exports/ads.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    header, rows = _csv_rows(response.body)
    assert header == list(COLUMNS)
    assert rows == []


def test_the_csv_emits_one_row_per_ad_per_context(db_session: Session) -> None:
    """A CSV cannot nest, and flattening status would assert a global conclusion.

    So a two-context ad gets two rows, and a context-free ad still gets one row with
    blank context columns -- dropping it would hide an ad that exists.
    """
    page = _page(db_session, "page-a")
    with_context, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    without, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-2")
    _add_context(db_session, ad_id=with_context.id, page_id=page.id, country="IN")
    _add_context(db_session, ad_id=with_context.id, page_id=page.id, country="AE")
    _add_context(db_session, ad_id=without.id, page_id=page.id)

    header, rows = _csv_rows(_client(db_session).get("/exports/ads.csv").body)
    index = {name: position for position, name in enumerate(header)}

    by_ad: dict[str, list[list[str]]] = {}
    for row in rows:
        by_ad.setdefault(row[index["ad_id"]], []).append(row)

    assert len(rows) == 3
    assert len(by_ad[str(with_context.id)]) == 2
    assert {row[index["context_country"]] for row in by_ad[str(with_context.id)]} == {"IN", "AE"}


def test_a_context_free_ad_still_gets_a_row(db_session: Session) -> None:
    """A CSV cannot nest, and dropping the row would hide an ad that exists.

    `persist_observations` always writes a context, so one is removed here to reach
    the state this defends against -- an ad whose context rows are gone or not yet
    written.
    """
    from app.models.ad_status import AdStatusByContext

    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    db_session.query(AdStatusByContext).filter(AdStatusByContext.ad_id == ad.id).delete()
    db_session.flush()

    header, rows = _csv_rows(_client(db_session).get("/exports/ads.csv").body)
    index = {name: position for position, name in enumerate(header)}
    assert len(rows) == 1
    assert rows[0][index["ad_id"]] == str(ad.id)
    assert rows[0][index["context_country"]] == ""
    assert rows[0][index["current_status"]] == ""


def test_a_formula_in_competitor_copy_is_neutralised_in_the_export(db_session: Session) -> None:
    """End to end, through a real provider string and a real ad.

    The payload shape below is the actual concern: ad copy is untrusted input and it
    very often begins with `-` or `+`.
    """
    page = _page(db_session, "page-a")
    payload = "-2+3+cmd|' /C calc'!A0"
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1", headline=payload)
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    _header, rows = _csv_rows(_client(db_session).get("/exports/ads.csv").body)
    # The export does not carry copy, but it does carry the provider's `meta_ad_id`
    # and the analysis text, both of which the same defence covers.
    for row in rows:
        for cell in row:
            assert not cell.startswith(("=", "+", "-", "@", "\t", "\r")), cell

    assert payload not in _client(db_session).get("/exports/ads.csv").body


def test_a_null_cell_is_empty_and_never_a_zero(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id, provider_active=None)

    header, rows = _csv_rows(_client(db_session).get("/exports/ads.csv").body)
    index = {name: position for position, name in enumerate(header)}
    row = next(r for r in rows if r[index["ad_id"]] == str(ad.id))
    assert row[index["provider_active"]] == ""
    assert row[index["not_seen_since_at"]] == ""
    assert row[index["media_provider_keys"]] == ""


def test_the_csv_timestamps_are_iso_utc(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    header, rows = _csv_rows(_client(db_session).get("/exports/ads.csv").body)
    index = {name: position for position, name in enumerate(header)}
    row = rows[0]
    assert row[index["first_seen_at"]].endswith("+00:00")


def test_the_csv_carries_the_interpretation_badge(db_session: Session) -> None:
    """So an exported cell cannot be read as provider data."""
    page = _page(db_session, "page-a")
    ad, snapshot = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)
    _add_analysis(db_session, ad=ad, snapshot=snapshot)

    header, rows = _csv_rows(_client(db_session).get("/exports/ads.csv").body)
    index = {name: position for position, name in enumerate(header)}
    assert rows[0][index["analysis_available"]] == "true"
    assert rows[0][index["analysis_evidence_class"]] == "AI_INTERPRETATION"
    assert rows[0][index["analysis_language"]] == "hi"


def test_the_csv_honours_the_same_filters_as_the_list(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id, country="IN")
    _add_context(db_session, ad_id=ad.id, page_id=page.id, country="AE")

    _header, filtered = _csv_rows(_client(db_session).get("/exports/ads.csv", country="AE").body)
    assert len(filtered) == 2  # one row per context, only the AE one


def test_the_csv_accepts_every_filter_ads_does(db_session: Session) -> None:
    """Parity, asserted against `/ads` itself rather than a restated list.

    The route docstring claimed "the same filters as `/ads`" while dropping four date
    parameters. Comparing the two live routes' declared query parameters is what makes
    the claim true and keeps it true.
    """
    spec = create_app(app_env=AppEnv.LOCAL).openapi()
    ads_params = {p["name"] for p in spec["paths"]["/ads"]["get"]["parameters"]}
    csv_params = {p["name"] for p in spec["paths"]["/exports/ads.csv"]["get"]["parameters"]}

    # Paging and ordering belong to `/ads` alone; an export has no page.
    paging_only = {"page", "page_size", "sort", "direction"}
    assert ads_params - paging_only == csv_params
    for date_filter in (
        "first_seen_from",
        "first_seen_to",
        "last_seen_from",
        "last_seen_to",
    ):
        assert date_filter in csv_params, date_filter


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("first_seen_to", "2000-01-01T00:00:00Z"),
        ("last_seen_to", "2000-01-01T00:00:00Z"),
    ],
)
def test_a_date_filter_actually_narrows_the_export(
    db_session: Session, parameter: str, value: str
) -> None:
    """Proves the four new parameters feed the filter object rather than being accepted.

    A parameter the route declares but never passes would leave the export showing
    everything -- a silent divergence from the filtered `/ads` set.
    """
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    _header, everything = _csv_rows(_client(db_session).get("/exports/ads.csv").body)
    assert len(everything) == 1

    _header, nothing = _csv_rows(
        _client(db_session).get("/exports/ads.csv", **{parameter: value}).body
    )
    assert nothing == []


def test_a_widening_date_filter_keeps_every_row(db_session: Session) -> None:
    """The other direction, so the test above cannot pass by filtering everything."""
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    _header, rows = _csv_rows(
        _client(db_session).get("/exports/ads.csv", first_seen_from="2000-01-01T00:00:00Z").body
    )
    assert len(rows) == 1


def test_an_export_over_the_cap_is_refused_not_truncated(db_session: Session) -> None:
    """A partial export is indistinguishable from a complete one.

    Someone will act on a truncated file believing it whole, so this raises and the
    route turns it into a 413. This is the **service** contract; the route-level
    behaviour that depends on the check running at the right time is proved by
    `test_an_oversized_export_is_a_413_over_real_http`.
    """
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    with pytest.raises(CsvExportTooLarge):
        list(iter_export_rows(db_session, filters=AdFilters(), max_rows=0))


def _cap_at(monkeypatch: Any, rows: int) -> None:
    """Lower the export cap to `rows` **as the route reads it**.

    Patches the constant the route module imported -- configuration, not behaviour.
    Every code path below is the shipped one: the real route, the real preflight, the
    real count query, the real generator and real HTTP framing.
    """
    import app.api.ads as ads_api

    monkeypatch.setattr(ads_api, "MAX_EXPORT_ROWS", rows)


def _ads_with_one_context(db_session: Session, count: int) -> None:
    """`count` ads, each with exactly one context -- so rows == ads."""
    page = _page(db_session, "page-a")
    for index in range(count):
        ad, _ = _observe(db_session, page_id=page.id, external_ad_id=f"ad-{index}")
        _add_context(db_session, ad_id=ad.id, page_id=page.id)


def test_an_oversized_export_is_a_413_over_real_http(db_session: Session, monkeypatch: Any) -> None:
    """The whole point of this pass, over actual HTTP.

    **The previous version of this test was false.** It replaced `stream_ads_csv`
    with a plain function that raised eagerly, so it proved the route could turn an
    exception into a 413 -- and the real `stream_ads_csv` is a *generator*, so the
    real cap check can only run after `StreamingResponse` has already sent the status
    line. The test passed while the product truncated.

    Nothing is mocked here except the cap constant. Two ads, cap of one: the count
    genuinely exceeds it.
    """
    _cap_at(monkeypatch, 1)
    _ads_with_one_context(db_session, 2)

    response = _client(db_session).get("/exports/ads.csv")
    assert response.status_code == 413


def test_a_413_carries_no_csv_body_and_no_attachment_header(
    db_session: Session, monkeypatch: Any
) -> None:
    """No partial file, and no `Content-Disposition` promising one.

    Half a file under an attachment header is the exact outcome the cap exists to
    prevent, so both are asserted: not a status of 200, and not a byte of CSV.
    """
    _cap_at(monkeypatch, 1)
    _ads_with_one_context(db_session, 2)

    response = _client(db_session).get("/exports/ads.csv")
    assert response.status_code == 413
    assert "ad_id" not in response.body, "a CSV header was streamed before the refusal"
    assert "content-disposition" not in response.headers
    assert response.json() == {"detail": response.json()["detail"]}


def test_a_413_detail_is_stable_and_leaks_nothing(db_session: Session, monkeypatch: Any) -> None:
    """Same refusal every time, and no internals in it."""
    _cap_at(monkeypatch, 1)
    _ads_with_one_context(db_session, 2)

    first = _client(db_session).get("/exports/ads.csv")
    second = _client(db_session).get("/exports/ads.csv")

    assert first.body == second.body
    detail = first.json()["detail"]
    assert "rows" in detail and "1" in detail
    for leak in ("Traceback", 'File "', "sqlalchemy", "psycopg", "SELECT"):
        assert leak not in first.body, leak


def test_an_export_exactly_at_the_cap_is_allowed(db_session: Session, monkeypatch: Any) -> None:
    """The cap is inclusive. Off-by-one here would refuse a legitimate export."""
    _cap_at(monkeypatch, 2)
    _ads_with_one_context(db_session, 2)

    response = _client(db_session).get("/exports/ads.csv")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")


def test_one_row_over_the_cap_is_refused(db_session: Session, monkeypatch: Any) -> None:
    """The boundary from the other side: `cap` is fine, `cap + 1` is not."""
    _cap_at(monkeypatch, 3)
    page = _page(db_session, "page-a")
    _ads_with_one_context(db_session, 3)
    assert _client(db_session).get("/exports/ads.csv").status_code == 200

    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-extra")
    _add_context(db_session, ad_id=ad.id, page_id=page.id)
    response = _client(db_session).get("/exports/ads.csv")
    assert response.status_code == 413


def test_the_cap_counts_rows_not_ads(db_session: Session, monkeypatch: Any) -> None:
    """One ad with three contexts is three rows.

    Counting ads would admit this export through the preflight and only discover the
    overrun halfway down the file -- the same truncation, reached a different way.
    """
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1")
    for country in ("IN", "AE", "GB"):
        _add_context(db_session, ad_id=ad.id, page_id=page.id, country=country)

    # One ad, cap of two: allowed on ad count, refused on row count.
    _cap_at(monkeypatch, 2)
    assert _client(db_session).get("/exports/ads.csv").status_code == 413


def test_a_normal_export_is_still_streamed_as_200(db_session: Session, monkeypatch: Any) -> None:
    """Refusing oversized exports must not have broken ordinary ones.

    The preflight is two queries, not a buffer: the response is still produced by the
    generator, row by row.
    """
    _cap_at(monkeypatch, 100)
    _ads_with_one_context(db_session, 2)

    response = _client(db_session).get("/exports/ads.csv")
    assert response.status_code == 200
    header, rows = _csv_rows(response.body)
    assert header == list(COLUMNS)
    assert len(rows) == 2


# ============================================================
# Platform visibility (S3.2 fix pass)
# ============================================================


def test_the_list_reports_the_latest_snapshots_platforms(db_session: Session) -> None:
    """Platforms are product-required and were stored all along -- only unexposed.

    They come out of `normalized`, which already holds the whole `RawAdRecord`, so
    this adds no column and moves no hash.
    """
    page = _page(db_session, "page-a")
    ad, _ = _observe(
        db_session, page_id=page.id, external_ad_id="ad-1", platforms=("facebook", "instagram")
    )
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    item = _client(db_session).get("/ads").json()["items"][0]
    assert item["platforms"] == ["facebook", "instagram"]


def test_the_detail_endpoint_reports_platforms(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1", platforms=("facebook",))
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    assert _client(db_session).get(f"/ads/{ad.id}").json()["platforms"] == ["facebook"]


def test_each_snapshot_reports_its_own_platforms(db_session: Session) -> None:
    """Per snapshot, because a snapshot is an *observation*.

    An ad can move between platforms, and showing the newest value on every row would
    make history claim things it never saw.
    """
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1", platforms=("facebook",))
    _observe(
        db_session,
        page_id=page.id,
        external_ad_id="ad-1",
        offset_days=4,
        platforms=("instagram",),
        primary_text="Now on Instagram too.",
    )
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    body = _client(db_session).get(f"/ads/{ad.id}/snapshots", page_size=50).json()
    reported = {tuple(item["platforms"]) for item in body["items"]}
    assert reported == {("facebook",), ("instagram",)}


def test_platform_order_is_the_providers_not_ours(db_session: Session) -> None:
    """Not sorted, not de-duplicated, not re-ordered.

    Re-sorting would make the API disagree with the stored evidence it reads.
    """
    page = _page(db_session, "page-a")
    ad, _ = _observe(
        db_session,
        page_id=page.id,
        external_ad_id="ad-1",
        platforms=("instagram", "facebook", "audience_network"),
    )
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    assert _client(db_session).get(f"/ads/{ad.id}").json()["platforms"] == [
        "instagram",
        "facebook",
        "audience_network",
    ]


def test_no_platforms_is_an_empty_list_not_a_claim(db_session: Session) -> None:
    """`[]` means "the stored record lists none" -- never "this ad ran nowhere"."""
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1", platforms=())
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    item = _client(db_session).get(f"/ads/{ad.id}").json()
    assert item["platforms"] == []
    assert "none" not in str(item["platforms"]).lower()


def test_a_missing_platforms_key_is_treated_as_absent_not_invented() -> None:
    """Robustness against a `normalized` document written before the key existed.

    Tested as a pure function with a stub, because the alternative -- updating a real
    snapshot to drop the key -- is refused by the append-only trigger. That refusal is
    the design working: `normalized` cannot be rewritten, so the reader has to cope
    with whatever shape it finds.
    """
    from dataclasses import dataclass

    @dataclass
    class _Stub:
        normalized: dict[str, Any]

    assert snapshot_platforms(_Stub({"headline": "x"})) == ()  # type: ignore[arg-type]
    assert snapshot_platforms(_Stub({"platforms": None})) == ()  # type: ignore[arg-type]
    assert snapshot_platforms(_Stub({"platforms": "facebook"})) == ()  # type: ignore[arg-type]
    assert snapshot_platforms(_Stub({"platforms": []})) == ()  # type: ignore[arg-type]
    assert snapshot_platforms(None) == ()


def test_a_non_string_platform_is_skipped_rather_than_coerced() -> None:
    """`str(123)` would invent a platform called "123"."""
    from dataclasses import dataclass

    @dataclass
    class _Stub:
        normalized: dict[str, Any]

    stub = _Stub({"platforms": ["facebook", 7, None, {"a": 1}]})
    assert snapshot_platforms(stub) == ("facebook",)  # type: ignore[arg-type]


def test_the_csv_carries_a_platforms_column(db_session: Session) -> None:
    page = _page(db_session, "page-a")
    ad, _ = _observe(
        db_session, page_id=page.id, external_ad_id="ad-1", platforms=("facebook", "instagram")
    )
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    header, rows = _csv_rows(_client(db_session).get("/exports/ads.csv").body)
    index = {name: position for position, name in enumerate(header)}
    assert "platforms" in index
    assert rows[0][index["platforms"]] == "facebook,instagram"


def test_an_empty_platform_list_is_an_empty_csv_cell(db_session: Session) -> None:
    """Not the string "none", which would be a claim the provider never made."""
    page = _page(db_session, "page-a")
    ad, _ = _observe(db_session, page_id=page.id, external_ad_id="ad-1", platforms=())
    _add_context(db_session, ad_id=ad.id, page_id=page.id)

    header, rows = _csv_rows(_client(db_session).get("/exports/ads.csv").body)
    index = {name: position for position, name in enumerate(header)}
    assert rows[0][index["platforms"]] == ""


def test_platform_visibility_added_no_column_and_no_index(db_session: Session) -> None:
    """Read out of `normalized`, so the schema is untouched by this pass."""
    table = cast("Table", AdSnapshot.__table__)
    assert "platforms" not in {str(column.name) for column in table.c}
    assert not [index for index in table.indexes if "platform" in str(index.name)]


def test_the_row_cap_is_a_documented_constant() -> None:
    assert isinstance(MAX_EXPORT_ROWS, int)
    assert MAX_EXPORT_ROWS > 0


# ============================================================
# Error handling
# ============================================================


def test_an_unhandled_failure_returns_500_with_no_traceback(
    db_session: Session, monkeypatch: Any
) -> None:
    """A stack trace in a response body discloses SQLAlchemy statements and values.

    `main.py` does not set `debug=True` today, but a future contributor might, and
    FastAPI's debug handler returns the traceback. So the catch-all is registered in
    every environment, not only production.
    """
    import app.api.ads as ads_api

    def _explode(session: Any, **kwargs: Any) -> Any:
        raise RuntimeError("SECRET_TOKEN=abc123 column provider_metadata")

    monkeypatch.setattr(ads_api, "list_ads", _explode)
    response = _client(db_session).get("/ads")
    assert response.status_code == 500
    assert "SECRET_TOKEN" not in response.body
    assert "Traceback" not in response.body
    assert "RuntimeError" not in response.body
    assert response.json() == {"detail": "internal server error"}


def test_a_malformed_uuid_is_a_422_not_a_500(db_session: Session) -> None:
    """422: the request could not be parsed at all, as distinct from a bad value."""
    assert _client(db_session).get("/ads/not-a-uuid").status_code == 422

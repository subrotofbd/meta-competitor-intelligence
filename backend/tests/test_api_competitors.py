"""S3.3 step 1: the competitor directory.

## What this file is really testing

`/competitors` looks trivial, and the shapes it returns are not the risk. The risk
is **uselessness**: an endpoint that lists names but whose ids do not actually filter
`/ads` would leave the frontend exactly where it started, with dropdowns that
silently return nothing.

So the load-bearing tests here are the two round-trip ones --
`test_a_competitor_id_from_here_filters_ads` and
`test_a_page_id_from_here_filters_ads`. Everything else is contract.

The negative tests matter just as much. `models/tracking.py` states that competitors
and pages carry **no** provenance, because neither is collected data; stamping
`PROVIDER_DATA` on a Page would be a lie. `test_no_provenance_field_is_exposed` is
what keeps that from being quietly "improved" later.

`integration`, because these write real rows and read them back. Nothing is
committed -- `db_session` binds every session inside an outer transaction that is
always rolled back.

No HTTP client is installed, so `tests/asgi_client.py` drives the ASGI app
in-process. No server, no network.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.config import AppEnv
from app.main import create_app
from app.models.tracking import Competitor, FacebookPage
from tests.asgi_client import ASGITestClient

pytestmark = pytest.mark.integration

BASE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
PROVIDER = "mock"


# ============================================================
# Builders
# ============================================================


def _competitor(session: Session, name: str) -> Competitor:
    """A competitor row. Name is deliberately not unique, matching the table."""
    row = Competitor(name=name)
    session.add(row)
    session.flush()
    return row


def _page(
    session: Session,
    *,
    competitor_id: uuid.UUID,
    page_id: str,
    name: str | None = "Aurora Kitchen Studio",
    url: str | None = "https://aurora.example.invalid/",
    country: str = "IN",
    is_tracked: bool = True,
    tracking_frequency: str = "daily",
) -> FacebookPage:
    """A Page row. `name`/`url` are nullable because a provider need not report them."""
    page = FacebookPage(
        competitor_id=competitor_id,
        page_id=page_id,
        name=name,
        url=url,
        country=country,
        tracking_frequency=tracking_frequency,
        is_tracked=is_tracked,
    )
    session.add(page)
    session.flush()
    return page


def _observe_ad(
    session: Session,
    *,
    page: FacebookPage,
    external_ad_id: str,
    offset_days: int = 0,
    platforms: tuple[str, ...] = ("facebook",),
) -> uuid.UUID:
    """Persist one ad observation through the real S2.1 write path.

    Hand-inserting an `Ad` would skip hash computation and the status context that
    `persist_observations` writes, and `/ads?competitor_id=` filters through that
    context table -- so a hand-made row would not prove the filter works at all.
    """
    from app.models.runs import (
        CollectionRun,
        CollectionRunStatus,
        ProviderRun,
        ProviderRunStatus,
        RawResponse,
    )
    from app.providers.data.models import AdFormat, RawAdRecord
    from app.providers.data.provenance import DataOrigin
    from app.services.ad_persistence import ObservedRecord, persist_observations

    at = BASE + timedelta(days=offset_days)
    run = CollectionRun(
        facebook_page_id=page.id,
        provider=PROVIDER,
        data_origin=DataOrigin.third_party,
        country=page.country,
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
            "country": page.country,
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
                record=RawAdRecord(
                    external_ad_id=external_ad_id,
                    platforms=platforms,
                    countries=(page.country,),
                    ad_status="active",
                    primary_text="A kettle that actually whistles.",
                    display_format=AdFormat.IMAGE,
                ),
                raw_response_id=raw.id,
            )
        ],
        provider=PROVIDER,
        data_origin=DataOrigin.third_party,
        page_id=page.id,
        country=page.country,
    )[0]
    return result.ad_id


def _client(session: Session) -> ASGITestClient:
    return ASGITestClient(session, app_env=AppEnv.LOCAL)


# ============================================================
# Shape
# ============================================================


def test_an_empty_corpus_is_200_with_no_items(db_session: Session) -> None:
    """`{"items": []}`, not 404 and not an empty body.

    An operator with nothing tracked yet is a real state, and the client has to be
    able to tell it apart from a failure.
    """
    response = _client(db_session).get("/competitors")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_the_envelope_and_nesting_shape_is_what_is_documented(db_session: Session) -> None:
    competitor = _competitor(db_session, "Aurora")
    _page(db_session, competitor_id=competitor.id, page_id="pg-1")

    body = _client(db_session).get("/competitors").json()
    assert set(body) == {"items"}

    item = body["items"][0]
    assert set(item) == {"id", "name", "created_at", "pages"}
    assert item["name"] == "Aurora"
    assert set(item["pages"][0]) == {
        "id",
        "page_id",
        "name",
        "url",
        "country",
        "is_tracked",
        "tracking_frequency",
        "created_at",
    }


def test_a_competitor_with_no_pages_is_present_and_visibly_empty(db_session: Session) -> None:
    """Omitting them would hide a competitor the operator actually created."""
    _competitor(db_session, "Brand With No Pages")

    items = _client(db_session).get("/competitors").json()["items"]
    assert len(items) == 1
    assert items[0]["pages"] == []


def test_nullable_page_name_and_url_stay_null(db_session: Session) -> None:
    """`None` means "the provider reported none". `""` would invent a blank name.

    Both are nullable on the table precisely because a provider need not report them,
    and a client must be able to tell that apart from an empty string.
    """
    competitor = _competitor(db_session, "Sparse")
    _page(
        db_session,
        competitor_id=competitor.id,
        page_id="pg-sparse",
        name=None,
        url=None,
    )

    page = _client(db_session).get("/competitors").json()["items"][0]["pages"][0]
    assert page["name"] is None
    assert page["url"] is None


def test_an_untracked_page_is_returned_not_hidden(db_session: Session) -> None:
    """Stopping collection is not deleting, and hiding the Page would hide its history.

    `ad_snapshots` is append-only with `RESTRICT` foreign keys: the Page's recorded
    observations stay real whether or not we still collect it. A directory that
    dropped untracked Pages would be a soft delete the schema does not have.
    """
    competitor = _competitor(db_session, "Aurora")
    _page(db_session, competitor_id=competitor.id, page_id="pg-tracked", is_tracked=True)
    _page(db_session, competitor_id=competitor.id, page_id="pg-idle", is_tracked=False)

    pages = _client(db_session).get("/competitors").json()["items"][0]["pages"]
    by_id = {page["page_id"]: page for page in pages}
    assert set(by_id) == {"pg-tracked", "pg-idle"}
    assert by_id["pg-idle"]["is_tracked"] is False


# ============================================================
# Ordering
# ============================================================


def test_competitors_are_ordered_by_name(db_session: Session) -> None:
    for name in ("Zenith", "Aurora", "Meridian"):
        _competitor(db_session, name)

    names = [item["name"] for item in _client(db_session).get("/competitors").json()["items"]]
    assert names == ["Aurora", "Meridian", "Zenith"]


def test_equal_competitor_names_are_broken_by_id(db_session: Session) -> None:
    """`name` is NOT unique, so name alone leaves the order arbitrary.

    Asserts the **expected** order -- the tie broken by ascending id -- rather than
    merely that two calls agree. An earlier version of this test called the endpoint
    three times and compared the results, which passed even with the `id` tie-break
    deleted: the same connection and plan returns the same rows in the same order
    regardless. Repeating a request proves nothing about determinism; asserting the
    order does.
    """
    first = _competitor(db_session, "Same Name")
    second = _competitor(db_session, "Same Name")
    third = _competitor(db_session, "Same Name")

    ids = [str(first.id), str(second.id), str(third.id)]
    returned = [item["id"] for item in _client(db_session).get("/competitors").json()["items"]]

    assert returned == sorted(ids)
    # And nothing collapsed or was dropped along the way.
    assert len(returned) == 3


def test_pages_with_no_name_sort_last(db_session: Session) -> None:
    """A Page the provider did not name belongs at the end, not the top.

    PostgreSQL already defaults to `NULLS LAST` for `ASC`, so this asserts the
    *observable ordering* rather than the presence of a clause -- a mutation that
    dropped the explicit `.nulls_last()` would still pass, and that is correct,
    because it would still behave the same. The clause is kept for intent, and this
    test is what pins the behaviour it is protecting.
    """
    competitor = _competitor(db_session, "Aurora")
    _page(db_session, competitor_id=competitor.id, page_id="pg-z", name="Zephyr")
    _page(db_session, competitor_id=competitor.id, page_id="pg-a", name="Aster")
    _page(db_session, competitor_id=competitor.id, page_id="pg-none", name=None)

    listed = _client(db_session).get("/competitors").json()["items"][0]["pages"]
    assert [page["name"] for page in listed] == ["Aster", "Zephyr", None]


# ============================================================
# The point of the endpoint: ids round-trip into /ads
# ============================================================


def test_a_competitor_id_from_here_filters_ads(db_session: Session) -> None:
    """Without this the endpoint is decorative.

    `/ads?competitor_id=` resolves through `ad_status_by_context`, so a
    hand-inserted ad that skipped the write path would not prove anything. The ad is
    persisted the way production persists it.
    """
    aurora = _competitor(db_session, "Aurora")
    meridian = _competitor(db_session, "Meridian")
    aurora_page = _page(db_session, competitor_id=aurora.id, page_id="pg-aurora")
    meridian_page = _page(db_session, competitor_id=meridian.id, page_id="pg-meridian")
    _observe_ad(db_session, page=aurora_page, external_ad_id="ad-aurora")
    _observe_ad(db_session, page=meridian_page, external_ad_id="ad-meridian")

    client = _client(db_session)
    listed = {item["name"]: item["id"] for item in client.get("/competitors").json()["items"]}

    filtered = client.get("/ads", competitor_id=listed["Aurora"]).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["meta_ad_id"] == "ad-aurora"

    assert client.get("/ads", competitor_id=listed["Meridian"]).json()["total"] == 1


def test_a_page_id_from_here_filters_ads(db_session: Session) -> None:
    """The same round trip, one level down."""
    competitor = _competitor(db_session, "Aurora")
    wanted = _page(db_session, competitor_id=competitor.id, page_id="pg-wanted")
    other = _page(db_session, competitor_id=competitor.id, page_id="pg-other")
    _observe_ad(db_session, page=wanted, external_ad_id="ad-wanted")
    _observe_ad(db_session, page=other, external_ad_id="ad-other")

    client = _client(db_session)
    pages = client.get("/competitors").json()["items"][0]["pages"]
    by_page_id = {page["page_id"]: page["id"] for page in pages}

    filtered = client.get("/ads", facebook_page_id=by_page_id["pg-wanted"]).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["meta_ad_id"] == "ad-wanted"


def test_the_context_reports_the_same_page_id_the_directory_lists(db_session: Session) -> None:
    """One id space, so a client never has to translate.

    `/ads` reports `contexts[].facebook_page_id`; this endpoint reports `pages[].id`.
    If those ever disagreed, every per-context row would be unattributable.
    """
    competitor = _competitor(db_session, "Aurora")
    page = _page(db_session, competitor_id=competitor.id, page_id="pg-1")
    _observe_ad(db_session, page=page, external_ad_id="ad-1")

    client = _client(db_session)
    listed_page_id = client.get("/competitors").json()["items"][0]["pages"][0]["id"]
    context_page_id = client.get("/ads").json()["items"][0]["contexts"][0]["facebook_page_id"]

    assert listed_page_id == str(page.id) == context_page_id


# ============================================================
# What must NOT be in the response
# ============================================================


def test_no_provenance_field_is_exposed(db_session: Session) -> None:
    """Neither `data_origin` nor `evidence_class`.

    `models/tracking.py` is explicit that a competitor is what the operator told us
    and a Page is what a provider reported, but neither is *collected data*: the
    first collected value enters at `collection_runs`. Stamping `PROVIDER_DATA` on a
    Page would also imply the operator's own competitor list is third-party data.
    """
    schema = create_app(app_env=AppEnv.LOCAL).openapi()["components"]["schemas"]
    for name in ("CompetitorOut", "FacebookPageOut"):
        fields = set(schema[name]["properties"])
        assert not fields & {"data_origin", "evidence_class"}, name


def test_no_internal_foreign_key_is_exposed(db_session: Session) -> None:
    """`collection_run_id`, `last_status_run_id` and friends stay internal.

    The one id-looking field that is legitimate is `page_id`, the provider's own
    identity for the Page -- different from this project's key, and useful to show.
    """
    fields = set(
        create_app(app_env=AppEnv.LOCAL).openapi()["components"]["schemas"]["FacebookPageOut"][
            "properties"
        ]
    )
    assert "page_id" in fields
    assert not {f for f in fields if f.endswith("_id")} - {"id", "page_id"}


def test_no_updated_at_and_no_counts_are_invented(db_session: Session) -> None:
    """`updated_at` exists on both tables and is deliberately not copied.

    Nothing in the product acts on it yet, and shipping it would imply a freshness
    guarantee nobody has defined. Ad and collection-run counts are worse: a count
    next to a competitor name invites reading it as performance, which this product
    cannot measure at all.
    """
    fields = set(
        create_app(app_env=AppEnv.LOCAL).openapi()["components"]["schemas"]["CompetitorOut"][
            "properties"
        ]
    )
    assert not fields & {"updated_at", "ad_count", "ads_count", "run_count", "runs"}
    assert (
        "total"
        not in create_app(app_env=AppEnv.LOCAL).openapi()["components"]["schemas"][
            "CompetitorListOut"
        ]["properties"]
    )


# ============================================================
# Route registration and read-only shape
# ============================================================


def test_exactly_five_routes_are_registered() -> None:
    assert sorted(create_app(app_env=AppEnv.LOCAL).openapi()["paths"]) == [
        "/ads",
        "/ads/{ad_id}",
        "/ads/{ad_id}/snapshots",
        "/competitors",
        "/exports/ads.csv",
    ]


def test_every_route_is_still_a_get() -> None:
    """Nothing may trigger work, so nothing may be anything but a read.

    `/competitors` is in the same process that can schedule collection runs and
    submit AI jobs, so "read-only" is a claim worth pinning rather than assuming.
    """
    spec = create_app(app_env=AppEnv.LOCAL).openapi()
    for path, operations in spec["paths"].items():
        assert set(operations) == {"get"}, f"{path} exposes {sorted(operations)}"


def test_the_endpoint_takes_no_query_parameters(db_session: Session) -> None:
    """Smallest correct read: no filters to invent semantics for.

    `is_tracked` and `country` are exposed on each Page for a client to filter; a
    server-side filter would be a contract nobody has needed yet.
    """
    spec = create_app(app_env=AppEnv.LOCAL).openapi()
    assert spec["paths"]["/competitors"]["get"].get("parameters", []) == []


def test_docs_and_openapi_gating_is_unchanged() -> None:
    """S3.3 added a route; it did not change when the schema is served."""
    prod = create_app(app_env=AppEnv.PROD)
    assert prod.docs_url is None
    assert prod.openapi_url is None
    assert "/competitors" in prod.openapi()["paths"]

    local = create_app(app_env=AppEnv.LOCAL)
    assert local.docs_url == "/docs"
    assert local.openapi_url == "/openapi.json"


def test_the_response_is_closed_to_unexpected_fields() -> None:
    """`extra="forbid"`, so a leak is a failure rather than a disclosure."""
    schemas = create_app(app_env=AppEnv.LOCAL).openapi()["components"]["schemas"]
    for name in ("CompetitorListOut", "CompetitorOut", "FacebookPageOut"):
        assert schemas[name]["additionalProperties"] is False, name

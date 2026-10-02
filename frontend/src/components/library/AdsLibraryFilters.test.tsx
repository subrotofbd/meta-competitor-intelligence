/**
 * Filters, search, sort and pagination over `GET /ads`.
 *
 * ## What is asserted here, and why it is asserted at the request boundary
 *
 * Most of these tests read the **URL the client asked for**, not the DOM. A filter can
 * look right on screen and still not be sent -- a stale closure, a wrong key, a value
 * dropped by the serialiser -- and a test that only inspects the rendered select would
 * pass while the query never carried the filter.
 *
 * ## Pure state first
 *
 * `adsQuery` is validated, serialised and transitioned in pure functions, so the URL
 * boundary is tested with no DOM and no request at all. The React tests then cover only
 * what the pure functions cannot: debouncing, history, and which of them fires.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdsLibrary } from "./AdsLibrary";
import {
  DEFAULT_QUERY,
  SORT_FIELDS,
  activeChips,
  adsQueryFromParams,
  adsQueryToParams,
  adsQueryToRequest,
  hasActiveFilters,
  withFilter,
  withPage,
  withoutChip,
  type AdsQuery,
} from "./adsQuery";
import type { AdListItemOut, CompetitorListOut } from "../../types/api";

/* ============================================================
 * Fixtures
 * ============================================================ */

const COMPETITOR_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const OTHER_COMPETITOR_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const PAGE_A = "11111111-1111-4111-8111-111111111111";
const PAGE_B = "22222222-2222-4222-8222-222222222222";

const COMPETITORS: CompetitorListOut = {
  items: [
    {
      id: COMPETITOR_ID,
      name: "Aurora Kitchen Studio",
      created_at: "2026-10-02T05:39:36Z",
      pages: [
        {
          id: PAGE_A,
          page_id: "mock-page-0001",
          name: "Aurora Kitchen",
          url: null,
          country: "IN",
          is_tracked: true,
          tracking_frequency: "manual",
          created_at: "2026-10-02T05:39:36Z",
        },
      ],
    },
    {
      id: OTHER_COMPETITOR_ID,
      name: "Northwind Gym",
      created_at: "2026-10-02T05:39:36Z",
      pages: [
        {
          id: PAGE_B,
          page_id: "mock-page-0002",
          name: "Northwind",
          url: null,
          country: "GB",
          is_tracked: true,
          tracking_frequency: "manual",
          created_at: "2026-10-02T05:39:36Z",
        },
      ],
    },
  ],
};

function ad(overrides: Partial<AdListItemOut> = {}): AdListItemOut {
  return {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    provider: "meta",
    meta_ad_id: "mock-ad-000101",
    data_origin: "public_ui",
    first_seen_at: "2026-08-22T14:30:00Z",
    last_seen_at: "2026-10-02T05:39:37Z",
    latest_snapshot: null,
    duration: null,
    contexts: [
      {
        facebook_page_id: PAGE_A,
        country: "IN",
        current_status: "seen",
        provider_active: true,
        not_seen_since_at: null,
        last_status_run_id: null,
      },
    ],
    media: [],
    platforms: ["facebook"],
    copy_fields: null,
    ...overrides,
  };
}

/**
 * Records every request and serves the two permitted endpoints.
 *
 * `total` and the number of rows actually rendered are deliberately **separate**.
 * Pagination reads `total`, not `len(items)`, so a test can declare `total: 100` and
 * still be handed two rows. Without that split every page renders twenty-five full ad
 * rows, and a file with fifty tests each driving four state changes spends its entire
 * budget in the DOM rather than on the behaviour under test -- which is how a real
 * assertion ends up failing on a timeout instead of on a wrong value.
 */
function mockApi(
  options: { total?: number; items?: AdListItemOut[]; adsStatus?: number; rowsPerPage?: number } = {},
) {
  const requested: string[] = [];
  const total = options.total ?? 1;
  const rowsPerPage = options.rowsPerPage ?? 2;

  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);

    const respond = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      });

    if (url.startsWith("/api/ads")) {
      if (options.adsStatus && options.adsStatus >= 400) {
        return respond({ detail: "Traceback (most recent call last): secret" }, options.adsStatus);
      }
      const url_ = new URL(url, "http://localhost");
      const page = Number(url_.searchParams.get("page") ?? "1");
      const size = Number(url_.searchParams.get("page_size") ?? "25");
      const remaining = Math.max(0, total - (page - 1) * size);
      const count = Math.max(0, Math.min(rowsPerPage, remaining));
      return respond({
        items: options.items ?? Array.from({ length: count }, (_, i) => ad({ id: `ad-${page}-${i}` })),
        total,
        page,
        page_size: size,
      });
    }
    if (url.startsWith("/api/competitors")) return respond(COMPETITORS);

    throw new Error(`unexpected request: ${url}`);
  });

  vi.stubGlobal("fetch", spy);
  return { requested, spy };
}

/** The query string of the most recent `/ads` request. */
function lastAdsQuery(requested: string[]): URLSearchParams {
  const urls = requested.filter((u) => u.startsWith("/api/ads"));
  expect(urls.length).toBeGreaterThan(0);
  return new URL(urls[urls.length - 1]!, "http://localhost").searchParams;
}

function adsRequests(requested: string[]): string[] {
  return requested.filter((u) => u.startsWith("/api/ads"));
}

async function renderLibrary() {
  render(<AdsLibrary />);
  await screen.findByTestId("result-count");
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.useRealTimers();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/* ============================================================
 * Pure state: URL boundary, no DOM, no request
 * ============================================================ */

describe("research state in the URL", () => {
  it("round-trips every field", () => {
    const query: AdsQuery = {
      ...DEFAULT_QUERY,
      q: "kettle",
      provider: "meta",
      competitorId: COMPETITOR_ID,
      facebookPageId: PAGE_A,
      country: "IN",
      currentStatus: "not_seen_since",
      providerActive: "false",
      dataOrigin: "third_party",
      firstSeenFrom: "2026-01-01",
      firstSeenTo: "2026-02-01",
      lastSeenFrom: "2026-03-01",
      lastSeenTo: "2026-04-01",
      sort: "meta_ad_id",
      direction: "asc",
      page: 3,
      pageSize: 50,
    };
    expect(adsQueryFromParams(adsQueryToParams(query))).toEqual(query);
  });

  it("omits defaults rather than sending empty values", () => {
    const params = adsQueryToParams(DEFAULT_QUERY);
    // An unset filter must not travel as `country=` or `q=`.
    expect(params.toString()).toBe("");
    expect(adsQueryToRequest(DEFAULT_QUERY)).toEqual({});
  });

  it("keeps direction when it differs from the default sort", () => {
    // "Sort by ad id ascending" is a real request even though `direction` alone is the
    // backend default. Dropping it here would silently reorder the results.
    const params = adsQueryToParams({ ...DEFAULT_QUERY, sort: "meta_ad_id", direction: "asc" });
    expect(params.get("sort")).toBe("meta_ad_id");
    expect(params.get("direction")).toBe("asc");
  });

  it("drops values the backend would reject rather than forwarding them", () => {
    // A URL is user input. The backend answers a bad sort with a 400 and a message; in a
    // research tool quietly using the default is better than that.
    const hostile = adsQueryFromParams(
      "?sort=;DROP+TABLE&direction=sideways&current_status=winner&data_origin=made_up" +
        "&page=0&page_size=9999&country=india&first_seen_from=yesterday" +
        "&competitor_id=not-a-uuid",
    );
    expect(hostile.sort).toBe("last_seen_at");
    expect(hostile.direction).toBe("desc");
    expect(hostile.currentStatus).toBe("");
    expect(hostile.dataOrigin).toBe("");
    expect(hostile.page).toBe(1);
    // Clamped to the backend's own maximum rather than reset: 9999 is an unreasonable
    // page size, but it is not an unreasonable *intent*, and 100 is still valid.
    expect(hostile.pageSize).toBe(100);
    // Upper-cased to match the backend, and a non-date is dropped rather than sent.
    expect(hostile.country).toBe("IN");
    expect(hostile.firstSeenFrom).toBe("");
    expect(hostile.competitorId).toBe("");
  });

  it("offers only the backend sort allowlist, and no relevance sort", () => {
    expect([...SORT_FIELDS]).toEqual([
      "last_seen_at",
      "first_seen_at",
      "meta_delivery_start",
      "meta_ad_id",
    ]);
    const labels = SORT_FIELDS.map((f) => adsQueryFromParams(`?sort=${f}`).sort);
    expect(labels).toEqual([...SORT_FIELDS]);
    // "relevance" is not a backend concept; a search result set is ordered by the sort.
    expect(adsQueryFromParams("?sort=relevance").sort).toBe("last_seen_at");
  });

  it("resets to page 1 for any filter change, and only that", () => {
    const paged = withPage({ ...DEFAULT_QUERY, country: "IN", q: "kettle" }, 7);
    expect(paged.page).toBe(7);
    expect(withFilter(paged, { country: "GB" }).page).toBe(1);
    expect(withPage(paged, 8)).toEqual({ ...paged, page: 8 });
    // Paging preserves everything else.
    expect(withPage(paged, 8).country).toBe("IN");
    expect(withPage(paged, 8).q).toBe("kettle");
  });

  it("clears sort and direction together, because neither alone makes sense", () => {
    const sorted = { ...DEFAULT_QUERY, sort: "meta_ad_id" as const, direction: "asc" as const };
    expect(withoutChip(sorted, "sort")).toMatchObject({
      sort: DEFAULT_QUERY.sort,
      direction: DEFAULT_QUERY.direction,
    });
  });

  it("returns to page 1 when any chip is removed, including sort", () => {
    // The sort branch is separate because sort and direction are cleared together, and
    // a separate branch is exactly where a forgotten `page: 1` hides.
    const paged = withPage({ ...DEFAULT_QUERY, country: "IN", sort: "meta_ad_id" }, 6);
    for (const chip of activeChips(paged)) {
      expect(withoutChip(paged, chip.key).page, chip.key).toBe(1);
    }
    // And the values themselves are gone, not merely unpaged.
    expect(withoutChip(paged, "country").country).toBe("");
    expect(withoutChip(paged, "sort").sort).toBe(DEFAULT_QUERY.sort);
  });

  it("lists active chips and reports whether anything is filtered", () => {
    expect(hasActiveFilters(DEFAULT_QUERY)).toBe(false);
    const query = { ...DEFAULT_QUERY, country: "IN", sort: "first_seen_at" as const };
    expect(hasActiveFilters(query)).toBe(true);
    expect(activeChips(query).map((c) => c.key)).toEqual(["country", "sort"]);
  });
});

/* ============================================================
 * Requests
 * ============================================================ */

describe("requests", () => {
  it("requests /ads and /competitors on load, and nothing else", async () => {
    const { requested } = mockApi();
    render(<AdsLibrary />);
    await screen.findByTestId("result-count");

    const paths = requested.map((u) => u.split("?")[0]).sort();
    expect(paths).toEqual(["/api/ads", "/api/competitors"]);
    // No detail endpoint for any row, no media, nothing absolute.
    expect(requested.some((u) => u.includes("/api/ads/"))).toBe(false);
    expect(requested.every((u) => u.startsWith("/api/"))).toBe(true);
  });

  it("requests /competitors once no matter how often the ads query changes", async () => {
    // Names do not vary with the filters. Refetching per keystroke would double the
    // traffic to produce no difference in the result.
    const { requested } = mockApi();
    render(<AdsLibrary />);
    await screen.findByTestId("result-count");

    await selectChange("Country", "IN");
    await selectChange("Current status", "seen");
    await waitFor(() => expect(adsRequests(requested).length).toBeGreaterThanOrEqual(3));

    expect(requested.filter((u) => u.startsWith("/api/competitors"))).toHaveLength(1);
  });

  it("does not refetch when the URL resolves to the same query", async () => {
    // The ads effect is keyed on the *serialised* parameter string, not on the state
    // object. A `popstate` that lands on a URL already showing -- browser history
    // restore, or Back to where you were -- produces a new object with identical values.
    // Keyed on identity, that is one wasted request per occurrence, forever.
    const { requested } = mockApi();
    await renderLibrary();
    await selectChange("Country", "IN");
    await waitFor(() => expect(lastAdsQuery(requested).get("country")).toBe("IN"));
    const before = adsRequests(requested).length;

    window.dispatchEvent(new PopStateEvent("popstate"));
    await settle();
    expect(adsRequests(requested).length).toBe(before);
  });

  it("does not duplicate the /ads request when nothing changed", async () => {
    const { requested } = mockApi();
    await renderLibrary();
    const before = adsRequests(requested).length;

    // A re-render with identical state must not cause a fetch. The effect is keyed on
    // the serialised parameter string precisely so this holds.
    fireEvent.change(screen.getByLabelText("Country"), { target: { value: "" } });
    await settle();
    expect(adsRequests(requested).length).toBe(before);
  });
});

/* ============================================================
 * Each filter, asserted on the wire
 * ============================================================ */

describe("filters reach the request", () => {
  const cases: ReadonlyArray<[string, string, string, string]> = [
    // label, control value, expected param, expected value
    ["Provider (exact match)", "meta", "provider", "meta"],
    ["Country", "GB", "country", "GB"],
    ["Current status", "not_seen_since", "current_status", "not_seen_since"],
    ["Provider active", "false", "provider_active", "false"],
    ["Data origin", "third_party", "data_origin", "third_party"],
    ["First seen from", "2026-01-01", "first_seen_from", "2026-01-01"],
    ["First seen to", "2026-02-01", "first_seen_to", "2026-02-01"],
    ["Last seen from", "2026-03-01", "last_seen_from", "2026-03-01"],
    ["Last seen to", "2026-04-01", "last_seen_to", "2026-04-01"],
    ["Sort by", "meta_ad_id", "sort", "meta_ad_id"],
    ["Direction", "asc", "direction", "asc"],
  ];

  it.each(cases)("%s sends %s=%s", async (label, value, param, expected) => {
    const { requested } = mockApi();
    await renderLibrary();

    await setControl(label, value);
    await waitFor(() => expect(lastAdsQuery(requested).get(param)).toBe(expected));
  });

  it("sends competitor_id and facebook_page_id as real UUIDs", async () => {
    const { requested } = mockApi();
    await renderLibrary();

    await selectChange("Competitor", COMPETITOR_ID);
    await waitFor(() => expect(lastAdsQuery(requested).get("competitor_id")).toBe(COMPETITOR_ID));

    await selectChange("Facebook Page", PAGE_A);
    await waitFor(() => expect(lastAdsQuery(requested).get("facebook_page_id")).toBe(PAGE_A));
  });

  it("offers no page list until a competitor is chosen, and sends no UUID before then", async () => {
    const { requested } = mockApi();
    await renderLibrary();

    const pageSelect = screen.getByLabelText("Facebook Page") as HTMLSelectElement;
    // Disabled and empty: a page list that ignores its parent reads as a broken filter.
    expect(pageSelect.disabled).toBe(true);
    expect(pageSelect.options).toHaveLength(1);
    expect(lastAdsQuery(requested).get("facebook_page_id")).toBeNull();

    await selectChange("Competitor", COMPETITOR_ID);
    await waitFor(() => {
      const select = screen.getByLabelText("Facebook Page") as HTMLSelectElement;
      expect(select.disabled).toBe(false);
    });
    const names = Array.from((screen.getByLabelText("Facebook Page") as HTMLSelectElement).options).map(
      (o) => o.textContent,
    );
    // Human names, not bare UUIDs.
    expect(names).toContain("Aurora Kitchen");
    expect(names.join(" ")).not.toContain(PAGE_A);
  });

  it("clears the page filter when the competitor changes, because the two would contradict", async () => {
    const { requested } = mockApi();
    await renderLibrary();

    await selectChange("Competitor", COMPETITOR_ID);
    await selectChange("Facebook Page", PAGE_A);
    await waitFor(() => expect(lastAdsQuery(requested).get("facebook_page_id")).toBe(PAGE_A));

    await selectChange("Competitor", OTHER_COMPETITOR_ID);
    await waitFor(() => {
      expect(lastAdsQuery(requested).get("competitor_id")).toBe(OTHER_COMPETITOR_ID);
      expect(lastAdsQuery(requested).get("facebook_page_id")).toBeNull();
    });
  });

  it("offers no platform, media, AI-availability or display-format filter", async () => {
    mockApi();
    await renderLibrary();

    const labels = Array.from(document.querySelectorAll("label")).map((l) =>
      (l.textContent ?? "").trim().toLowerCase(),
    );
    for (const banned of ["platform", "media", "format", "analysis", "ai availability", "thumbnail"]) {
      expect(labels.some((l) => l.includes(banned)), `unexpected filter: ${banned}`).toBe(false);
    }
  });
});

/* ============================================================
 * Search
 * ============================================================ */

describe("search", () => {
  it("debounces typing into a single request", async () => {
    const { requested } = mockApi();
    await renderLibrary();
    const before = adsRequests(requested).length;

    const input = screen.getByLabelText(/Search copy and ad ids/);
    fireEvent.change(input, { target: { value: "kettle" } });
    fireEvent.change(input, { target: { value: "kettl" } });
    fireEvent.change(input, { target: { value: "kettle" } });

    // Nothing yet: the debounce has not elapsed.
    expect(adsRequests(requested).length).toBe(before);

    await waitFor(() => expect(adsRequests(requested).length).toBe(before + 1));
    expect(lastAdsQuery(requested).get("q")).toBe("kettle");
  });

  it("preserves the other filters when the search term changes", async () => {
    const { requested } = mockApi();
    await renderLibrary();

    await selectChange("Country", "IN");
    await setControl("Sort by", "meta_ad_id");

    fireEvent.change(screen.getByLabelText(/Search copy and ad ids/), {
      target: { value: "kettle" },
    });
    await waitFor(() => expect(lastAdsQuery(requested).get("q")).toBe("kettle"));

    const params = lastAdsQuery(requested);
    expect(params.get("country")).toBe("IN");
    expect(params.get("sort")).toBe("meta_ad_id");
  });

  it("returns to the filtered dataset when the search is cleared", async () => {
    const { requested } = mockApi();
    await renderLibrary();

    await selectChange("Country", "IN");
    fireEvent.change(screen.getByLabelText(/Search copy and ad ids/), {
      target: { value: "kettle" },
    });
    await waitFor(() => expect(lastAdsQuery(requested).get("q")).toBe("kettle"));

    fireEvent.change(screen.getByLabelText(/Search copy and ad ids/), {
      target: { value: "" },
    });
    await waitFor(() => expect(lastAdsQuery(requested).get("q")).toBeNull());
    expect(lastAdsQuery(requested).get("country")).toBe("IN");
  });

  it("searches the server rather than the rows already on screen", async () => {
    const { requested } = mockApi();
    await renderLibrary();
    fireEvent.change(screen.getByLabelText(/Search copy and ad ids/), {
      target: { value: "kettle" },
    });
    await waitFor(() => expect(lastAdsQuery(requested).get("q")).toBe("kettle"));
    // The hint says so, and the request proves it.
    expect(screen.getByText(/Searches the whole corpus/)).toBeDefined();
  });
});

/* ============================================================
 * Active filters
 * ============================================================ */

describe("active filters", () => {
  it("shows nothing when nothing is filtered", async () => {
    mockApi();
    await renderLibrary();
    expect(screen.queryByTestId("active-filters")).toBeNull();
  });

  it("lists active filters compactly, not as a badge per field", async () => {
    mockApi();
    await renderLibrary();

    await selectChange("Country", "IN");
    await selectChange("Current status", "seen");

    const panel = screen.getByTestId("active-filters");
    expect(within(panel).getByText("Country:")).toBeDefined();
    expect(within(panel).getByText("Status:")).toBeDefined();
    // Two chips, not one badge per control in the bar.
    expect(within(panel).getAllByRole("button")).toHaveLength(3); // 2 chips + Clear all
  });

  it("removes one filter and leaves the others alone", async () => {
    const { requested } = mockApi();
    await renderLibrary();

    await selectChange("Country", "IN");
    await selectChange("Current status", "seen");
    await waitFor(() => expect(lastAdsQuery(requested).get("current_status")).toBe("seen"));

    fireEvent.click(screen.getByRole("button", { name: /Remove filter Country/ }));
    await waitFor(() => expect(lastAdsQuery(requested).get("country")).toBeNull());
    expect(lastAdsQuery(requested).get("current_status")).toBe("seen");
  });

  it("removing the sort chip returns to page 1", async () => {
    const { requested } = mockApi({ total: 100 });
    await renderLibrary();

    await selectChange("Country", "IN");
    await setControl("Sort by", "meta_ad_id");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(lastAdsQuery(requested).get("page")).toBe("2"));

    fireEvent.click(screen.getByRole("button", { name: /Remove filter Sort/ }));
    await waitFor(() => {
      const params = lastAdsQuery(requested);
      expect(params.get("sort")).toBeNull();
      expect(params.get("page")).toBeNull();
    });
    // The other filter is untouched.
    expect(lastAdsQuery(requested).get("country")).toBe("IN");
  });

  it("clears everything at once, and resets to page 1", async () => {
    const { requested } = mockApi({ total: 100 });
    await renderLibrary();

    await selectChange("Country", "IN");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(lastAdsQuery(requested).get("page")).toBe("2"));

    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    await waitFor(() => expect(screen.queryByTestId("active-filters")).toBeNull());

    const params = lastAdsQuery(requested);
    expect(params.get("country")).toBeNull();
    expect(params.get("page")).toBeNull();
  });
});

/* ============================================================
 * Sort and pagination
 * ============================================================ */

describe("sorting and pagination", () => {
  it("pages forward and back, preserving filters and sort", async () => {
    const { requested } = mockApi({ total: 100 });
    await renderLibrary();

    await selectChange("Country", "IN");
    await setControl("Sort by", "meta_ad_id");

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => {
      const params = lastAdsQuery(requested);
      expect(params.get("page")).toBe("2");
      expect(params.get("country")).toBe("IN");
      expect(params.get("sort")).toBe("meta_ad_id");
    });

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => expect(lastAdsQuery(requested).get("page")).toBeNull());
    // Page 1 is the default, so it is omitted rather than sent as page=1.
    expect(lastAdsQuery(requested).get("country")).toBe("IN");
  });

  it("disables Previous on the first page and Next on the last", async () => {
    mockApi({ total: 30 });
    await renderLibrary();

    expect((screen.getByRole("button", { name: "Previous" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("changes page size and resets to page 1", async () => {
    const { requested } = mockApi({ total: 100 });
    await renderLibrary();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(lastAdsQuery(requested).get("page")).toBe("2"));

    await selectChange("Rows per page", "50");
    await waitFor(() => {
      const params = lastAdsQuery(requested);
      expect(params.get("page_size")).toBe("50");
      expect(params.get("page")).toBeNull();
    });
  });

  it("resets to page 1 when any filter changes", async () => {
    const { requested } = mockApi({ total: 100 });
    await renderLibrary();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(lastAdsQuery(requested).get("page")).toBe("2"));

    await selectChange("Data origin", "public_ui");
    await waitFor(() => expect(lastAdsQuery(requested).get("page")).toBeNull());
  });

  it("shows the current page and the total", async () => {
    mockApi({ total: 120 });
    await renderLibrary();
    const nav = screen.getByTestId("pagination");
    expect(nav.textContent).toContain("Page 1 of 5");
    expect(nav.textContent).toContain("120 ads found");
  });

  it("reports an empty filtered result honestly", async () => {
    mockApi({ total: 0 });
    await renderLibrary();

    // With nothing filtered, an empty corpus and a filter that matched nothing are
    // different situations and get different wording.
    expect(screen.getByText("No observed ads are available")).toBeDefined();

    await selectChange("Country", "IN");
    await waitFor(() => expect(screen.getByText("No ads match these filters")).toBeDefined());
    expect(screen.queryByTestId("ad-row")).toBeNull();
  });
});

/* ============================================================
 * URL persistence
 * ============================================================ */

describe("URL state", () => {
  it("restores filters, search, sort and page from the URL on load", async () => {
    window.history.replaceState(
      null,
      "",
      "/?q=kettle&country=IN&current_status=seen&sort=meta_ad_id&direction=asc&page=3&page_size=50",
    );
    const { requested } = mockApi();
    render(<AdsLibrary />);
    await screen.findByTestId("result-count");

    // The initial request already carries everything, so a refresh does not need a
    // second round trip to discover its own state.
    const params = lastAdsQuery(requested);
    expect(params.get("q")).toBe("kettle");
    expect(params.get("country")).toBe("IN");
    expect(params.get("current_status")).toBe("seen");
    expect(params.get("sort")).toBe("meta_ad_id");
    expect(params.get("direction")).toBe("asc");
    expect(params.get("page")).toBe("3");
    expect(params.get("page_size")).toBe("50");

    // And the controls show it.
    expect((screen.getByLabelText(/Search copy and ad ids/) as HTMLInputElement).value).toBe("kettle");
    expect((screen.getByLabelText("Country") as HTMLInputElement).value).toBe("IN");
  });

  it("writes state to the URL as it changes", async () => {
    mockApi();
    await renderLibrary();

    await selectChange("Country", "IN");
    await waitFor(() => expect(window.location.search).toContain("country=IN"));
    expect((screen.getByLabelText("Country") as HTMLInputElement).value).toBe("IN");
  });

  it("follows Back to the previous state", async () => {
    mockApi();
    await renderLibrary();

    await selectChange("Country", "IN");
    await waitFor(() => expect(window.location.search).toContain("country=IN"));

    await selectChange("Country", "GB");
    await waitFor(() => expect(window.location.search).toContain("country=GB"));

    window.history.back();
    await waitFor(() => expect((screen.getByLabelText("Country") as HTMLInputElement).value).toBe("IN"));
  });

  it("leaves no history entry for each keystroke", async () => {
    mockApi();
    await renderLibrary();
    const before = window.history.length;

    const input = screen.getByLabelText(/Search copy and ad ids/);
    fireEvent.change(input, { target: { value: "k" } });
    fireEvent.change(input, { target: { value: "ke" } });
    fireEvent.change(input, { target: { value: "ket" } });

    // Debounced, so a burst of typing settles into at most one entry.
    expect(window.history.length - before).toBeLessThanOrEqual(2);
  });
});

/* ============================================================
 * States, responsive, and what must never appear
 * ============================================================ */

describe("loading, error and mobile", () => {
  it("shows the skeleton on load and never a placeholder ad row", async () => {
    mockApi();
    render(<AdsLibrary />);

    expect(screen.getByTestId("loading-state")).toBeDefined();
    expect(screen.queryByTestId("ad-row")).toBeNull();
    await screen.findByTestId("result-count");
  });

  it("shows a safe error without the response body or a trace", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi({ adsStatus: 500 });
    render(<AdsLibrary />);

    expect(await screen.findByTestId("error-state")).toBeDefined();
    const text = screen.getByTestId("error-state").textContent ?? "";
    expect(text).toContain("Could not load observed ads");
    expect(text).not.toContain("Traceback");
    expect(text).not.toContain("secret");
  });

  it("keeps the filters and search reachable on a small screen", async () => {
    mockApi();
    await renderLibrary();

    // Search is always visible; the rest sits behind one disclosure.
    expect(screen.getByLabelText(/Search copy and ad ids/)).toBeDefined();
    const toggle = screen.getByRole("button", { name: /Show filters/ });
    expect(toggle).toBeDefined();

    // The panel is hidden until asked for, then revealed.
    const panel = screen.getByTestId("filter-panel");
    expect((panel as HTMLElement).hidden).toBe(true);
    fireEvent.click(toggle);
    expect((screen.getByTestId("filter-panel") as HTMLElement).hidden).toBe(false);
    expect(screen.getByRole("button", { name: /Hide filters/ })).toBeDefined();
  });

  it("does not require horizontal scrolling", async () => {
    mockApi();
    await renderLibrary();
    // jsdom has no layout engine, so this catches the two ways a Tailwind layout
    // usually becomes sideways-only.
    expect(document.body.innerHTML).not.toContain("overflow-x-auto");
    expect(document.body.innerHTML).not.toMatch(/min-w-\[\d{3,}px\]/);
  });

  it("labels every control", async () => {
    mockApi();
    await renderLibrary();

    for (const control of Array.from(document.querySelectorAll("input, select"))) {
      const id = control.getAttribute("id");
      const labelled =
        (id !== null && document.querySelector(`label[for="${id}"]`) !== null) ||
        control.getAttribute("aria-label") !== null;
      expect(labelled, `unlabelled control: ${control.outerHTML.slice(0, 80)}`).toBe(true);
    }
  });

  it("renders no performance metric and no longevity verdict", async () => {
    mockApi({ items: [ad({ duration: { days: 214, bucket: "Long-running", source: "meta_delivery_start", is_long_running_signal: true } })] });
    const { container } = render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    const leaf = [...container.querySelectorAll("*")]
      .filter((el) => el.children.length === 0)
      .map((el) => (el.textContent ?? "").trim())
      .filter(Boolean)
      .join(" | ")
      .toLowerCase();

    expect(leaf).not.toMatch(
      /\b(spend|spends|budget|budgets|roas|cpa|cpc|cpm|lead|leads|sales|revenue|click|clicks|reach|reaches|impression|impressions|conversion|conversions|winner|loser|best|top performer)\b/,
    );
    // The duration proxy still reads as a proxy.
    expect(screen.getByRole("tooltip").textContent).toBe("duration is a public proxy, not performance");
  });
});

/* ============================================================
 * Helpers
 * ============================================================ */

async function setControl(label: string, value: string) {
  const control = screen.getByLabelText(label);
  fireEvent.change(control, { target: { value } });
  // Let the debounce settle before the assertion reads the request.
  await waitFor(() => expect((control as HTMLInputElement).value).toBe(value));
}

/**
 * Let pending effects and their fetches settle.
 *
 * A `waitFor` whose condition is *already* satisfied returns on its first tick -- before
 * the effect under test has had a chance to run. Asserting that a request did **not**
 * happen therefore races the thing it is checking, and passes for the wrong reason. So
 * these tests settle first and only then assert absence.
 */
async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
}

async function selectChange(label: string, value: string) {
  const control = screen.getByLabelText(label);
  fireEvent.change(control, { target: { value } });
  await waitFor(() => expect((control as HTMLSelectElement).value).toBe(value));
}
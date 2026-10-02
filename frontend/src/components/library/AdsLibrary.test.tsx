/**
 * Focused tests for the Ad Library screen.
 *
 * ## Fixtures are hand-built from the real response shape
 *
 * The shapes here were read off live `/ads` and `/competitors` payloads, and then
 * rewritten with fixed placeholder UUIDs. Two reasons for hand-building rather than
 * committing a dump:
 *
 * - A dump captured from a seeded database is environment state. It would make this test
 *   fail the moment someone re-seeds, for a reason that has nothing to do with the grid.
 * - The seeded data has exactly **one context per ad** and one ad with `platforms: []`.
 *   Multi-context rendering is a stated requirement and the demo data cannot exercise
 *   it, so those cases have to be constructed.
 *
 * The requirement cases that the demo data genuinely does contain -- a real `0`-day
 * duration, a `[]` platform list, `provider_active: null` -- are all represented.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdsLibrary } from "./AdsLibrary";
import { NO_PLATFORMS_RECORDED } from "./AdsGrid";
import { LONG_RUNNING_TOOLTIP } from "../provenance/DurationSignal";
import type { AdListOut, CompetitorListOut, AdListItemOut, ContextOut } from "../../types/api";

/* ============================================================
 * Fixtures
 * ============================================================ */

const PAGE_1 = "11111111-1111-4111-8111-111111111111";
const PAGE_2 = "22222222-2222-4222-8222-222222222222";
const PAGE_UNKNOWN = "99999999-9999-4999-8999-999999999999";

function context(overrides: Partial<ContextOut> = {}): ContextOut {
  return {
    facebook_page_id: PAGE_1,
    country: "IN",
    current_status: "seen",
    provider_active: true,
    not_seen_since_at: null,
    last_status_run_id: null,
    ...overrides,
  };
}

function item(overrides: Partial<AdListItemOut> = {}): AdListItemOut {
  return {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    provider: "meta",
    meta_ad_id: "mock-ad-000101",
    data_origin: "public_ui",
    first_seen_at: "2026-08-22T14:30:00Z",
    last_seen_at: "2026-10-02T05:39:37Z",
    latest_snapshot: null,
    duration: null,
    contexts: [context()],
    media: [],
    platforms: ["facebook"],
    // Always present in the real response, so the fixture always has it too. A fixture
    // that omits a required field tests a shape the server never sends.
    copy_fields: {
      primary_text: "A kettle that actually whistles.",
      headline: "Still whistling after 5,000 boils",
      description: "Packaging claim, unchanged test method.",
      cta: "SHOP_NOW",
      destination_url: "https://aurora.example.invalid/kettle/box-copy",
    },
    ...overrides,
  };
}

function list(items: AdListItemOut[], total = items.length): AdListOut {
  return { items, total, page: 1, page_size: 25 };
}

const DIRECTORY: CompetitorListOut = {
  items: [
    {
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      name: "Aurora Kitchen Studio",
      created_at: "2026-10-02T05:39:36Z",
      pages: [
        {
          id: PAGE_1,
          page_id: "mock-page-0001",
          // Deliberately different from the competitor name. Real data often shares a
          // brand name across both, and a test that then asserts on the text is really
          // asserting "this string appears somewhere", which proves nothing about which
          // of the two rendered.
          name: "Aurora Kitchen",
          url: null,
          country: "IN",
          is_tracked: true,
          tracking_frequency: "manual",
          created_at: "2026-10-02T05:39:36Z",
        },
        {
          id: PAGE_2,
          page_id: "mock-page-0003",
          name: "Coastal Ayurveda",
          url: null,
          country: "IN",
          is_tracked: true,
          tracking_frequency: "manual",
          created_at: "2026-10-02T05:39:36Z",
        },
      ],
    },
  ],
};

/** Routes the two permitted URLs and records every URL actually requested. */
function mockApi(handlers: {
  ads?: () => Promise<Response> | Response;
  competitors?: () => Promise<Response> | Response;
}) {
  const requested: string[] = [];

  const respond = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  const fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);

    if (url.startsWith("/api/ads")) {
      return handlers.ads ? handlers.ads() : respond(list([item()]));
    }
    if (url.startsWith("/api/competitors")) {
      return handlers.competitors ? handlers.competitors() : respond(DIRECTORY);
    }

    // Anything else is a bug: the grid is permitted exactly two endpoints.
    throw new Error(`unexpected request: ${url}`);
  });

  vi.stubGlobal("fetch", fetchSpy);
  return { requested, fetchSpy };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/* ============================================================
 * The two permitted requests
 * ============================================================ */

describe("the Ad Library screen", () => {
  it("renders ads returned by /ads", async () => {
    mockApi({
      ads: () =>
        json(
          list([
            item({ id: "ad-1", meta_ad_id: "mock-ad-000101" }),
            item({ id: "ad-2", meta_ad_id: "mock-ad-000102", platforms: ["facebook", "instagram"] }),
          ]),
        ),
    });

    render(<AdsLibrary />);

    expect(await screen.findAllByTestId("ad-row")).toHaveLength(2);
    expect(screen.getByText("mock-ad-000101")).toBeDefined();
    expect(screen.getByText("mock-ad-000102")).toBeDefined();
    expect(screen.getByTestId("result-count").textContent).toContain("2");
  });

  it("requests only /ads and /competitors, and nothing else", async () => {
    // The concrete risk is a grid that fans out to `/ads/{id}` per row, which would be
    // one request per row and would pre-empt the detail screen. Step 6A exists so the
    // copy arrives in the list response and this stays at two requests.
    const { requested } = mockApi({
      ads: () =>
        json(
          list([
            item({ id: "ad-1", meta_ad_id: "mock-ad-1" }),
            item({ id: "ad-2", meta_ad_id: "mock-ad-2" }),
            item({ id: "ad-3", meta_ad_id: "mock-ad-3" }),
          ]),
        ),
    });
    render(<AdsLibrary />);

    await waitFor(() => expect(screen.getAllByTestId("ad-row")).toHaveLength(3));

    // Three rows, still two requests. A per-row copy fetch would make this five.
    expect(requested).toHaveLength(2);
    const paths = requested.map((u) => u.split("?")[0]).sort();
    expect(paths).toEqual(["/api/ads", "/api/competitors"]);
    // Explicitly: no detail endpoint, for any row.
    expect(requested.some((u) => u.includes("/api/ads/"))).toBe(false);
    // And nothing absolute: no origin, no host, no port.
    expect(requested.every((u) => u.startsWith("/api/"))).toBe(true);
  });

  it("shows a loading state before the data arrives", async () => {
    // Definite assignment: the executor runs synchronously, but TypeScript's
    // control-flow analysis cannot see that and narrows the variable to `null` for
    // ever, which makes the call below an error.
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    mockApi({
      ads: async () => {
        await gate;
        return json(list([item()]));
      },
    });

    render(<AdsLibrary />);

    expect(screen.getByTestId("loading-state")).toBeDefined();
    expect(screen.getByText(/Loading observed ads/)).toBeDefined();
    // Not a fabricated row while waiting.
    expect(screen.queryByTestId("ad-row")).toBeNull();

    release();
    await waitFor(() => expect(screen.getByTestId("ad-row")).toBeDefined());
    expect(screen.queryByTestId("loading-state")).toBeNull();
  });

  it("shows an honest empty state when /ads returns nothing", async () => {
    mockApi({ ads: () => json(list([], 0)) });
    render(<AdsLibrary />);

    expect(await screen.findByTestId("empty-state")).toBeDefined();
    expect(screen.getByText("No observed ads are available")).toBeDefined();
    // Fabricating a demo row here would be the exact failure being guarded against.
    expect(screen.queryByTestId("ad-row")).toBeNull();
  });

  it("shows an error state without exposing the response body or a stack trace", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi({
      ads: () =>
        json({ detail: "Traceback (most recent call last): ... secret_table ..." }, 500),
    });

    render(<AdsLibrary />);

    expect(await screen.findByTestId("error-state")).toBeDefined();
    const text = screen.getByTestId("error-state").textContent ?? "";

    expect(text).toContain("Could not load observed ads");
    expect(text).toContain("500");
    // The body is for the console, not the screen.
    expect(text).not.toContain("Traceback");
    expect(text).not.toContain("secret_table");
    expect(screen.queryByTestId("ad-row")).toBeNull();
    expect(consoleError).toHaveBeenCalled();
  });

  it("reports an unreachable server without claiming a status", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi({
      ads: () => {
        throw new TypeError("Failed to fetch");
      },
    });

    render(<AdsLibrary />);
    expect(await screen.findByTestId("error-state")).toBeDefined();
    const text = screen.getByTestId("error-state").textContent ?? "";
    expect(text).toContain("could not be reached");
    expect(text).not.toContain("Failed to fetch");
  });
});

/* ============================================================
 * Name resolution
 * ============================================================ */

describe("competitor and page name resolution", () => {
  it("resolves a context's page UUID to its page and competitor name", async () => {
    mockApi({});
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    // Scoped to the grid: the competitor select also contains the competitor name now
    // that there is a competitor filter.
    const grid = within(screen.getByTestId("ads-grid"));
    expect(grid.getByText("Aurora Kitchen Studio")).toBeDefined();
    expect(grid.getByText("Aurora Kitchen")).toBeDefined();
    expect(grid.getByText("mock-page-0001")).toBeDefined();
  });

  it("falls back to a compact UUID when no page matches", async () => {
    // The requirement: do not invent a name. The identifier itself is shown instead.
    mockApi({ ads: () => json(list([item({ contexts: [context({ facebook_page_id: PAGE_UNKNOWN })] })])) });
    render(<AdsLibrary />);

    const fallback = await screen.findByTestId("unresolved-page");
    expect(fallback.textContent).toContain("9999");
    expect(fallback.textContent).toContain("9999".slice(-4));
    expect(fallback.getAttribute("title")).toBe(PAGE_UNKNOWN);
    expect(screen.queryByTestId("unresolved-page")?.textContent).not.toContain("Aurora");
  });

  it("renders provider-supplied names as plain text, never as markup", async () => {
    // Competitor and page names are free text from the API, so they go through SafeText.
    // A future edit that switched to dangerouslySetInnerHTML would turn this red.
    const hostile: CompetitorListOut = {
      items: [
        {
          ...DIRECTORY.items[0]!,
          name: "<script>globalThis.__pwned=1</script>",
          pages: [{ ...DIRECTORY.items[0]!.pages[0]!, name: "<img src=x onerror=alert(1)>" }],
        },
      ],
    };
    mockApi({ competitors: () => json(hostile) });
    const { container } = render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect((globalThis as Record<string, unknown>)["__pwned"]).toBeUndefined();
  });
});

/* ============================================================
 * Contexts: one ad, many contexts, never flattened
 * ============================================================ */

describe("contexts", () => {
  it("renders one row per ad, with several contexts inside that row", async () => {
    mockApi({
      ads: () =>
        json(
          list([
            item({
              contexts: [
                context({ facebook_page_id: PAGE_1, country: "IN" }),
                context({ facebook_page_id: PAGE_2, country: "GB", current_status: "not_seen_since" }),
              ],
            }),
          ]),
        ),
    });

    render(<AdsLibrary />);

    expect(await screen.findAllByTestId("ad-row")).toHaveLength(1);
    // Two contexts, two distinct countries on screen at once.
    expect(screen.getByText("IN")).toBeDefined();
    expect(screen.getByText("GB")).toBeDefined();
  });

  it("keeps multiple context statuses separate rather than flattening them", async () => {
    // The backend has no ad-level status, and neither may this screen. An ad seen in one
    // market and presumed inactive in another is the finding, not a contradiction.
    mockApi({
      ads: () =>
        json(
          list([
            item({
              contexts: [
                context({ facebook_page_id: PAGE_1, country: "IN", current_status: "seen" }),
                context({
                  facebook_page_id: PAGE_2,
                  country: "GB",
                  current_status: "presumed_inactive",
                }),
              ],
            }),
          ]),
        ),
    });

    render(<AdsLibrary />);
    await screen.findAllByTestId("ad-row");

    // Scoped to the row: the status select also offers "Seen" as an option.
    const row = within(screen.getByTestId("ad-row"));
    expect(row.getByText("Seen")).toBeDefined();
    expect(row.getByText("Presumed inactive")).toBeDefined();
    // No single merged status anywhere.
    expect(screen.queryByText("Mixed")).toBeNull();
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("stopped");
  });

  it("renders provider_active null as an em dash, never as false", async () => {
    mockApi({ ads: () => json(list([item({ contexts: [context({ provider_active: null })] })])) });
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    expect(screen.getByTestId("provider-active").textContent).toContain("—");
    expect(screen.getByTestId("provider-active").textContent).not.toContain("not reported active");
  });
});

/* ============================================================
 * Platforms
 * ============================================================ */

describe("platforms", () => {
  it("preserves the provider's order exactly", async () => {
    // Not sorted. The order is what the provider reported, and re-ordering it would
    // discard information for the sake of tidiness.
    mockApi({
      ads: () => json(list([item({ platforms: ["instagram", "facebook", "audience_network"] })])),
    });
    render(<AdsLibrary />);

    const badges = await screen.findByTestId("platform-list");
    expect([...badges.children].map((c) => c.textContent)).toEqual([
      "instagram",
      "facebook",
      "audience_network",
    ]);
  });

  it("shows an honest empty state for platforms=[] and invents nothing", async () => {
    mockApi({ ads: () => json(list([item({ platforms: [] })])) });
    render(<AdsLibrary />);

    expect(await screen.findByTestId("no-platforms")).toBeDefined();
    expect(screen.getByTestId("no-platforms").textContent).toBe(NO_PLATFORMS_RECORDED);

    // `[]` means the record lists no platforms -- never "it ran nowhere", and never a
    // guess that it was Facebook.
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("no platforms");
    const platformCell = screen.getByTestId("no-platforms").closest("[role='cell']");
    expect(platformCell?.textContent).not.toContain("facebook");
  });
});

/* ============================================================
 * Duration, provenance, nulls
 * ============================================================ */

describe("duration and provenance", () => {
  it("renders days, bucket, source, and the exact long-running tooltip", async () => {
    mockApi({
      ads: () =>
        json(
          list([
            item({
              duration: {
                days: 214,
                bucket: "Long-running",
                source: "meta_delivery_start",
                is_long_running_signal: true,
              },
            }),
          ]),
        ),
    });
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    expect(screen.getByText(/214 days/)).toBeDefined();
    expect(screen.getByText("Long-running")).toBeDefined();
    expect(screen.getByText("from Meta-reported delivery start")).toBeDefined();

    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.textContent).toBe("duration is a public proxy, not performance");
    expect(tooltip.textContent).toBe(LONG_RUNNING_TOOLTIP);
  });

  it("renders a real zero-day duration as 0, not as an em dash", async () => {
    // Present in the real seeded data: mock-ad-000203 is 0 days, bucket New, first_seen_at.
    mockApi({
      ads: () =>
        json(
          list([
            item({
              duration: { days: 0, bucket: "New", source: "first_seen_at", is_long_running_signal: false },
            }),
          ]),
        ),
    });
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    expect(screen.getByText(/^0 days$/)).toBeDefined();
    expect(screen.getByText("from First seen by us")).toBeDefined();
  });

  it("renders the data origin as a provenance badge", async () => {
    mockApi({ ads: () => json(list([item({ data_origin: "official_api" })])) });
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    const badge = document.querySelector("[data-origin='official_api']");
    expect(badge?.textContent).toBe("Official API");
  });

  it("renders a missing duration as an em dash", async () => {
    mockApi({ ads: () => json(list([item({ duration: null })])) });
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    // Scoped to the duration cell. The row carries several em dashes by design -- the
    // copy columns have no data to show -- so a bare getByTestId would pass for the
    // wrong reason.
    const durationCell = screen
      .getByTestId("ad-row")
      .querySelectorAll("[role='cell']")[4]!;
    expect(durationCell.textContent).toContain("Duration");
    expect(durationCell.querySelector("[data-testid='null-value']")?.textContent).toBe("—");
  });
});

/* ============================================================
 * What must not be on this screen
 * ============================================================ */

describe("what the grid must never show", () => {
  it("renders no performance metric label, value, or placeholder", async () => {
    mockApi({
      ads: () =>
        json(
          list([
            item({
              contexts: [
                context(),
                context({
                  facebook_page_id: PAGE_2,
                  country: "GB",
                  current_status: "not_seen_since",
                  provider_active: false,
                  not_seen_since_at: "2026-09-01T12:00:00Z",
                }),
              ],
              duration: {
                days: 214,
                bucket: "Long-running",
                source: "meta_delivery_start",
                is_long_running_signal: true,
              },
              platforms: [],
            }),
          ]),
        ),
    });

    const { container } = render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    // Scan **leaf** nodes, joined by a separator, rather than `container.textContent`.
    //
    // `textContent` concatenates adjacent elements with no separator, so two column
    // headers read as one token: `...Last seenProvenanceROAS`. A `\broas\b` boundary
    // then fails to match, and the whole guard silently passes on exactly the content
    // it exists to catch. Joining leaf texts with " | " restores real boundaries. This
    // was found by mutation, not by reading the test.
    const text = [...container.querySelectorAll("*")]
      .filter((el) => el.children.length === 0)
      .map((el) => (el.textContent ?? "").trim())
      .filter((t) => t !== "")
      .join(" | ")
      .toLowerCase();

    // Word boundaries, not `toContain`: a substring test flags "reach" inside
    // "reaching". A banned-word check that cries wolf gets deleted, which is worse than
    // not having one.
    const banned =
      /\b(spend|spends|spending|budget|budgets|roas|cpa|cpc|cpm|lead|leads|sales|revenue|click|clicks|reach|reaches|impression|impressions|conversion|conversions|winner|loser|best|top performer|top performers)\b/;
    const found = text.match(banned);
    expect(found, `banned term rendered: ${found?.[0] ?? ""} in ... ${text}`).toBeNull();

    // Not even as a "coming soon".
    expect(text).not.toContain("coming soon");
    expect(text).not.toContain("not available yet");
  });

  it("shows the copy the list response carries", async () => {
    // Step 6A closed the gap this grid used to have. The copy arrives in `/ads` itself,
    // so the row can say what the ad says without a second request.
    mockApi({ ads: () => json(list([item()])) });
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    const copy = screen.getByTestId("copy-preview");
    expect(copy.textContent).toContain("A kettle that actually whistles.");
    expect(copy.textContent).toContain("Still whistling after 5,000 boils");
    expect(copy.textContent).toContain("CTA: SHOP_NOW");
  });

  it("truncates long copy visually but keeps the full text in the DOM", async () => {
    // `line-clamp`, not a JavaScript cut. Truncating the string would hand a screen
    // reader and a copy-paste a sentence with no ending.
    const long = "word ".repeat(200).trim();
    mockApi({
      ads: () => json(list([item({ copy_fields: { ...item().copy_fields!, primary_text: long } })])),
    });
    const { container } = render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    const primary = screen.getByTestId("copy-preview").firstElementChild as HTMLElement;
    expect(primary.className).toContain("line-clamp-2");
    // Nothing removed from the text itself.
    expect(primary.textContent).toBe(long);
    expect(container.textContent).toContain(long.slice(-40));
  });

  it("renders null copy fields as an em dash, never as empty text", async () => {
    mockApi({
      ads: () =>
        json(
          list([
            item({
              copy_fields: {
                primary_text: null,
                headline: null,
                description: null,
                cta: null,
                destination_url: null,
              },
            }),
          ]),
        ),
    });
    const { container } = render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    const copy = screen.getByTestId("copy-preview");
    expect(copy.textContent).toContain("\u2014");
    expect(copy.textContent).toContain("provider reported no text");
    // Never N/A, never the word null, never a fabricated placeholder string.
    const text = (container.textContent ?? "").toLowerCase();
    expect(text).not.toContain("n/a");
    expect(text).not.toContain("unknown");
  });

  it("distinguishes never-observed from the provider reporting no text", async () => {
    // `copy_fields: null` means the ad has no snapshot. A copy object whose fields are
    // all null means the provider sent none. Collapsing the two would be a false claim.
    mockApi({ ads: () => json(list([item({ copy_fields: null })])) });
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    expect(screen.getByTestId("copy-absent").textContent).toBe("not observed yet");
    expect(screen.queryByTestId("copy-preview")).toBeNull();
  });

  it("renders provider copy as plain text, never as markup", async () => {
    // Ad copy is provider-supplied free text and goes through SafeText. A future edit
    // that reached for dangerouslySetInnerHTML turns this red.
    const hostile = '<script>globalThis.__pwned=1</script><img src=x onerror=alert(1)>';
    mockApi({
      ads: () =>
        json(list([item({ copy_fields: { ...item().copy_fields!, primary_text: hostile } })])),
    });
    const { container } = render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByTestId("copy-preview").textContent).toContain(hostile);
    expect((globalThis as Record<string, unknown>)["__pwned"]).toBeUndefined();
  });

  it("does not count anything as a ranking", async () => {
    // The count is an observation count. Phrasing it as "top N" would invite the
    // question this product cannot answer.
    mockApi({ ads: () => json(list([item(), item({ id: "ad-2" })], 2)) });
    render(<AdsLibrary />);
    await screen.findAllByTestId("ad-row");

    const count = screen.getByTestId("result-count").textContent?.toLowerCase() ?? "";
    expect(count).toContain("observed ads");
    expect(count).not.toMatch(/\b(top|best|winning|leading)\b/);
  });

  it("shows no AI availability indicator", async () => {
    // Requirement 16: AI surfaces on the detail screen, not here. An indicator on the
    // list would also tempt a click-through to an endpoint the grid must not call.
    mockApi({});
    const { container } = render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    expect(container.querySelector("[data-copy-hash]")).toBeNull();
    expect(container.textContent?.toLowerCase()).not.toContain("interpretation");
    expect(container.textContent?.toLowerCase()).not.toContain("analysis");
  });

  it("loads no image and fetches no media", async () => {
    mockApi({});
    const { container, fetchSpy } = (() => {
      const api = mockApi({});
      const rendered = render(<AdsLibrary />);
      return { container: rendered.container, fetchSpy: api.fetchSpy };
    })();
    await screen.findByTestId("ad-row");

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("video")).toBeNull();
    for (const call of fetchSpy.mock.calls) {
      expect(String(call[0])).not.toMatch(/\.(jpg|jpeg|png|gif|mp4|webp|avif)/i);
    }
  });
});

/* ============================================================
 * Responsive structure
 * ============================================================ */

describe("responsive structure", () => {
  it("does not require horizontal scrolling at any width", async () => {
    mockApi({});
    const { container } = render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    // jsdom has no layout engine, so this cannot measure overflow. What it can do is
    // catch the two ways a Tailwind layout usually becomes sideways-only: an
    // `overflow-x-auto` wrapper around the data, and a forced minimum width.
    const html = container.innerHTML;
    expect(html).not.toContain("overflow-x-auto");
    expect(html).not.toContain("overflow-x-scroll");
    expect(html).not.toMatch(/min-w-\[\d{3,}px\]/);
    // The row is a single column by default and only widens at the `lg` breakpoint,
    // which is what makes a phone render a stacked card rather than a squeezed table.
    const row = screen.getByTestId("ad-row");
    expect(row.className).toContain("grid-cols-1");
    expect(row.className).toContain("lg:grid-cols-");
  });

  it("keeps secondary columns on mobile but drops them on tablet", async () => {
    mockApi({});
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    const row = screen.getByTestId("ad-row");
    // Every secondary cell is visible at base and at lg, hidden between.
    const secondary = [...row.querySelectorAll("[role='cell']")].filter((c) =>
      c.className.includes("max-md:block"),
    );
    expect(secondary).toHaveLength(2);
    for (const cell of secondary) {
      expect(cell.className).toContain("md:hidden");
      expect(cell.className).toContain("lg:block");
    }
  });

  it("gives every cell a label for the stacked mobile layout", async () => {
    mockApi({});
    render(<AdsLibrary />);
    await screen.findByTestId("ad-row");

    const cells = [...screen.getByTestId("ad-row").querySelectorAll("[role='cell']")];
    expect(cells).toHaveLength(7);
    for (const cell of cells) {
      const label = cell.querySelector("span");
      expect(label?.textContent?.trim()).toBeTruthy();
      expect(label?.className).toContain("lg:hidden");
    }
  });
});
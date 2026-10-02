/**
 * Historical snapshots.
 *
 * ## Most of these tests are about what the history must NOT become
 *
 * A snapshot list is where four specific mistakes are easiest and least visible: sorting
 * an append-only history, showing the ad's *current* copy on an *older* row, labelling a
 * provider's historical `ad_status` as a current status, and implying that a null hash
 * means "nothing changed". None of those throws. So each has its own test.
 *
 * ## Every snapshot builds its own copy
 *
 * The fixtures deliberately differ from one row to the next, in copy, in platforms and in
 * hashes, so a test that accidentally reuses the latest ad copy on a historical row is
 * caught rather than passing because every row happened to look the same.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SnapshotHistory } from "./SnapshotHistory";
import { AdDetail } from "./AdDetail";
import type { CopyFieldsOut, SnapshotListOut, SnapshotOut } from "../../types/api";

const AD_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function copy(overrides: Partial<CopyFieldsOut> = {}): CopyFieldsOut {
  return {
    primary_text: "Most kettles go quiet in a year.",
    headline: "Still whistling after 5,000 boils",
    description: "Packaging claim, unchanged test method.",
    cta: "SHOP_NOW",
    destination_url: "https://aurora.example.invalid/kettle/box-copy",
    ...overrides,
  };
}

function snapshot(overrides: Partial<SnapshotOut> = {}): SnapshotOut {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    created_at: "2026-10-02T05:39:37.303283Z",
    collection_run_id: "44444444-4444-4444-8444-444444444444",
    content_hash: "149f3d02c4d3f402e74d7b068fb68a269c9dd9930361f13ab2501818c713274f",
    copy_hash: "b62dc7a3e20d0dc0661c89f14fb38797fb538876fbd2995cb56c0ba4e1a07830",
    creative_hash: "fa9f07566b57996b292c7c83fd86bea0cd3f9e85c75a4eb6c5939de373772b22",
    ad_status: "active",
    meta_delivery_start: "2026-01-05T09:00:00Z",
    copy_fields: copy(),
    media: [],
    platforms: ["facebook", "instagram"],
    analysis_copy_hash: null,
    ...overrides,
  };
}

/** Three observations, newest first, each visibly different from the last. */
const HISTORY: SnapshotOut[] = [
  snapshot({
    id: "33333333-3333-4333-8333-333333333333",
    created_at: "2026-10-02T05:39:37Z",
    content_hash: "aaaa000000000000000000000000000000000000000000000000000000000001",
    copy_hash: "bbbb000000000000000000000000000000000000000000000000000000000001",
    creative_hash: "cccc000000000000000000000000000000000000000000000000000000000001",
    copy_fields: copy({
      primary_text: "Same kettle, new claim. The cycle test is now on the box.",
      headline: "Still whistling after 5,000 boils",
      cta: "SHOP_NOW",
    }),
    platforms: ["facebook", "instagram", "messenger"],
    analysis_copy_hash: "dddd000000000000000000000000000000000000000000000000000000000001",
  }),
  snapshot({
    id: "33333333-3333-4333-8333-333333333334",
    created_at: "2026-09-01T12:00:00Z",
    content_hash: "aaaa000000000000000000000000000000000000000000000000000000000002",
    copy_hash: null,
    creative_hash: null,
    ad_status: null,
    meta_delivery_start: null,
    copy_fields: copy({
      primary_text: "Most kettles go quiet in a year.",
      headline: "A kettle that actually whistles",
      cta: "SHOP_NOW",
    }),
    platforms: ["facebook"],
    media: [
      {
        provider: "meta",
        provider_key: "mock-media-0001",
        source_url: "https://cdn.example.invalid/mock-media-0001.jpg",
        mime: "image/jpeg",
        width: 1080,
        height: 1080,
        duration_seconds: null,
        first_seen_at: "2026-09-01T12:00:00Z",
        last_seen_at: "2026-09-01T12:00:00Z",
        bytes_available: false,
      },
    ],
  }),
  snapshot({
    id: "33333333-3333-4333-8333-333333333335",
    created_at: "2026-08-01T09:00:00Z",
    content_hash: "aaaa000000000000000000000000000000000000000000000000000000000003",
    copy_hash: "bbbb000000000000000000000000000000000000000000000000000000000002",
    creative_hash: null,
    copy_fields: copy({ primary_text: "The original wording.", headline: null, cta: null }),
    platforms: [],
  }),
];

function list(items: SnapshotOut[], total = items.length, page = 1, pageSize = 25): SnapshotListOut {
  return { items, total, page, page_size: pageSize };
}

/**
 * Serves the record, the snapshots endpoint, and **nothing else**.
 *
 * Throwing on any other URL is deliberate: a panel that quietly started requesting the
 * list or a media file would otherwise pass a permissive mock.
 */
function mockApi(options: { snapshots?: () => Response; detail?: () => Response } = {}) {
  const requested: string[] = [];
  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

    if (url.includes("/snapshots")) return options.snapshots ? options.snapshots() : json(list(HISTORY, 3));
    if (url === `/api/ads/${AD_ID}`) {
      if (options.detail) return options.detail();
      return json({
        id: AD_ID,
        provider: "meta",
        meta_ad_id: "mock-ad-000101",
        data_origin: "public_ui",
        first_seen_at: "2026-08-01T09:00:00Z",
        last_seen_at: "2026-10-02T05:39:37Z",
        latest_snapshot: null,
        duration: null,
        contexts: [],
        copy_fields: copy({ primary_text: "THE LATEST COPY, which no historical row may show." }),
        analysis: null,
        media: [],
        platforms: ["facebook"],
      });
    }
    throw new Error(`unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", spy);
  return { requested, spy };
}

function snapshotRequests(requested: string[]): string[] {
  return requested.filter((u) => u.includes("/snapshots"));
}

function lastSnapshotQuery(requested: string[]): URLSearchParams {
  const urls = snapshotRequests(requested);
  expect(urls.length).toBeGreaterThan(0);
  return new URL(urls[urls.length - 1]!, "http://localhost").searchParams;
}

async function renderHistory(options: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi(options);
  const view = render(<SnapshotHistory adId={AD_ID} />);
  await screen.findByRole("heading", { name: "Historical snapshots" });
  await waitFor(() => expect(screen.queryByTestId("snapshots-loading")).toBeNull());
  return { ...api, ...view };
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/* ============================================================
 * Requests
 * ============================================================ */

describe("snapshot requests", () => {
  it("requests /ads/{id}/snapshots with page and page_size", async () => {
    const { requested } = await renderHistory();
    const params = lastSnapshotQuery(requested);
    expect(params.get("page")).toBe("1");
    expect(params.get("page_size")).toBe("25");
  });

  it("never requests the ads list, the directory, a media URL, or an analysis", async () => {
    const { requested } = await renderHistory();
    for (const url of requested) {
      expect(url.startsWith(`/api/ads/${AD_ID}`)).toBe(true);
      expect(url).not.toContain("/competitors");
      expect(url).not.toContain("analysis");
      expect(url).not.toMatch(/example\.invalid|\.(jpg|jpeg|png|gif|mp4|webp)/i);
      // Not the list endpoint: no bare `/api/ads?`.
      expect(url).not.toMatch(/\/api\/ads\?/);
    }
  });

  it("makes exactly one snapshot request for a given page", async () => {
    const { requested } = await renderHistory();
    await waitFor(() => expect(snapshotRequests(requested)).toHaveLength(1));
    // Settle, then confirm no second request crept in from a re-render.
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(snapshotRequests(requested)).toHaveLength(1);
  });

  it("on the detail route the record is fetched once and history separately", async () => {
    const { requested } = mockApi();
    render(<AdDetail adId={AD_ID} />);
    await screen.findByRole("heading", { name: "mock-ad-000101" });
    await waitFor(() => expect(snapshotRequests(requested)).toHaveLength(1));

    const recordRequests = requested.filter((u) => u === `/api/ads/${AD_ID}`);
    expect(recordRequests).toHaveLength(1);
  });
});

/* ============================================================
 * Order, copy, platforms
 * ============================================================ */

describe("the history as stored", () => {
  it("renders the API's order and does not re-sort it", async () => {
    // Deliberately not newest-first in the fixture, so a client sort would be visible.
    const shuffled = [HISTORY[2]!, HISTORY[0]!, HISTORY[1]!];
    const { container } = await renderHistory({
      snapshots: () =>
        new Response(JSON.stringify(list(shuffled, 3)), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    });

    const dates = [...container.querySelectorAll("[data-testid='snapshot-row'] h4")].map(
      (h) => h.textContent,
    );
    expect(dates).toEqual([
      "2026-08-01 09:00 UTC",
      "2026-10-02 05:39 UTC",
      "2026-09-01 12:00 UTC",
    ]);
  });

  it("shows each snapshot's own copy, never the ad's current copy", async () => {
    const { container } = await renderHistory();
    const text = container.textContent ?? "";
    expect(text).toContain("Same kettle, new claim. The cycle test is now on the box.");
    expect(text).toContain("A kettle that actually whistles");
    expect(text).toContain("The original wording.");
    // The detail endpoint's copy belongs to the detail screen, never to a history row.
    expect(text).not.toContain("THE LATEST COPY");
  });

  it("uses each snapshot's own platforms, in the order the provider gave them", async () => {
    const { container } = await renderHistory();
    const rows = [...container.querySelectorAll("[data-testid='snapshot-row']")];
    const lists = rows.map((row) =>
      [...row.querySelectorAll("[data-testid='platform-list']")].map(
        (list) => [...list.children].map((c) => c.textContent),
      ),
    );

    expect(lists[0]).toEqual([["facebook", "instagram", "messenger"]]);
    expect(lists[1]).toEqual([["facebook"]]);
  });

  it("says none recorded for a snapshot with an empty platform list", async () => {
    await renderHistory();
    const empties = screen.getAllByTestId("no-platforms");
    expect(empties).toHaveLength(1);
    expect(empties[0]!.textContent).toBe("none recorded");
    // Not the ad's current list, which is `facebook` for every other row.
    expect(empties[0]!.closest("[data-testid='snapshot-row']")?.textContent).not.toContain("instagram");
  });

  it("renders null copy fields as an em dash", async () => {
    await renderHistory();
    const last = screen.getAllByTestId("snapshot-row")[2]!;
    const dashes = last.querySelectorAll("[data-testid='null-value']");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
    for (const dash of dashes) expect(dash.textContent).toBe("—");
  });

  it("keeps long copy readable", async () => {
    const long = "sentence ".repeat(400).trim();
    await renderHistory({
      snapshots: () =>
        new Response(JSON.stringify(list([snapshot({ copy_fields: copy({ primary_text: long }) })], 1)), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    });
    expect(screen.getByText(long)).toBeDefined();
  });

  it("renders provider copy as plain text, never markup", async () => {
    const hostile = "<script>globalThis.__pwned=1</script>";
    const { container } = await renderHistory({
      snapshots: () =>
        new Response(JSON.stringify(list([snapshot({ copy_fields: copy({ primary_text: hostile }) })], 1)), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    });
    expect(container.querySelector("script")).toBeNull();
    expect((globalThis as Record<string, unknown>)["__pwned"]).toBeUndefined();
  });
});

/* ============================================================
 * The "changed" label
 * ============================================================ */

describe("the change label", () => {
  it("says copy changed only where a comparison was actually performed", async () => {
    const { container } = await renderHistory();
    const labels = [...container.querySelectorAll("[data-testid='snapshot-label']")].map(
      (n) => n.textContent,
    );
    // Rows 0 and 1 have an older snapshot after them to compare with; the last row has
    // none in this result, so it must not claim anything.
    expect(labels[0]).toBe("Copy changed since the previous observation");
    expect(labels[1]).toBe("Copy changed since the previous observation");
    expect(labels[2]).toBe("Observed snapshot");
  });

  it("says nothing changed when the stored copy is identical", async () => {
    const identical = snapshot({ id: "44444444-4444-4444-8444-444444444441" });
    const { container } = await renderHistory({
      snapshots: () =>
        new Response(
          JSON.stringify(
            // Two observations whose stored copy fields are identical. Nothing is hashed;
            // this is a plain comparison of the fields as returned.
            list([snapshot({ id: "44444444-4444-4444-8444-444444444442" }), identical], 2),
          ),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
    });
    const labels = [...container.querySelectorAll("[data-testid='snapshot-label']")].map(
      (n) => n.textContent,
    );
    expect(labels[0]).toBe("Observed snapshot");
  });
});

/* ============================================================
 * Hashes, status, delivery
 * ============================================================ */

describe("hashes, status and delivery", () => {
  it("renders stored hashes as stored, and null ones as em dashes", async () => {
    const { container } = await renderHistory();

    // Compacted for display, with the full value available on hover.
    const contentHashes = [...container.querySelectorAll("[title]")]
      .map((n) => n.getAttribute("title"))
      .filter((t): t is string => t !== null && t.startsWith("aaaa"));
    expect(contentHashes[0]).toBe("aaaa000000000000000000000000000000000000000000000000000000000001");
    // The null ones are dashes. Asserted per element rather than as a substring, because
    // this product's own fixture prose contains the word "unchanged" in a description --
    // a document-wide ban would fail on content rather than on the claim under test.
    for (const node of container.querySelectorAll("dd, span")) {
      expect((node.textContent ?? "").trim().toLowerCase()).not.toMatch(
        /^(unchanged|identical|no change|same)$/,
      );
    }
    /*
     * Checked per field, not by counting. A `>= 3` on the number of dashes is satisfied by
     * a version that renders a null hash as sixty-four zeros instead of a dash, because
     * two of the five nulls in this row survive either way -- which mutation testing
     * demonstrated rather than argued.
     */
    const row = screen.getAllByTestId("snapshot-row")[1]!;
    for (const label of ["Copy hash", "Creative hash", "Analysis copy hash"]) {
      const cell = hashCell(row, label);
      expect(cell, label).not.toBeNull();
      expect(cell!.querySelector("[data-testid='null-value']"), label).not.toBeNull();
      expect(cell!.textContent, label).not.toMatch(/\b[0-9a-f]{16,}\b/);
    }
  });

  it("labels a snapshot ad_status as recorded at that observation, never as a status", async () => {
    const { container } = await renderHistory();
    const text = container.textContent ?? "";
    expect(text).toContain("Provider reported at this observation");
    // Never the S2.3 vocabulary on a historical row, and never "stopped".
    for (const banned of ["current status", "global status", "stopped", "presumed inactive", "not seen since"]) {
      expect(text.toLowerCase()).not.toContain(banned);
    }
    // The provider's own word is shown verbatim.
    expect(text).toContain("active");
  });

  it("shows meta_delivery_start when present and an em dash when not", async () => {
    const { container } = await renderHistory();
    expect(container.textContent).toContain("2026-01-05 09:00 UTC");
    const row = screen.getAllByTestId("snapshot-row")[1]!;
    expect(within(row).getAllByTestId("null-value").length).toBeGreaterThan(0);
  });

  it("shows analysis_copy_hash as a stored reference and requests no analysis", async () => {
    const { requested, container } = await renderHistory();
    const text = container.textContent ?? "";
    expect(text).toContain("Analysis copy hash");
    expect(container.innerHTML).toContain("dddd000000000000000000000000000000000000000000000000000000000001");
    expect(requested.some((u) => u.includes("analysis"))).toBe(false);
  });
});

/* ============================================================
 * Media
 * ============================================================ */

describe("snapshot media", () => {
  it("shows references only, and says the bytes are not acquired", async () => {
    await renderHistory();
    expect(screen.getAllByTestId("snapshot-media")).toHaveLength(1);
    expect(screen.getByTestId("bytes-not-acquired").textContent).toBe("bytes not acquired");
  });

  it("never turns source_url into an image and never requests it", async () => {
    const { container, requested } = await renderHistory();
    for (const tag of ["img", "video", "iframe", "source", "object", "embed"]) {
      expect(container.querySelector(tag)).toBeNull();
    }
    expect(container.innerHTML).not.toContain("background-image");
    expect(requested.some((u) => u.includes("cdn.example.invalid"))).toBe(false);
  });
});

/* ============================================================
 * Pagination
 * ============================================================ */

describe("snapshot pagination", () => {
  const many = (count: number): SnapshotListOut =>
    list(
      Array.from({ length: count }, (_, i) => snapshot({ id: `33333333-3333-4333-8333-3333333333${String(i).padStart(2, "0")}` })),
      100,
      1,
      25,
    );

  it("pages forward and back, and persists the page in the URL", async () => {
    const { requested } = await renderHistory({
      snapshots: () =>
        new Response(JSON.stringify(many(25)), { status: 200, headers: { "content-type": "application/json" } }),
    });

    fireClick("Next snapshots");
    await waitFor(() => expect(lastSnapshotQuery(requested).get("page")).toBe("2"));
    await waitFor(() => expect(window.location.search).toContain("snapshot_page=2"));

    fireClick("Previous snapshots");
    await waitFor(() => expect(lastSnapshotQuery(requested).get("page")).toBe("1"));
    // Page 1 is the default, so it leaves the URL clean.
    await waitFor(() => expect(window.location.search).not.toContain("snapshot_page"));
  });

  it("changes page size and returns to the first page", async () => {
    const { requested } = await renderHistory({
      snapshots: () =>
        new Response(JSON.stringify(many(25)), { status: 200, headers: { "content-type": "application/json" } }),
    });

    fireClick("Next snapshots");
    await waitFor(() => expect(lastSnapshotQuery(requested).get("page")).toBe("2"));

    const select = screen.getByLabelText("Per page") as HTMLSelectElement;
    select.value = "50";
    select.dispatchEvent(new Event("change", { bubbles: true }));

    await waitFor(() => {
      const params = lastSnapshotQuery(requested);
      expect(params.get("page_size")).toBe("50");
      expect(params.get("page")).toBe("1");
    });
  });

  it("restores the page from the URL on load", async () => {
    window.history.replaceState(null, "", "/?snapshot_page=3&snapshot_page_size=50");
    const { requested } = await renderHistory();
    const params = lastSnapshotQuery(requested);
    expect(params.get("page")).toBe("3");
    expect(params.get("page_size")).toBe("50");
  });

  it("disables Previous on the first page and Next on the last", async () => {
    await renderHistory();
    expect((screen.getByRole("button", { name: "Previous snapshots" }) as HTMLButtonElement).disabled).toBe(true);
    // Total 3 at 25 per page is a single page, so Next is disabled too.
    expect((screen.getByRole("button", { name: "Next snapshots" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("leaves the library's own URL parameters untouched", async () => {
    // The snapshot keys are prefixed so a detail link and a library link can coexist.
    window.history.replaceState(null, "", "/ads/abc?snapshot_page=2");
    await renderHistory();
    expect(window.location.pathname).toBe(`/ads/abc`);
    expect(window.location.search).toContain("snapshot_page=2");
    expect(window.location.search).not.toContain("q=");
    expect(window.location.search).not.toContain("country=");
  });
});

/* ============================================================
 * States and what must never appear
 * ============================================================ */

describe("states and prohibitions", () => {
  it("shows an empty state when no snapshots are returned", async () => {
    await renderHistory({
      snapshots: () =>
        new Response(JSON.stringify(list([], 0)), { status: 200, headers: { "content-type": "application/json" } }),
    });
    expect(screen.getByTestId("snapshots-empty")).toBeDefined();
    expect(screen.queryByTestId("snapshot-row")).toBeNull();
  });

  it("shows a calm skeleton and no fake observations while loading", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        await gate;
        return new Response(JSON.stringify(list([HISTORY[0]!])), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    render(<SnapshotHistory adId={AD_ID} />);
    expect(screen.getByTestId("snapshots-loading")).toBeDefined();
    expect(screen.queryByTestId("snapshot-row")).toBeNull();
    release?.();
    await waitFor(() => expect(screen.getByTestId("snapshot-row")).toBeDefined());
  });

  it("shows a safe error state without a trace", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    await renderHistory({
      snapshots: () =>
        new Response(JSON.stringify({ detail: "Traceback (most recent call last): SECRET" }), {
          status: 500,
          headers: { "content-type": "application/json" },
        }),
    });
    const error = screen.getByTestId("snapshot-error");
    expect(error.textContent).toContain("could not complete the request");
    expect(error.textContent).not.toContain("Traceback");
    expect(error.textContent).not.toContain("SECRET");
  });

  it("renders no performance metric and no longevity verdict", async () => {
    const { container } = await renderHistory();
    const leaf = [...container.querySelectorAll("*")]
      .filter((el) => el.children.length === 0)
      .map((el) => (el.textContent ?? "").trim())
      .filter(Boolean)
      .join(" | ")
      .toLowerCase();

    expect(leaf).not.toMatch(
      /\b(spend|spends|budget|budgets|roas|cpa|cpc|cpm|lead|leads|sales|revenue|click|clicks|reach|reaches|impression|impressions|conversion|conversions|winner|loser|best|top performer|improved|improvement)\b/,
    );
    expect(leaf).not.toContain("coming soon");
  });

  it("keeps the history usable on a small screen", async () => {
    const { container } = await renderHistory();
    expect(container.innerHTML).not.toContain("overflow-x-auto");
    expect(container.innerHTML).not.toMatch(/min-w-\[\d{3,}px\]/);
    // Copy wraps rather than forcing a scroll.
    expect(container.innerHTML).toContain("break-words");
  });

  it("exposes the pagination as a labelled landmark with real buttons", async () => {
    await renderHistory();
    const nav = screen.getByRole("navigation", { name: "Snapshot pagination" });
    expect(within(nav).getByRole("button", { name: "Previous snapshots" })).toBeDefined();
    expect(within(nav).getByRole("button", { name: "Next snapshots" })).toBeDefined();
    expect(within(nav).getByText(/Page/)).toBeDefined();
  });
});

/** The value cell (`dd`) belonging to a `dt` with this label, within one row. */
function hashCell(row: Element, label: string): HTMLElement | null {
  const term = [...row.querySelectorAll("dt")].find((dt) => dt.textContent?.trim() === label);
  return (term?.parentElement?.querySelector("dd") as HTMLElement | null) ?? null;
}

function fireClick(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
}
/**
 * The Ad Detail screen.
 *
 * ## These tests are mostly about what is *not* requested
 *
 * The detail route is allowed exactly one call. Every test here records the URL of each
 * request, because the failures that matter on this screen are all invisible in the DOM:
 * a detail screen that quietly also pulls the list, or the directory, or a media URL, still
 * looks perfect.
 *
 * ## `AdDetailOut` has no Page name, and that is the point of two tests
 *
 * The screen must not fetch `/competitors` to invent one. So the Page is identified by its
 * id, and no test anywhere expects a brand name on this screen.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdDetail } from "./AdDetail";
import { App } from "../../App";
import type { AdDetailOut, ContextOut } from "../../types/api";

const AD_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function context(overrides: Partial<ContextOut> = {}): ContextOut {
  return {
    facebook_page_id: "11111111-1111-4111-8111-111111111111",
    country: "IN",
    current_status: "seen",
    provider_active: true,
    not_seen_since_at: null,
    last_status_run_id: null,
    ...overrides,
  };
}

function detail(overrides: Partial<AdDetailOut> = {}): AdDetailOut {
  return {
    id: AD_ID,
    provider: "meta",
    meta_ad_id: "mock-ad-000101",
    data_origin: "public_ui",
    first_seen_at: "2026-08-22T14:30:00Z",
    last_seen_at: "2026-10-02T05:39:37Z",
    latest_snapshot: {
      id: "22222222-2222-4222-8222-222222222222",
      created_at: "2026-10-02T05:39:37.303283Z",
      content_hash: "149f3d02c4d3f402e74d7b068fb68a269c9dd9930361f13ab2501818c713274f",
      copy_hash: "b62dc7a3e20d0dc0661c89f14fb38797fb538876fbd2995cb56c0ba4e1a07830",
      creative_hash: "fa9f07566b57996b292c7c83fd86bea0cd3f9e85c75a4eb6c5939de373772b22",
      ad_status: "active",
      meta_delivery_start: "2026-01-05T09:00:00Z",
    },
    duration: { days: 214, bucket: "Long-running", source: "meta_delivery_start", is_long_running_signal: true },
    contexts: [context()],
    copy_fields: {
      primary_text: "Most kettles go quiet in a year.",
      headline: "Still whistling after 5,000 boils",
      description: "Packaging claim, unchanged test method.",
      cta: "SHOP_NOW",
      destination_url: "https://aurora.example.invalid/kettle/box-copy",
    },
    analysis: null,
    media: [],
    platforms: ["facebook"],
    ...overrides,
  };
}

/**
 * Serves only `/ads/{id}` and **throws on anything else**.
 *
 * Failing loudly is the point: a screen that quietly started requesting the list would
 * otherwise pass a mock that answers everything.
 */
function mockApi(options: { ad?: AdDetailOut; status?: number } = {}) {
  const requested: string[] = [];
  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);

    if (/^\/api\/ads\/[0-9a-f-]+$/.test(url)) {
      const status = options.status ?? 200;
      if (status >= 400) {
        return new Response(JSON.stringify({ detail: "Traceback (most recent call last): secret" }), {
          status,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(JSON.stringify(options.ad ?? detail()), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    throw new Error(`unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", spy);
  return { requested, spy };
}

/**
 * Renders the detail screen and returns both the recorded requests and the render result.
 *
 * Both are returned because most of these tests assert on `container` *and* on what was
 * requested -- the point of the screen is that it shows everything and fetches almost
 * nothing.
 */
async function renderDetail(options: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi(options);
  const view = render(<AdDetail adId={AD_ID} />);
  await screen.findByRole("heading", { name: "mock-ad-000101" });
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

describe("requests", () => {
  it("loads only GET /ads/{id}", async () => {
    const { requested } = await renderDetail();
    expect(requested).toEqual([`/api/ads/${AD_ID}`]);
  });

  it("never requests the list, the directory, or anything external", async () => {
    const { requested } = await renderDetail();
    for (const url of requested) {
      expect(url).toMatch(/^\/api\/ads\/[0-9a-f-]{36}$/);
      // No list, no directory, no media, nothing off-origin.
      expect(url).not.toContain("/ads?");
      expect(url).not.toContain("/competitors");
      expect(url).not.toMatch(/https?:|\.(jpg|jpeg|png|gif|mp4|webp)/i);
    }
  });

  it("does not fetch the destination URL, and does not embed it as media", async () => {
    const { requested, spy } = await renderDetail();
    const link = screen.getByRole("link", { name: /aurora\.example\.invalid/ });
    expect(link.getAttribute("href")).toBe("https://aurora.example.invalid/kettle/box-copy");
    // A real destination a person may open, and inert until they do.
    expect(link.getAttribute("rel")).toContain("noreferrer");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(requested.some((u) => u.includes("example.invalid"))).toBe(false);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("triggers no AI generation -- it only reads what is stored", async () => {
    const { requested } = await renderDetail();
    expect(requested.filter((u) => !u.startsWith(`/api/ads/${AD_ID}`))).toHaveLength(0);
  });
});

/* ============================================================
 * Copy
 * ============================================================ */

describe("ad copy", () => {
  it("renders every copy field", async () => {
    await renderDetail();
    const body = document.body.textContent ?? "";
    expect(body).toContain("Most kettles go quiet in a year.");
    expect(body).toContain("Still whistling after 5,000 boils");
    expect(body).toContain("Packaging claim, unchanged test method.");
    expect(body).toContain("SHOP_NOW");
    expect(body).toContain("https://aurora.example.invalid/kettle/box-copy");
  });

  it("renders null copy fields as an em dash, never 0 or N/A", async () => {
    const { container } = await renderDetail({
      ad: detail({
        copy_fields: { primary_text: null, headline: null, description: null, cta: null, destination_url: null },
      }),
    });

    const dashes = container.querySelectorAll("[data-testid='null-value']");
    expect(dashes.length).toBeGreaterThanOrEqual(5);
    for (const dash of dashes) expect(dash.textContent).toBe("—");

    const text = (container.textContent ?? "").toLowerCase();
    expect(text).not.toContain("n/a");
    expect(text).not.toContain("unknown");
  });

  it("says so plainly when the record carries no copy at all", async () => {
    await renderDetail({ ad: detail({ copy_fields: null }) });
    expect(screen.getByText(/carries no copy/)).toBeDefined();
  });

  it("keeps long copy readable rather than truncating it", async () => {
    const long = "word ".repeat(300).trim();
    await renderDetail({ ad: detail({ copy_fields: { ...detail().copy_fields!, primary_text: long } }) });
    // The full string is in the document; a detail screen that cuts a sentence off is not
    // a detail screen.
    expect(screen.getByText(long)).toBeDefined();
  });

  it("renders provider copy as plain text, never markup", async () => {
    const hostile = '<script>globalThis.__pwned=1</script><img src=x onerror=alert(1)>';
    const { container } = await renderDetail({
      ad: detail({ copy_fields: { ...detail().copy_fields!, primary_text: hostile } }),
    });
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect((globalThis as Record<string, unknown>)["__pwned"]).toBeUndefined();
  });
});

/* ============================================================
 * Contexts, platforms, duration
 * ============================================================ */

describe("contexts, platforms and duration", () => {
  it("keeps several contexts separate, with no ad-level status", async () => {
    await renderDetail({
      ad: detail({
        contexts: [
          context({ country: "IN", current_status: "seen" }),
          context({ country: "GB", current_status: "presumed_inactive", provider_active: false }),
        ],
      }),
    });

    expect(screen.getAllByTestId("detail-context")).toHaveLength(2);
    expect(screen.getByText("IN")).toBeDefined();
    expect(screen.getByText("GB")).toBeDefined();
    expect(screen.getByText("Presumed inactive")).toBeDefined();

    const text = document.body.textContent ?? "";
    expect(text).not.toContain("stopped");
    // No single merged status anywhere.
    expect(text).not.toContain("Mixed");
  });

  it("keeps presumed_inactive worded as a presumption", async () => {
    await renderDetail({ ad: detail({ contexts: [context({ current_status: "presumed_inactive" })] }) });
    expect(screen.getByText("Presumed inactive")).toBeDefined();
    expect(screen.getByTitle(/presumption, not a verdict/)).toBeDefined();
  });

  it("renders provider_active null as an em dash, not as false", async () => {
    await renderDetail({ ad: detail({ contexts: [context({ provider_active: null })] }) });
    const node = screen.getByTestId("provider-active");
    expect(node.textContent).toContain("—");
    expect(node.textContent).not.toContain("not reported active");
  });

  it("shows the last-seen timestamp for a context that has one", async () => {
    await renderDetail({
      ad: detail({ contexts: [context({ current_status: "not_seen_since", not_seen_since_at: "2026-09-01T12:00:00Z" })] }),
    });
    expect(screen.getAllByText("2026-09-01 12:00 UTC").length).toBeGreaterThan(0);
  });

  it("preserves the provider's platform order and does not infer", async () => {
    await renderDetail({ ad: detail({ platforms: ["instagram", "facebook", "audience_network"] }) });
    const list = screen.getByTestId("platform-list");
    expect([...list.children].map((c) => c.textContent)).toEqual([
      "instagram",
      "facebook",
      "audience_network",
    ]);
  });

  it("says none recorded for an empty platform list", async () => {
    await renderDetail({ ad: detail({ platforms: [] }) });
    expect(screen.getByTestId("no-platforms").textContent).toBe("none recorded");
    const cell = screen.getByTestId("no-platforms").closest("dd");
    expect(cell?.textContent).not.toContain("facebook");
  });

  it("shows days, bucket, source and the exact long-running tooltip", async () => {
    await renderDetail();
    expect(screen.getByText(/214 days/)).toBeDefined();
    expect(screen.getByText("Long-running")).toBeDefined();
    expect(screen.getByText("from Meta-reported delivery start")).toBeDefined();
    expect(screen.getByRole("tooltip").textContent).toBe("duration is a public proxy, not performance");
  });

  it("renders a real zero-day duration as 0", async () => {
    await renderDetail({
      ad: detail({ duration: { days: 0, bucket: "New", source: "first_seen_at", is_long_running_signal: false } }),
    });
    expect(screen.getByText(/^0 days$/)).toBeDefined();
    expect(screen.getByText("from First seen by us")).toBeDefined();
  });
});

/* ============================================================
 * AI interpretation
 * ============================================================ */

describe("copy interpretation", () => {
  it("says not analysed and renders no empty fields when there is none", async () => {
    await renderDetail({ ad: detail({ analysis: null }) });
    expect(screen.getByTestId("analysis-absent").textContent).toBe("not analysed");
    // Fourteen null fields would read as "we analysed it and found nothing".
    expect(screen.queryByTestId("interpretation-table")).toBeNull();
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("Why it may work");
  });

  it("renders an analysis with its badge, provenance and fields", async () => {
    await renderDetail({
      ad: detail({
        analysis: {
          evidence_class: "AI_INTERPRETATION",
          copy_hash: "b62dc7a3e20d0dc0661c89f14fb38797fb538876fbd2995cb56c0ba4e1a07830",
          analysis_version: "mock-v1",
          prompt_version: "s3.1-analysis-v1",
          provider: "mock",
          model: "some-model",
          language: "en",
          confidence: "high",
          interpretation: { hook: "Opens on a failure the reader has already had.", urgency: null },
          source_snapshot_id: "22222222-2222-4222-8222-222222222222",
          created_at: "2026-10-02T06:00:00Z",
        },
      }),
    });

    const badge = document.querySelector("[data-evidence-class='AI_INTERPRETATION']");
    expect(badge?.textContent).toBe("AI interpretation");
    // The model output is fenced, and says what it is.
    expect(screen.getByText(/not something the provider stated/)).toBeDefined();
    expect(screen.getByText("some-model")).toBeDefined();
    expect(screen.getByText("mock-v1")).toBeDefined();
    expect(screen.getByText("s3.1-analysis-v1")).toBeDefined();
    expect(screen.getByText("Opens on a failure the reader has already had.")).toBeDefined();
    // Provenance back to the copy and the observation it came from.
    const provenance = document.querySelector("[data-copy-hash]");
    expect(provenance?.getAttribute("data-source-snapshot-id")).toBe("22222222-2222-4222-8222-222222222222");
    // And no invented route.
    expect(screen.queryByRole("link", { name: /snapshot/ })).toBeNull();
  });

  it("tolerates value types it was not written for", async () => {
    // `interpretation` is Record<string, unknown>. A number, an object, an array and a
    // boolean must all render rather than crash or become "[object Object]".
    await renderDetail({
      ad: detail({
        analysis: {
          evidence_class: "AI_INTERPRETATION",
          copy_hash: "b62dc7a3e20d0dc0661c89f14fb38797fb538876fbd2995cb56c0ba4e1a07830",
          analysis_version: "future-v9",
          prompt_version: "s3.1-analysis-v1",
          provider: "mock",
          model: null,
          language: null,
          confidence: null,
          interpretation: {
            hook: "A string.",
            hook_score: 0.82,
            evidence: { claim: "5,000 cycles", method: "published log" },
            tags: ["specificity", "proof"],
            verified: true,
            future_field_added_later: "renders without crashing",
          },
          source_snapshot_id: "22222222-2222-4222-8222-222222222222",
          created_at: "2026-10-02T06:00:00Z",
        },
      }),
    });

    const table = screen.getByTestId("interpretation-table");
    const text = table.textContent ?? "";
    expect(text).toContain("0.82");
    expect(text).toContain("5,000 cycles");
    expect(text).toContain("specificity");
    expect(text).toContain("true");
    // An unknown key is still shown, not dropped.
    expect(text).toContain("Future field added later");
    // Never the stringification failure mode.
    expect(text).not.toContain("[object Object]");
  });

  it("renders null interpretation values as an em dash", async () => {
    await renderDetail({
      ad: detail({
        analysis: {
          evidence_class: "AI_INTERPRETATION",
          copy_hash: "b62dc7a3e20d0dc0661c89f14fb38797fb538876fbd2995cb56c0ba4e1a07830",
          analysis_version: "mock-v1",
          prompt_version: "s3.1-analysis-v1",
          provider: "mock",
          model: null,
          language: null,
          confidence: null,
          interpretation: { hook: null },
          source_snapshot_id: "22222222-2222-4222-8222-222222222222",
          created_at: "2026-10-02T06:00:00Z",
        },
      }),
    });
    const table = screen.getByTestId("interpretation-table");
    expect(table.querySelector("[data-testid='null-value']")?.textContent).toBe("—");
  });

  it("says an empty mapping is a reading of sparse copy", async () => {
    await renderDetail({
      ad: detail({
        analysis: {
          evidence_class: "AI_INTERPRETATION",
          copy_hash: "b62dc7a3e20d0dc0661c89f14fb38797fb538876fbd2995cb56c0ba4e1a07830",
          analysis_version: "mock-v1",
          prompt_version: "s3.1-analysis-v1",
          provider: "mock",
          model: null,
          language: null,
          confidence: null,
          interpretation: {},
          source_snapshot_id: "22222222-2222-4222-8222-222222222222",
          created_at: "2026-10-02T06:00:00Z",
        },
      }),
    });
    expect(screen.getByTestId("interpretation-empty").textContent).toContain("reading of sparse copy");
  });
});

/* ============================================================
 * Media
 * ============================================================ */

describe("media references", () => {
  const asset = {
    provider: "meta",
    provider_key: "mock-media-0001",
    source_url: "https://cdn.example.invalid/mock-media-0001.jpg",
    mime: "image/jpeg",
    width: 1080,
    height: 1080,
    duration_seconds: null,
    first_seen_at: "2026-10-02T05:39:37Z",
    last_seen_at: "2026-10-02T05:39:37Z",
    bytes_available: false,
  };

  it("shows the metadata and says the bytes are not acquired", async () => {
    await renderDetail({ ad: detail({ media: [asset] }) });
    expect(screen.getAllByTestId("detail-media")).toHaveLength(1);
    expect(screen.getByTestId("bytes-not-acquired").textContent).toBe("bytes not acquired");
    const text = screen.getByTestId("detail-media").textContent ?? "";
    expect(text).toContain("image/jpeg");
    expect(text).toContain("1080");
    expect(text).toContain("mock-media-0001");
  });

  it("never turns source_url into an image and never requests it", async () => {
    const { container, requested } = await renderDetail({ ad: detail({ media: [asset] }) });
    for (const tag of ["img", "video", "source", "iframe", "object", "embed"]) {
      expect(container.querySelector(tag)).toBeNull();
    }
    expect(container.innerHTML).not.toContain("background-image");
    expect(requested.some((u) => u.includes("cdn.example.invalid"))).toBe(false);
  });

  it("keeps a null duration as an em dash, not 0", async () => {
    const { container } = await renderDetail({ ad: detail({ media: [asset] }) });
    expect(container.querySelector("[data-testid='detail-media'] [data-testid='null-value']")).not.toBeNull();
    expect(screen.getByTestId("detail-media").textContent).not.toContain("0s");
  });

  it("displays duration_seconds as sent, without parsing it", async () => {
    // A string on the wire. Parsing it for computation would reintroduce the float error
    // the string exists to avoid.
    await renderDetail({ ad: detail({ media: [{ ...asset, duration_seconds: "19.90" }] }) });
    expect(screen.getByTestId("detail-media").textContent).toContain("19.90s");
  });

  it("says none recorded when there is no media at all", async () => {
    await renderDetail({ ad: detail({ media: [] }) });
    expect(screen.getByText("none recorded")).toBeDefined();
    expect(screen.queryByTestId("detail-media")).toBeNull();
  });
});

/* ============================================================
 * Routing and states
 * ============================================================ */

describe("routing and states", () => {
  it("shows a not-found state for an id the server does not have, with no trace", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { requested } = mockApi({ status: 404 });
    render(<AdDetail adId={AD_ID} />);

    expect(await screen.findByTestId("detail-not-found")).toBeDefined();
    expect(screen.getByText("Ad not found")).toBeDefined();
    const text = screen.getByTestId("detail-not-found").textContent ?? "";
    expect(text).not.toContain("Traceback");
    expect(requested).toEqual([`/api/ads/${AD_ID}`]);
  });

  it("shows a safe error state on a server failure", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi({ status: 500 });
    render(<AdDetail adId={AD_ID} />);

    expect(await screen.findByTestId("detail-error")).toBeDefined();
    const text = screen.getByTestId("detail-error").textContent ?? "";
    expect(text).toContain("Could not load this ad");
    expect(text).not.toContain("Traceback");
    expect(text).not.toContain("secret");
  });

  it("does not request anything for a malformed id", async () => {
    // The router resolves a non-UUID to `malformed`, so the typo costs no round trip and
    // no 422. `console.error` is silenced because this mock refuses every endpoint and
    // the refusal is exactly what is being asserted.
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { spy } = mockApi();
    window.history.replaceState(null, "", "/ads/not-a-uuid");
    render(<App />);

    expect(screen.getByTestId("detail-malformed")).toBeDefined();
    expect(screen.getByText("Ad not found")).toBeDefined();
    expect(spy).not.toHaveBeenCalled();
  });

  it("opens the detail route from the pathname", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi();
    window.history.replaceState(null, "", `/ads/${AD_ID}`);
    render(<App />);
    expect(await screen.findByRole("heading", { name: "mock-ad-000101" })).toBeDefined();
  });

  it("shows the library at the root path", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    mockApi();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Ad Library" })).toBeDefined();
  });

  it("offers a way back to the library", async () => {
    await renderDetail();
    expect(screen.getByRole("link", { name: /Back to Ad Library/ }).getAttribute("href")).toBe("/");
  });

  it("shows a calm skeleton and no fake ad content while loading", async () => {
    // Definite assignment: the executor runs synchronously, but TypeScript's
    // control-flow analysis cannot see that and narrows the variable to `null` for
    // ever, which makes the call below an error.
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        await gate;
        return new Response(JSON.stringify(detail()), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    render(<AdDetail adId={AD_ID} />);
    expect(screen.getByTestId("detail-loading")).toBeDefined();
    expect(screen.queryByText("mock-ad-000101")).toBeNull();
    release();
    await waitFor(() => expect(screen.getByRole("heading", { name: "mock-ad-000101" })).toBeDefined());
  });

  it("keeps the record usable on a small screen", async () => {
    const { container } = await renderDetail({
      ad: detail({ media: [{ provider: "meta", provider_key: "k", source_url: "https://x.invalid/a.jpg", mime: "image/jpeg", width: 1, height: 1, duration_seconds: null, first_seen_at: "2026-10-02T05:39:37Z", last_seen_at: "2026-10-02T05:39:37Z", bytes_available: false }] }),
    });
    expect(container.innerHTML).not.toContain("overflow-x-auto");
    expect(container.innerHTML).not.toMatch(/min-w-\[\d{3,}px\]/);
    // Long copy wraps rather than forcing a scroll.
    expect(container.innerHTML).toContain("break-words");
  });

  it("renders no performance metric anywhere on the screen", async () => {
    const { container } = await renderDetail({
      ad: detail({
        analysis: {
          evidence_class: "AI_INTERPRETATION",
          copy_hash: "b62dc7a3e20d0dc0661c89f14fb38797fb538876fbd2995cb56c0ba4e1a07830",
          analysis_version: "mock-v1",
          prompt_version: "s3.1-analysis-v1",
          provider: "mock",
          model: null,
          language: "en",
          confidence: "high",
          interpretation: { hook: "A reading.", why_it_may_work: "It may suit a reader who ..." },
          source_snapshot_id: "22222222-2222-4222-8222-222222222222",
          created_at: "2026-10-02T06:00:00Z",
        },
      }),
    });

    // Leaf-node text joined with a separator: `textContent` concatenates adjacent
    // elements, so two labels read as one token and word boundaries never match.
    const leaf = [...container.querySelectorAll("*")]
      .filter((el) => el.children.length === 0)
      .map((el) => (el.textContent ?? "").trim())
      .filter(Boolean)
      .join(" | ")
      .toLowerCase();

    expect(leaf).not.toMatch(
      /\b(spend|spends|budget|budgets|roas|cpa|cpc|cpm|lead|leads|sales|revenue|click|clicks|reach|reaches|impression|impressions|conversion|conversions|winner|loser|best|top performer)\b/,
    );
    // Not even as a teaser.
    expect(leaf).not.toContain("coming soon");
  });

  it("names no Page brand, because the response carries none", async () => {
    await renderDetail();
    // The id appears twice by design: once in Identity, once beside each context's
    // status. Both are identifiers, and neither is a name.
    const ids = screen.getAllByText("11111111-1111-4111-8111-111111111111");
    expect(ids.length).toBeGreaterThanOrEqual(1);
    expect(document.body.textContent).not.toContain("Aurora");
  });
});
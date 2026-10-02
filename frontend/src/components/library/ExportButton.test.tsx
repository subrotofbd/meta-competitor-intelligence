/**
 * CSV export.
 *
 * ## The parity test is the point of this file
 *
 * "Export what I filtered" is the product's claim, and the failure mode is invisible: an
 * export that quietly drops one filter still produces a plausible-looking file of the
 * wrong rows. So the central test here compares the *serialised parameters* of the list
 * request against those of the export URL, key by key, rather than checking that the
 * export "has the filters".
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExportButton, filenameFromDisposition } from "./ExportButton";
import { adsCsvUrl } from "../../api/library";
import {
  DEFAULT_QUERY,
  adsQueryToFilterParams,
  adsQueryToParams,
  type AdsQuery,
} from "./adsQuery";

/** Every filter set at once, with deliberately distinct values. */
const EVERY_FILTER: AdsQuery = {
  ...DEFAULT_QUERY,
  q: "kettle",
  provider: "meta",
  competitorId: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  facebookPageId: "11111111-1111-4111-8111-111111111111",
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
  page: 4,
  pageSize: 50,
};

/** The twelve the export endpoint accepts. */
const FILTER_KEYS = [
  "q",
  "provider",
  "competitor_id",
  "facebook_page_id",
  "country",
  "current_status",
  "provider_active",
  "data_origin",
  "first_seen_from",
  "first_seen_to",
  "last_seen_from",
  "last_seen_to",
] as const;

const NON_FILTER_KEYS = ["page", "page_size", "sort", "direction"] as const;

function csvResponses(requested: string[], options: { status?: number } = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);

    if (url.startsWith("/api/exports/ads.csv")) {
      const status = options.status ?? 200;
      return new Response(status === 200 ? "meta_ad_id,status\nmock-ad-1,active\n" : JSON.stringify({ detail: "Traceback: SECRET" }), {
        status,
        headers: {
          "content-type": status === 200 ? "text/csv; charset=utf-8" : "application/json",
          ...(status === 200 ? { "Content-Disposition": 'attachment; filename="ads.csv"' } : {}),
        },
      });
    }
    // Anything else means the export went looking for something it should not.
    throw new Error(`unexpected request: ${url}`);
  });
}

function csvUrlParams(requested: string[]): URLSearchParams {
  const urls = requested.filter((u) => u.startsWith("/api/exports/ads.csv"));
  expect(urls.length).toBeGreaterThan(0);
  return new URL(urls[urls.length - 1]!, "http://localhost").searchParams;
}

async function clickExport() {
  fireEvent.click(screen.getByRole("button", { name: /Export/ }));
}

beforeEach(() => {
  // jsdom has no object-URL implementation, and the button only needs one to exist.
  URL.createObjectURL = vi.fn(() => "blob:mock");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/* ============================================================
 * Filter parity -- the central assertion
 * ============================================================ */

describe("export parameters match the list parameters exactly", () => {
  it("sends all twelve filters the list sends, with identical values", () => {
    const list = adsQueryToParams(EVERY_FILTER);
    const exportParams = adsQueryToFilterParams(EVERY_FILTER);

    for (const key of FILTER_KEYS) {
      expect(exportParams.get(key), key).toBe(list.get(key));
      expect(exportParams.get(key), key).not.toBeNull();
    }
    expect([...exportParams.keys()].sort()).toEqual([...FILTER_KEYS].sort());
  });

  it("includes the four date bounds and q unchanged", () => {
    const params = adsQueryToFilterParams(EVERY_FILTER);
    expect(params.get("first_seen_from")).toBe("2026-01-01");
    expect(params.get("first_seen_to")).toBe("2026-02-01");
    expect(params.get("last_seen_from")).toBe("2026-03-01");
    expect(params.get("last_seen_to")).toBe("2026-04-01");
    expect(params.get("q")).toBe("kettle");
  });

  it("excludes page, page_size, sort and direction", () => {
    // The export is not a page of results. Sending them would be rejected or ignored, and
    // either way the URL stops describing what the file contains.
    const params = adsQueryToFilterParams(EVERY_FILTER);
    for (const key of NON_FILTER_KEYS) {
      expect(params.has(key), key).toBe(false);
    }
    // And the list really does carry them, so the exclusion is meaningful.
    expect(adsQueryToParams(EVERY_FILTER).get("page")).toBe("4");
    expect(adsQueryToParams(EVERY_FILTER).get("page_size")).toBe("50");
    expect(adsQueryToParams(EVERY_FILTER).get("sort")).toBe("meta_ad_id");
    expect(adsQueryToParams(EVERY_FILTER).get("direction")).toBe("asc");
  });

  it("builds an export URL from the same serializer as the request", () => {
    // The URL the button uses and the parameters under test come from the same function,
    // so this cannot drift from the assertions above.
    expect(adsCsvUrl(EVERY_FILTER)).toBe(
      `/api/exports/ads.csv?${adsQueryToFilterParams(EVERY_FILTER).toString()}`,
    );
  });
});

/* ============================================================
 * The button
 * ============================================================ */

describe("the export control", () => {
  it("exists, with an accessible name and a visible focus ring", async () => {
    const requested: string[] = [];
    vi.stubGlobal("fetch", csvResponses(requested));
    render(<ExportButton query={DEFAULT_QUERY} />);

    const button = screen.getByRole("button", { name: "Export CSV" });
    expect(button.className).toContain("focus-visible:outline");
    await clickExport();
    await waitFor(() => expect(requested).toHaveLength(1));
  });

  it("is reachable and operable by keyboard", async () => {
    const requested: string[] = [];
    vi.stubGlobal("fetch", csvResponses(requested));
    render(<ExportButton query={DEFAULT_QUERY} />);

    const button = screen.getByRole("button", { name: "Export CSV" });
    button.focus();
    expect(document.activeElement).toBe(button);
    // A native button, so Enter and Space are handled by the platform rather than by us.
    expect(button.tagName).toBe("BUTTON");
    expect(button.getAttribute("type")).toBe("button");
    // Activating it by keyboard performs the export, exactly as clicking does.
    fireEvent.click(button);
    await waitFor(() => expect(requested).toHaveLength(1));
  });

  it("sends a clean URL when nothing is filtered", async () => {
    const requested: string[] = [];
    vi.stubGlobal("fetch", csvResponses(requested));
    render(<ExportButton query={DEFAULT_QUERY} />);

    await clickExport();
    await waitFor(() => expect(requested).toHaveLength(1));

    // No null, no undefined, no empty uuid, no page=1, no sort.
    expect(requested[0]).toBe("/api/exports/ads.csv");
    expect(csvUrlParams(requested).toString()).toBe("");
  });

  it("carries every active filter into the request", async () => {
    const requested: string[] = [];
    vi.stubGlobal("fetch", csvResponses(requested));
    render(<ExportButton query={EVERY_FILTER} />);

    await clickExport();
    await waitFor(() => expect(requested).toHaveLength(1));

    const params = csvUrlParams(requested);
    for (const key of FILTER_KEYS) {
      expect(params.get(key), key).toBe(adsQueryToParams(EVERY_FILTER).get(key));
    }
    for (const key of NON_FILTER_KEYS) {
      expect(params.has(key), key).toBe(false);
    }
  });

  it("makes exactly one request, and nothing else", async () => {
    const requested: string[] = [];
    vi.stubGlobal("fetch", csvResponses(requested));
    render(<ExportButton query={EVERY_FILTER} />);

    await clickExport();
    await waitFor(() => expect(requested).toHaveLength(1));
    // No /ads, no /ads/{id}, no /competitors, nothing off-origin. The mock throws on
    // anything else, so a stray request would fail the test rather than pass quietly.
    expect(requested.every((u) => u.startsWith("/api/exports/ads.csv"))).toBe(true);
  });

  it("survives a rapid double click without exporting twice", async () => {
    const requested: string[] = [];
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    const spy = vi.fn(async (input: RequestInfo | URL) => {
      requested.push(String(input));
      await gate;
      return new Response("meta_ad_id\n", {
        status: 200,
        headers: { "content-type": "text/csv", "Content-Disposition": 'attachment; filename="ads.csv"' },
      });
    });
    vi.stubGlobal("fetch", spy);

    render(<ExportButton query={DEFAULT_QUERY} />);
    const button = screen.getByRole("button", { name: /Export/ });

    /*
     * All three clicks inside ONE `act`, so React batches them and does not re-render
     * between them -- the button is still enabled for all three.
     *
     * That is deliberate. `fireEvent` flushes on every call, so a naive test passes purely
     * because the second click lands on a disabled button, and it would pass with the
     * re-entrancy lock deleted entirely. Batching inside `act` reproduces the case the lock
     * actually exists for: two clicks in the same task, before the disabled attribute has
     * reached the DOM -- which is what a programmatic double invocation looks like.
     */
    act(() => {
      fireEvent.click(button);
      fireEvent.click(button);
      fireEvent.click(button);
    });

    release?.();
    await waitFor(() => expect(button.textContent).toBe("Export CSV"));
    expect(requested).toHaveLength(1);
  });

  it("shows an exporting state and returns to normal", async () => {
    const requested: string[] = [];
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        requested.push(String(input));
        await gate;
        return new Response("meta_ad_id\n", {
          status: 200,
          headers: { "content-type": "text/csv", "Content-Disposition": 'attachment; filename="ads.csv"' },
        });
      }),
    );

    render(<ExportButton query={DEFAULT_QUERY} />);
    await clickExport();

    await waitFor(() => expect(screen.getByRole("button", { name: /Exporting/ })).toBeDefined());
    const busy = screen.getByRole("button", { name: /Exporting/ }) as HTMLButtonElement;
    expect(busy.disabled).toBe(true);
    expect(busy.getAttribute("aria-busy")).toBe("true");

    release?.();
    await waitFor(() => expect(screen.getByRole("button", { name: "Export CSV" })).toBeDefined());
    expect((screen.getByRole("button", { name: "Export CSV" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("downloads the file on success without claiming it in words", async () => {
    const requested: string[] = [];
    vi.stubGlobal("fetch", csvResponses(requested));
    const clicked: HTMLAnchorElement[] = [];
    const originalClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function patched(this: HTMLAnchorElement) {
      clicked.push(this);
    };

    try {
      render(<ExportButton query={DEFAULT_QUERY} />);
      await clickExport();
      await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());

      expect(clicked).toHaveLength(1);
      expect(clicked[0]!.download).toBe("ads.csv");
      // A blob URL, and the anchor is cleaned up rather than left in the document.
      expect(clicked[0]!.getAttribute("href")).toBe("blob:mock");
      expect(document.querySelectorAll("a[download]")).toHaveLength(0);
      // No "success" toast: the browser already shows the download.
      expect(screen.getByTestId("export-status").textContent).toBe("");
    } finally {
      HTMLAnchorElement.prototype.click = originalClick;
    }
  });
});

/* ============================================================
 * Filenames
 * ============================================================ */

describe("filename handling", () => {
  it("uses the server's Content-Disposition filename", () => {
    expect(filenameFromDisposition('attachment; filename="ads.csv"')).toBe("ads.csv");
    expect(filenameFromDisposition("attachment; filename=ads.csv")).toBe("ads.csv");
  });

  it("falls back safely when the header is absent or unusable", () => {
    expect(filenameFromDisposition(null)).toBe("ads.csv");
    expect(filenameFromDisposition("attachment")).toBe("ads.csv");
    expect(filenameFromDisposition('attachment; filename=""')).toBe("ads.csv");
    expect(filenameFromDisposition('attachment; filename=".."')).toBe("ads.csv");
  });

  it("strips any path component out of the name", () => {
    // A download name is something a filesystem will act on, so a path in it is refused.
    expect(filenameFromDisposition('attachment; filename="../../etc/passwd"')).toBe("passwd");
    expect(filenameFromDisposition('attachment; filename="C:\\\\windows\\\\evil.csv"')).toBe("evil.csv");
  });

  it("tolerates a malformed percent-escape rather than failing the download", () => {
    expect(filenameFromDisposition('attachment; filename="%E0%A4%A.csv"')).toBe("ads.csv");
  });
});

/* ============================================================
 * Failures
 * ============================================================ */

describe("failures are reported honestly", () => {
  const cases: ReadonlyArray<[number, RegExp]> = [
    [400, /rejected/i],
    [413, /larger than the server allows|narrow the filters/i],
    [500, /could not complete/i],
  ];

  it.each(cases)("reports %i without a trace and downloads nothing", async (status, expected) => {
    const requested: string[] = [];
    vi.stubGlobal("fetch", csvResponses(requested, { status }));

    const clicked: string[] = [];
    const originalClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function patched() {
      clicked.push("clicked");
    };

    try {
      render(<ExportButton query={EVERY_FILTER} />);
      await clickExport();
      await waitFor(() => expect(screen.getByTestId("export-status").textContent).not.toBe(""));

      const text = screen.getByTestId("export-status").textContent ?? "";
      expect(text).toMatch(expected);
      // No raw server internals, and no claim that anything was exported.
      expect(text).not.toContain("Traceback");
      expect(text).not.toContain("SECRET");
      expect(text.toLowerCase()).not.toContain("success");
      // And no file was produced.
      expect(clicked).toHaveLength(0);
      expect(URL.createObjectURL).not.toHaveBeenCalled();
      // The button recovers, so a second attempt is possible.
      expect(screen.getByRole("button", { name: "Export CSV" })).toBeDefined();
    } finally {
      HTMLAnchorElement.prototype.click = originalClick;
    }
  });

  it("reports a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});

    render(<ExportButton query={DEFAULT_QUERY} />);
    await clickExport();
    await waitFor(() => expect(screen.getByTestId("export-status").textContent).not.toBe(""));

    const text = screen.getByTestId("export-status").textContent ?? "";
    expect(text).toMatch(/could not be downloaded/i);
    // The browser's own message is not shown to the reader.
    expect(text).not.toContain("Failed to fetch");
  });
});

/* ============================================================
 * Prohibitions
 * ============================================================ */

describe("what the control must never say", () => {
  it("mentions no report, PDF, metric or verdict", () => {
    const { container } = render(<ExportButton query={DEFAULT_QUERY} />);
    const text = (container.textContent ?? "").toLowerCase();
    for (const banned of [
      "report",
      "pdf",
      "coming soon",
      "spend",
      "roas",
      "cpa",
      "cpc",
      "cpm",
      "leads",
      "revenue",
      "click",
      "reach",
      "impression",
      "conversion",
      "winner",
      "loser",
      "best",
      "top performer",
    ]) {
      expect(text, banned).not.toContain(banned);
    }
  });

  it("renders a single control, so nothing is duplicated on a small screen", () => {
    render(<ExportButton query={DEFAULT_QUERY} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("does not force horizontal overflow", () => {
    const { container } = render(<ExportButton query={DEFAULT_QUERY} />);
    expect(container.innerHTML).not.toContain("overflow-x-auto");
    expect(container.innerHTML).not.toMatch(/min-w-\[\d{3,}px\]/);
  });
});
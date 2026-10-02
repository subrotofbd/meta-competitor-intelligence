/**
 * Focused tests for the provenance primitives.
 *
 * ## What these tests are actually defending
 *
 * Every rule here is a rule the product can break silently. A missing value rendered as
 * `0` still looks like data. A longevity badge that says "best" still reads as a claim.
 * A `source_url` in an `<img>` still looks like a thumbnail, right up until the browser
 * fetches it. None of those failures throws, so nothing but a test catches them.
 *
 * ## The wording ban is asserted against real rendered output
 *
 * `prohibited wording never appears` renders every primitive with representative data
 * and scans the combined text for `winner`, `loser`, `best`, and `top performer`. It
 * passes only while the components keep their wordings, and it fails the moment one of
 * them drifts -- which is the only moment it is worth anything.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AdStatus,
  ContextOut,
  DurationOut,
  EvidenceClass,
  MediaReferenceOut,
} from "../../types/api";
import { AIInterpretationBadge, AIInterpretationBadgeForAnalysis } from "./AIInterpretationBadge";
import { ContextStatus } from "./ContextStatus";
import { DataOriginBadge } from "./DataOriginBadge";
import { EvidenceClassBadge } from "./EvidenceClassBadge";
import { BYTES_NOT_ACQUIRED, MediaAvailability } from "./MediaAvailability";
import { DurationSignal, LONG_RUNNING_TOOLTIP } from "./DurationSignal";
import { EM_DASH, NullValue } from "./NullValue";
import { SafeText } from "./SafeText";

/* ============================================================
 * Sample data
 * ============================================================ */

const DURATION: DurationOut = {
  days: 214,
  bucket: "Long-running",
  source: "meta_delivery_start",
  is_long_running_signal: true,
};

const CONTEXT = (overrides: Partial<ContextOut> = {}): ContextOut => ({
  facebook_page_id: "11111111-1111-4111-8111-111111111111",
  country: "IN",
  current_status: "seen",
  provider_active: true,
  not_seen_since_at: null,
  last_status_run_id: null,
  ...overrides,
});

const MEDIA: MediaReferenceOut = {
  provider: "meta",
  provider_key: "mock-media-0001",
  source_url: "https://cdn.example.invalid/mock-media-0001.jpg",
  mime: "image/jpeg",
  width: 1080,
  height: 1080,
  duration_seconds: null,
  first_seen_at: "2026-10-02T05:39:37.303283+00:00",
  last_seen_at: "2026-10-02T05:39:37.303283+00:00",
  bytes_available: false,
};

/* ============================================================
 * NullValue
 * ============================================================ */

describe("NullValue", () => {
  it("renders exactly an em dash for null and undefined", () => {
    for (const value of [null, undefined]) {
      const { container } = render(<NullValue value={value} />);
      expect(container.textContent).toBe(EM_DASH);
    }
  });

  it("renders 0 as 0, not as an em dash", () => {
    // The defect this prevents. Longevity has a real zero -- an ad first seen today has
    // run for zero days -- and a truthiness check would erase it, showing "we do not
    // know" where the truth is "no time has passed".
    render(<NullValue value={0} />);
    expect(screen.getByTestId("null-value").textContent).toBe("0");
    expect(screen.getByTestId("null-value").getAttribute("data-missing")).toBe("false");
  });

  it("never renders N/A, and never invents a placeholder", () => {
    const { container } = render(<NullValue value={null} />);
    const text = (container.textContent ?? "").toLowerCase();
    expect(text).toBe(EM_DASH);
    expect(text).not.toContain("n/a");
    expect(text).not.toContain("unknown");
    expect(text).not.toContain("null");
  });

  it("marks a missing value so it is distinguishable from a real one", () => {
    render(<NullValue value={null} />);
    expect(screen.getByTestId("null-value").getAttribute("data-missing")).toBe("true");
  });

  it("treats an empty string as missing rather than rendering an invisible gap", () => {
    render(<NullValue value="" />);
    expect(screen.getByTestId("null-value").textContent).toBe(EM_DASH);
  });
});

/* ============================================================
 * DataOriginBadge
 * ============================================================ */

describe("DataOriginBadge", () => {
  const cases = [
    ["official_api", "Official API"],
    ["public_ui", "Public UI"],
    ["third_party", "Third party"],
    ["user_import", "Imported by operator"],
  ] as const;

  it.each(cases)("renders %s with its own label", (origin, label) => {
    render(<DataOriginBadge origin={origin} />);
    expect(screen.getByText(label)).toBeDefined();
  });

  it("uses the same neutral tone for all four, so the axis cannot be read as trust", () => {
    // Four colours here would invite ranking the four origins, which means something.
    // Trust lives on EvidenceClassBadge.
    const tones = cases.map(([origin]) => {
      const { container } = render(<DataOriginBadge origin={origin} />);
      return container.querySelector(".badge")?.className;
    });
    expect(new Set(tones).size).toBe(1);
    expect(tones[0]).toContain("badge--neutral");
  });
});

/* ============================================================
 * EvidenceClassBadge
 * ============================================================ */

describe("EvidenceClassBadge", () => {
  const cases: ReadonlyArray<readonly [EvidenceClass, string]> = [
    ["VERIFIED_PUBLIC_DATA", "Verified public data"],
    ["PROVIDER_DATA", "Provider data"],
    ["ESTIMATE", "Estimate"],
    ["AI_INTERPRETATION", "AI interpretation"],
  ];

  const toneOf = (evidenceClass: EvidenceClass): string => {
    const { container, unmount } = render(
      <EvidenceClassBadge evidenceClass={evidenceClass} />,
    );
    const tone = container.querySelector(".badge")?.className ?? "";
    unmount();
    return tone;
  };

  it.each(cases)("renders %s with its own label", (evidenceClass, label) => {
    render(<EvidenceClassBadge evidenceClass={evidenceClass} />);
    expect(screen.getByText(label)).toBeDefined();
  });

  it("gives AI_INTERPRETATION a tone of its own, distinct from every other value", () => {
    // The concrete risk is a client joining model output onto provider data and
    // presenting an interpretation as something the provider said. If this badge shared
    // a tone with PROVIDER_DATA, that mistake would look correct.
    const ai = toneOf("AI_INTERPRETATION");
    expect(ai).toContain("badge--ai");
    for (const [evidenceClass] of cases) {
      if (evidenceClass === "AI_INTERPRETATION") continue;
      expect(ai).not.toBe(toneOf(evidenceClass));
    }
  });

  it("does not let ESTIMATE be mistaken for verified data", () => {
    expect(toneOf("ESTIMATE")).not.toBe(toneOf("VERIFIED_PUBLIC_DATA"));
  });

  it("spells out AI interpretation rather than abbreviating it", () => {
    render(<EvidenceClassBadge evidenceClass="AI_INTERPRETATION" />);
    expect(screen.getByText("AI interpretation")).toBeDefined();
    expect(screen.queryByText("AI")).toBeNull();
  });
});

/* ============================================================
 * AIInterpretationBadge
 * ============================================================ */

describe("AIInterpretationBadge", () => {
  const COPY_HASH = "b62dc7a3e20d0dc0661c89f14fb38797fb538876fbd2995cb56c0ba4e1a07830";
  const SNAPSHOT_ID = "22222222-2222-4222-8222-222222222222";

  it("visibly marks the value as an AI interpretation", () => {
    render(<AIInterpretationBadge copyHash={COPY_HASH} sourceSnapshotId={SNAPSHOT_ID} />);
    expect(screen.getByText("AI interpretation")).toBeDefined();
  });

  it("carries both identifiers it was derived from", () => {
    // Analysis is copy-scoped: copy_hash identifies the words, source_snapshot_id the
    // observation that produced them. A reader needs both.
    const { container } = render(
      <AIInterpretationBadge copyHash={COPY_HASH} sourceSnapshotId={SNAPSHOT_ID} />,
    );
    const badge = container.querySelector("[data-copy-hash]");
    expect(badge?.getAttribute("data-copy-hash")).toBe(COPY_HASH);
    expect(badge?.getAttribute("data-source-snapshot-id")).toBe(SNAPSHOT_ID);
  });

  it("shows truncated identifiers, and keeps the full value available", () => {
    render(<AIInterpretationBadge copyHash={COPY_HASH} sourceSnapshotId={SNAPSHOT_ID} />);
    expect(screen.getByText(`copy ${COPY_HASH.slice(0, 12)}…${COPY_HASH.slice(-12)}`)).toBeDefined();
    expect(screen.getByTitle(COPY_HASH)).toBeDefined();
  });

  it("fabricates no URL", () => {
    // There is no router yet. An invented href would look real and 404.
    const { container } = render(
      <AIInterpretationBadge copyHash={COPY_HASH} sourceSnapshotId={SNAPSHOT_ID} />,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.innerHTML).not.toContain("href");
  });

  it("makes no request", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<AIInterpretationBadge copyHash={COPY_HASH} sourceSnapshotId={SNAPSHOT_ID} />);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("can be driven straight off an AnalysisOut", () => {
    render(
      <AIInterpretationBadgeForAnalysis
        analysis={{
          evidence_class: "AI_INTERPRETATION",
          copy_hash: COPY_HASH,
          analysis_version: "mock-v1",
          prompt_version: "s3.1-analysis-v1",
          provider: "mock",
          model: null,
          language: "en",
          confidence: "high",
          // `unknown` values, not assumed to be strings.
          interpretation: { hook: "a string", hook_score: 0.8, tags: ["a", "list"] },
          source_snapshot_id: SNAPSHOT_ID,
          created_at: "2026-10-02T00:00:00Z",
        }}
      />,
    );
    expect(screen.getByText("AI interpretation")).toBeDefined();
    expect(document.querySelector("[data-source-snapshot-id]")?.getAttribute("data-source-snapshot-id")).toBe(SNAPSHOT_ID);
  });
});

/* ============================================================
 * DurationSignal
 * ============================================================ */

describe("DurationSignal", () => {
  it("renders the days and the bucket", () => {
    render(<DurationSignal duration={DURATION} />);
    expect(screen.getByText(/214 days/)).toBeDefined();
    expect(screen.getByText("Long-running")).toBeDefined();
  });

  it("always displays the source, for both values", () => {
    // A duration quoted without its source is not interpretable: the provider's
    // delivery start and our first sighting can be months apart.
    for (const [source, expected] of [
      ["meta_delivery_start", "Meta-reported delivery start"],
      ["first_seen_at", "First seen by us"],
    ] as const) {
      const { unmount } = render(
        <DurationSignal duration={{ ...DURATION, source }} />,
      );
      expect(screen.getByText(`from ${expected}`)).toBeDefined();
      unmount();
    }
  });

  it("renders the long-running tooltip with exactly the required text", () => {
    render(<DurationSignal duration={DURATION} />);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.textContent).toBe("duration is a public proxy, not performance");
    // Same string, exported, so the test cannot drift from the component.
    expect(tooltip.textContent).toBe(LONG_RUNNING_TOOLTIP);
    expect(screen.getByTitle(LONG_RUNNING_TOOLTIP)).toBeDefined();
  });

  it("renders LONG-RUNNING SIGNAL when the flag is set, and nothing when it is not", () => {
    const { unmount } = render(<DurationSignal duration={DURATION} />);
    expect(screen.getByText("Long-running signal")).toBeDefined();
    expect(screen.getByTestId("long-running-signal").textContent?.toLowerCase()).toContain(
      "long-running signal",
    );
    unmount();

    render(<DurationSignal duration={{ ...DURATION, is_long_running_signal: false }} />);
    expect(screen.queryByTestId("long-running-signal")).toBeNull();
  });

  it("renders a real zero-day duration as 0, not as an em dash", () => {
    render(<DurationSignal duration={{ ...DURATION, days: 0 }} />);
    expect(screen.getByText(/^0 days$/)).toBeDefined();
    expect(screen.queryByTestId("null-value")).toBeNull();
  });

  it("renders an em dash for a missing duration", () => {
    render(<DurationSignal duration={null} />);
    expect(screen.getByTestId("null-value").textContent).toBe(EM_DASH);
  });

  it("never shows a longevity verdict, whatever the bucket", () => {
    for (const bucket of ["New", "Testing", "Established", "Long-running", "Evergreen"] as const) {
      const { unmount } = render(<DurationSignal duration={{ ...DURATION, bucket }} />);
      expect(screen.queryByText(/winner|loser|best|top performer/i)).toBeNull();
      unmount();
    }
  });
});

/* ============================================================
 * ContextStatus
 * ============================================================ */

describe("ContextStatus", () => {
  const statusCases: ReadonlyArray<[AdStatus, RegExp]> = [
    ["seen", /Seen/],
    ["not_seen_since", /Not seen since/],
    ["presumed_inactive", /Presumed inactive/],
  ];

  it.each(statusCases)("renders %s with its own wording", (current_status, expected) => {
    render(<ContextStatus context={CONTEXT({ current_status })} />);
    expect(screen.getByText(expected)).toBeDefined();
  });

  it("never renders not_seen_since as stopped", () => {
    // Absence from a run is not evidence an ad stopped running.
    render(<ContextStatus context={CONTEXT({ current_status: "not_seen_since" })} />);
    const text = document.body.textContent?.toLowerCase() ?? "";
    expect(text).not.toContain("stopped");
    expect(text).not.toContain("inactive");
    expect(text).toContain("not seen since");
  });

  it("keeps presumed_inactive worded as a presumption", () => {
    // The word "presumed" is load-bearing, not styling. A badge reading "inactive" and
    // nothing else reads as a conclusion.
    const { container } = render(
      <ContextStatus context={CONTEXT({ current_status: "presumed_inactive" })} />,
    );
    expect(container.textContent).toContain("Presumed inactive");

    // No element anywhere presents the status as a bare "Inactive" -- that single word
    // is what turns a presumption into a conclusion.
    for (const node of Array.from(container.querySelectorAll("*"))) {
      expect(node.textContent ?? "").not.toMatch(/^inactive\b/i);
    }

    // The tooltip is on the badge, not on the wrapper: `data-context-status` marks the
    // context, and only the status badge carries the explanation.
    expect(screen.getByTitle(/presumption, not a verdict/)).toBeDefined();
    expect(
      container.querySelector("[data-context-status]")?.getAttribute("data-context-status"),
    ).toBe("presumed_inactive");
  });

  it("keeps provider_active tri-state", () => {
    // Rounding null to false would manufacture "we checked and it was not running"
    // out of the absence of a check.
    const { unmount } = render(<ContextStatus context={CONTEXT({ provider_active: true })} />);
    expect(screen.getByTestId("provider-active").textContent).toContain("reported active");
    unmount();

    render(<ContextStatus context={CONTEXT({ provider_active: false })} />);
    const falseText = screen.getByTestId("provider-active").textContent ?? "";
    expect(falseText).toContain("not reported active");
    // `false` is the provider declining to assert activity, not a conclusion.
    expect(falseText).not.toContain("stopped");
    expect(screen.queryByTestId("null-value")).toBeNull();
  });

  it("renders provider_active null as an em dash, never as false", () => {
    render(<ContextStatus context={CONTEXT({ provider_active: null })} />);
    const node = screen.getByTestId("provider-active");
    expect(node.textContent).toContain(EM_DASH);
    expect(node.textContent).not.toContain("not reported active");
    expect(
      document.querySelector("[data-context-status]")?.getAttribute("data-provider-active"),
    ).toBe("unknown");
  });

  it("shows country, and page identity when props supply it", () => {
    const { unmount } = render(<ContextStatus context={CONTEXT()} />);
    expect(screen.getByText("IN")).toBeDefined();
    unmount();

    render(
      <ContextStatus
        context={CONTEXT()}
        pageName="Aurora Kitchen Studio"
        pageId="mock-page-0001"
      />,
    );
    expect(screen.getByText("Aurora Kitchen Studio")).toBeDefined();
    expect(screen.getByText("mock-page-0001")).toBeDefined();
  });

  it("omits page identity entirely when no props are given", () => {
    // `ContextOut` carries a page id but no name, so the caller must opt in. Rendering
    // a bare uuid would be noise.
    render(<ContextStatus context={CONTEXT()} />);
    expect(screen.getByText("IN")).toBeDefined();
    expect(screen.queryByText(/11111111/)).toBeNull();
  });

  it("shows when the ad was last seen, and never as a stop date", () => {
    render(
      <ContextStatus
        context={CONTEXT({
          current_status: "not_seen_since",
          not_seen_since_at: "2026-09-01T12:00:00+00:00",
        })}
      />,
    );
    expect(screen.getByTestId("not-seen-since").textContent).toContain("2026-09-01 12:00 UTC");
  });
});

/* ============================================================
 * MediaAvailability
 * ============================================================ */

describe("MediaAvailability", () => {
  it("says bytes not acquired when bytes_available is false", () => {
    render(<MediaAvailability media={MEDIA} />);
    expect(screen.getByTestId("bytes-not-acquired").textContent).toBe("bytes not acquired");
    expect(screen.getByTestId("bytes-not-acquired").textContent).toBe(BYTES_NOT_ACQUIRED);
  });

  it("never renders source_url as an image src, or any element that could fetch it", () => {
    const { container } = render(<MediaAvailability media={MEDIA} />);
    // No <img>, no <video>, no <source>, no <iframe>, and no inline background-image.
    for (const tag of ["img", "video", "source", "iframe", "object", "embed"]) {
      expect(container.querySelector(tag)).toBeNull();
    }
    expect(container.innerHTML).not.toContain("background-image");
    expect(container.innerHTML).not.toContain("background:url");
  });

  it("renders source_url as text and a data attribute, never as a fetchable link", () => {
    // An anchor would send the reader to the provider's CDN, around the authenticated
    // media route.
    const { container } = render(<MediaAvailability media={MEDIA} />);
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("[data-source-url]")?.getAttribute("data-source-url")).toBe(
      MEDIA.source_url,
    );
    expect(screen.getByTitle(MEDIA.source_url!)).toBeDefined();
  });

  it("triggers no network request", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<MediaAvailability media={MEDIA} />);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("keeps a null duration as an em dash, never 0", () => {
    // An image has no duration. `0` would read as "an instant video".
    render(<MediaAvailability media={MEDIA} />);
    expect(screen.getByTestId("null-value").textContent).toBe(EM_DASH);
    expect(document.body.textContent).not.toContain("0s");
  });

  it("renders an em dash when source_url is absent", () => {
    render(<MediaAvailability media={{ ...MEDIA, source_url: null }} />);
    expect(screen.getAllByTestId("null-value").length).toBeGreaterThan(0);
    expect(document.querySelector("[data-source-url]")).toBeNull();
  });
});

/* ============================================================
 * SafeText
 * ============================================================ */

describe("SafeText", () => {
  it("renders a nullable string, and an em dash when it is absent", () => {
    const { unmount } = render(<SafeText value="Provider text" />);
    expect(screen.getByText("Provider text")).toBeDefined();
    unmount();

    for (const value of [null, undefined]) {
      const { container, unmount: u } = render(<SafeText value={value} />);
      expect(container.textContent).toBe(EM_DASH);
      u();
    }
  });

  it("renders markup in the value as text, not as elements", () => {
    // React escapes interpolated children. This pins that behaviour for this component:
    // a future edit that reaches for dangerouslySetInnerHTML would turn this test red.
    const hostile = `<script>globalThis.__pwned = true</script><img src=x onerror="alert(1)">`;
    const { container } = render(<SafeText value={hostile} />);

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toBe(hostile);
    expect((globalThis as Record<string, unknown>)["__pwned"]).toBeUndefined();
  });

  it("handles characters that are meaningful in other contexts", () => {
    const { container } = render(<SafeText value={'Tea & coffee <every day> "quoted"'} />);
    expect(container.textContent).toBe('Tea & coffee <every day> "quoted"');
  });
});

/* ============================================================
 * The wording ban, asserted against everything at once
 * ============================================================ */

describe("prohibited wording", () => {
  const BANNED = /winner|loser|best|top performer/i;

  it("never appears in any primitive, with representative data", () => {
    // Each component is rendered in turn and the text accumulated, so a ban that only
    // holds for one component is still caught.
    const parts: string[] = [];

    for (const origin of ["official_api", "public_ui", "third_party", "user_import"] as const) {
      const { container, unmount } = render(<DataOriginBadge origin={origin} />);
      parts.push(container.textContent ?? "");
      unmount();
    }

    for (const evidenceClass of [
      "VERIFIED_PUBLIC_DATA",
      "PROVIDER_DATA",
      "ESTIMATE",
      "AI_INTERPRETATION",
    ] as const) {
      const { container, unmount } = render(
        <EvidenceClassBadge evidenceClass={evidenceClass} />,
      );
      parts.push(container.textContent ?? "");
      unmount();
    }

    for (const duration of [
      DURATION,
      { ...DURATION, days: 0, bucket: "New" as const, is_long_running_signal: false },
      null,
    ]) {
      const { container, unmount } = render(<DurationSignal duration={duration} />);
      parts.push(container.textContent ?? "");
      unmount();
    }

    for (const current_status of ["seen", "not_seen_since", "presumed_inactive"] as const) {
      const { container, unmount } = render(
        <ContextStatus context={CONTEXT({ current_status, provider_active: null })} />,
      );
      parts.push(container.textContent ?? "");
      unmount();
    }

    const mediaRender = render(<MediaAvailability media={MEDIA} />);
    parts.push(mediaRender.container.textContent ?? "");
    mediaRender.unmount();

    const combined = parts.join(" ");
    expect(combined).not.toMatch(BANNED);
    // A sanity floor, so the ban cannot pass by rendering nothing at all.
    expect(combined.length).toBeGreaterThan(100);
  });
});
/**
 * The Ad Detail screen: one ad's complete research record, from `GET /ads/{ad_id}`.
 *
 * ## Exactly one request
 *
 * This screen fetches the ad and nothing else. Not the list, not the competitor
 * directory, not a media URL. That is a deliberate constraint, and it has a visible
 * consequence recorded below rather than a workaround.
 *
 * ## The consequence: Page names are absent
 *
 * `AdDetailOut` carries `contexts[].facebook_page_id` and no name. A human-readable
 * competitor and Page name lives only in `GET /competitors`, which this screen must not
 * call. So the Page is identified by its internal id -- compactly, with the full value on
 * hover -- and **no name is invented**. Stamping a placeholder brand here would be worse
 * than an identifier: it would look like data the product has.
 *
 * ## The AI panel states its own status either way
 *
 * `analysis: null` renders **"not analysed"**, a statement about the record. It is not
 * rendered as an object of fourteen null fields, which would read as "we analysed it and
 * found nothing" -- the exact confusion `schemas/ads.py` warns about. When an analysis
 * does exist it is badged `AI_INTERPRETATION` and clearly separated from everything the
 * provider reported.
 */

import { useEffect, useState } from "react";

import { fetchAd } from "../../api/library";
import { ApiError } from "../../api/client";
import type { AdDetailOut } from "../../types/api";
import { AIInterpretationBadge } from "../provenance/AIInterpretationBadge";
import { ContextStatus } from "../provenance/ContextStatus";
import { DataOriginBadge } from "../provenance/DataOriginBadge";
import { DurationSignal } from "../provenance/DurationSignal";
import { EvidenceClassBadge } from "../provenance/EvidenceClassBadge";
import { MediaAvailability } from "../provenance/MediaAvailability";
import { NullValue } from "../provenance/NullValue";
import { SafeText } from "../provenance/SafeText";
import { formatUtcDateTime } from "../provenance/format";
import { PlatformList } from "./AdsGrid";
import { adPath, navigate, routeLinkProps } from "../../router";

/**
 * The fourteen agreed interpretation fields, in reading order.
 *
 * Anything not on this list is still rendered, after these. A future
 * `analysis_version` may add fields, and silently dropping them would make the panel lie
 * about how much the model actually said.
 */
const KNOWN_INTERPRETATION_FIELDS = [
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
] as const;

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "not-found" }
  | { readonly kind: "error"; readonly message: string }
  | { readonly kind: "ready"; readonly ad: AdDetailOut };

export function AdDetail({ adId }: { readonly adId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    (async () => {
      try {
        const ad = await fetchAd(adId, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setState({ kind: "ready", ad });
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
          setState({ kind: "not-found" });
          return;
        }
        // The response body is for the console, not the screen.
        console.error("Ad detail request failed", error);
        setState({ kind: "error", message: describe(error) });
      }
    })();
    return () => controller.abort();
  }, [adId]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "not-found") return <NotFoundState />;
  if (state.kind === "error") return <ErrorState message={state.message} />;

  const ad = state.ad;
  return (
    <article aria-labelledby="ad-detail-heading" className="flex flex-col gap-8">
      <BackLink />

      <header className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <DataOriginBadge origin={ad.data_origin} />
          <span className="ref text-slate-500 dark:text-slate-400">{ad.provider}</span>
        </div>
        <h2 id="ad-detail-heading" className="text-xl font-semibold tracking-tight">
          <SafeText value={ad.meta_ad_id} />
        </h2>
      </header>

      <IdentitySection ad={ad} />
      <CopySection ad={ad} />
      <ContextsSection ad={ad} />
      <DurationSection ad={ad} />
      <AnalysisSection ad={ad} />
      <MediaSection ad={ad} />
      <SnapshotsSection />
    </article>
  );
}

/* ============================================================
 * Sections
 * ============================================================ */

/**
 * Back to the library.
 *
 * The browser's own Back is what restores the filter state, because the library's URL is
 * still the previous history entry. So this control uses it when there is somewhere to go
 * back to, and only falls back to a plain link when the screen was opened directly.
 */
function BackLink() {
  const href = "/";
  return (
    <a
      {...routeLinkProps(href)}
      onClick={(event) => {
        if (window.history.length > 1) {
          event.preventDefault();
          window.history.back();
        }
      }}
      className="w-fit rounded-md text-sm text-slate-600 underline decoration-slate-300 underline-offset-4 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:text-slate-400 dark:decoration-slate-600 dark:hover:text-slate-100 dark:focus-visible:outline-sky-400"
    >
      ← Back to Ad Library
    </a>
  );
}

/**
 * The shared card. One restrained surface, a heading, and room to breathe.
 *
 * Sections are separated by whitespace and a single hairline rather than by a colour or a
 * shadow. A detail page with eight boxed panels is a dashboard, and this is not one.
 */
function Section({
  title,
  children,
  aside,
}: {
  readonly title: string;
  readonly children: React.ReactNode;
  readonly aside?: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 border-t border-slate-200 pt-6 dark:border-slate-800">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** A label and a value. The grid is what makes a long record scannable. */
function Field({ label, children }: { readonly label: string; readonly children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="min-w-0 text-sm break-words">{children}</dd>
    </div>
  );
}

const FIELD_GRID = "grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2";

function IdentitySection({ ad }: { ad: AdDetailOut }) {
  const pages = [...new Set(ad.contexts.map((c) => c.facebook_page_id))];
  const countries = [...new Set(ad.contexts.map((c) => c.country))];

  return (
    <Section title="Identity">
      <dl className={FIELD_GRID}>
        <Field label="Provider">
          <SafeText value={ad.provider} />
        </Field>
        <Field label="Provider ad id">
          <span className="ref">
            <SafeText value={ad.meta_ad_id} />
          </span>
        </Field>
        <Field label="Record id">
          <span className="ref text-slate-500 dark:text-slate-400">
            <SafeText value={ad.id} />
          </span>
        </Field>
        <Field label="First seen">
          <SafeText value={formatUtcDateTime(ad.first_seen_at)} />
        </Field>
        <Field label="Last seen">
          <SafeText value={formatUtcDateTime(ad.last_seen_at)} />
        </Field>
        <Field label="Countries">
          {countries.length === 0 ? <NullValue value={null} /> : countries.join(", ")}
        </Field>
        <Field label="Platforms">
          <PlatformList platforms={ad.platforms} />
        </Field>
        <Field label="Page ids">
          {/*
            `AdDetailOut` carries no Page or competitor name, and this screen must not
            fetch the directory to get one. The identifier is shown instead, which is a
            true statement about what the record holds.
          */}
          {pages.length === 0 ? (
            <NullValue value={null} />
          ) : (
            <ul className="flex flex-col gap-0.5">
              {pages.map((id) => (
                <li key={id} className="ref text-slate-500 dark:text-slate-400" title={id}>
                  {id}
                </li>
              ))}
            </ul>
          )}
        </Field>
      </dl>
    </Section>
  );
}

function CopySection({ ad }: { ad: AdDetailOut }) {
  const copy = ad.copy_fields;

  return (
    <Section title="Ad copy">
      {copy === null ? (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          <NullValue value={null} /> This record carries no copy, because it has no
          snapshot yet.
        </p>
      ) : (
        <dl className="flex flex-col gap-4">
          <Field label="Primary text">
            {/* Not truncated. This is the full record, and a cut-off sentence here would
                defeat the purpose of a detail screen. */}
            <SafeText value={copy.primary_text} className="whitespace-pre-wrap leading-relaxed" />
          </Field>
          <Field label="Headline">
            <SafeText value={copy.headline} />
          </Field>
          <Field label="Description">
            <SafeText value={copy.description} />
          </Field>
          <Field label="Call to action">
            <SafeText value={copy.cta} />
          </Field>
          <Field label="Destination URL">
            {copy.destination_url === null ? (
              <NullValue value={null} />
            ) : (
              // Text plus an explicit link. Nothing here is fetched on render -- an
              // anchor is inert until a person activates it -- and `noreferrer` keeps the
              // destination from learning where the click came from.
              <a
                href={copy.destination_url}
                target="_blank"
                rel="noreferrer noopener"
                className="break-all text-sky-700 underline underline-offset-2 hover:text-sky-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:text-sky-300 dark:hover:text-sky-100 dark:focus-visible:outline-sky-400"
              >
                <SafeText value={copy.destination_url} />
              </a>
            )}
          </Field>
        </dl>
      )}
    </Section>
  );
}

function ContextsSection({ ad }: { ad: AdDetailOut }) {
  return (
    <Section
      title="Context and status"
      aside={
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {ad.contexts.length === 0
            ? "No contexts recorded"
            : `${ad.contexts.length} ${ad.contexts.length === 1 ? "context" : "contexts"}`}
        </p>
      }
    >
      {/*
        Every context stays its own block. An ad served on several Pages in several
        countries has several independent conclusions, and collapsing them into one
        status would assert one of them falsely.
      */}
      {ad.contexts.length === 0 ? (
        <NullValue value={null} />
      ) : (
        <ul className="flex flex-col gap-4">
          {ad.contexts.map((context) => (
            <li
              key={`${context.facebook_page_id}:${context.country}`}
              data-testid="detail-context"
              className="flex flex-col gap-1 rounded-md border border-slate-200 p-3 dark:border-slate-800"
            >
              <ContextStatus
                context={context}
                pageId={context.facebook_page_id}
                // A name would have to come from the directory, which this screen must
                // not request. Null renders as an em dash rather than a guess.
                pageName={null}
              />
              {context.not_seen_since_at !== null ? (
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Last seen:{" "}
                  <SafeText value={formatUtcDateTime(context.not_seen_since_at)} />
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function DurationSection({ ad }: { ad: AdDetailOut }) {
  const snapshot = ad.latest_snapshot;
  return (
    <Section title="Longevity">
      <div className="flex flex-col gap-3">
        <DurationSignal duration={ad.duration} />
        <dl className={FIELD_GRID}>
          <Field label="Meta-reported start">
            <SafeText value={formatUtcDateTime(snapshot?.meta_delivery_start ?? null)} />
          </Field>
          <Field label="Provider reported status">
            <SafeText value={snapshot?.ad_status ?? null} />
          </Field>
        </dl>
      </div>
    </Section>
  );
}

/* ============================================================
 * AI interpretation
 * ============================================================ */

function AnalysisSection({ ad }: { ad: AdDetailOut }) {
  const analysis = ad.analysis;

  return (
    <Section
      title="Copy interpretation"
      // A neutral statement, not a badge. The badge below is the claim about the value.
      aside={
        analysis === null ? (
          <p data-testid="analysis-absent" className="text-xs text-slate-500 dark:text-slate-400">
            not analysed
          </p>
        ) : (
          <EvidenceClassBadge evidenceClass={analysis.evidence_class} />
        )
      }
    >
      {analysis === null ? (
        // Deliberately a sentence, and deliberately not fourteen empty fields.
        <p className="text-sm text-slate-600 dark:text-slate-400">
          No copy analysis has been stored for this record. Nothing has been inferred on
          your behalf.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {/*
            Distinct from everything above: its own tinted surface, and a note saying what
            it is. The point is that a reader cannot mistake a model's reading of the
            words for something Meta reported.
          */}
          <div className="rounded-lg border border-violet-300 bg-violet-50/50 p-4 dark:border-violet-800 dark:bg-violet-500/5">
            <p className="mb-3 text-xs text-violet-900 dark:text-violet-200">
              This is a model&apos;s reading of the ad&apos;s words. It is not something the
              provider stated, and it is not a fact about the ad.
            </p>

            <AIInterpretationBadge
              copyHash={analysis.copy_hash}
              sourceSnapshotId={analysis.source_snapshot_id}
            />

            <dl className={`mt-4 ${FIELD_GRID}`}>
              <Field label="Language">
                <SafeText value={analysis.language} />
              </Field>
              <Field label="Confidence">
                <SafeText value={analysis.confidence} />
              </Field>
              <Field label="Analysis version">
                <span className="ref">
                  <SafeText value={analysis.analysis_version} />
                </span>
              </Field>
              <Field label="Prompt version">
                <span className="ref">
                  <SafeText value={analysis.prompt_version} />
                </span>
              </Field>
              <Field label="Model provider">
                <SafeText value={analysis.provider} />
              </Field>
              <Field label="Model">
                <SafeText value={analysis.model} />
              </Field>
            </dl>

            <InterpretationTable interpretation={analysis.interpretation} />
          </div>
        </div>
      )}
    </Section>
  );
}

/**
 * Renders the opaque `interpretation` mapping.
 *
 * Three rules, and each has broken something:
 *
 * 1. **Known fields first, unknown after.** A future `analysis_version` may add fields,
 *    and dropping them would make the panel understate what the model said.
 * 2. **Values are `unknown`, not `string`.** A number or an object must render as
 *    itself, not crash and not be stringified into `[object Object]`.
 * 3. **`{}` is a real reading of sparse copy**, so an empty mapping says so rather than
 *    rendering an empty table with no explanation.
 */
function InterpretationTable({
  interpretation,
}: {
  readonly interpretation: Readonly<Record<string, unknown>>;
}) {
  const entries = Object.entries(interpretation);
  if (entries.length === 0) {
    return (
      <p data-testid="interpretation-empty" className="mt-4 text-sm text-violet-900 dark:text-violet-200">
        The model answered with every field empty. That is a reading of sparse copy, not a
        missing analysis.
      </p>
    );
  }

  const known = entries.filter(([key]) =>
    (KNOWN_INTERPRETATION_FIELDS as readonly string[]).includes(key),
  );
  const unknown = entries.filter(
    ([key]) => !(KNOWN_INTERPRETATION_FIELDS as readonly string[]).includes(key),
  );

  return (
    <dl data-testid="interpretation-table" className="mt-4 flex flex-col gap-3">
      {[...known, ...unknown].map(([key, value]) => (
        <div key={key} className="flex flex-col gap-0.5">
          <dt className="text-xs text-violet-800/80 dark:text-violet-300/80">
            {humanise(key)}
          </dt>
          <dd className="text-sm leading-relaxed break-words">
            <InterpretationValue value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Render whatever a model actually returned, without assuming it is a string. */
function InterpretationValue({ value }: { readonly value: unknown }) {
  if (value === null || value === undefined) return <NullValue value={null} />;
  if (typeof value === "string") return <SafeText value={value} />;
  if (typeof value === "number" || typeof value === "boolean") {
    return <span className="tabular-nums">{String(value)}</span>;
  }
  // An object or an array is not something the v1 contract defines, so it is shown as
  // JSON rather than guessed at. Still plain text -- never markup.
  let serialised: string;
  try {
    serialised = JSON.stringify(value) ?? String(value);
  } catch {
    // A circular structure is not something a JSON API can produce, but rendering the
    // field as unknown beats failing the whole panel over one value.
    serialised = "[unreadable value]";
  }
  return <SafeText value={serialised} className="ref" />;
}

/** `why_it_may_work` reads better as `Why it may work`. Presentation only. */
function humanise(key: string): string {
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/* ============================================================
 * Media
 * ============================================================ */

function MediaSection({ ad }: { ad: AdDetailOut }) {
  return (
    <Section title="Media references" aside={<MediaCount count={ad.media.length} />}>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        These are references the provider reported. This product has not acquired the
        files and does not load them.
      </p>
      {ad.media.length === 0 ? (
        <NullValue value={null} />
      ) : (
        <ul className="mt-2 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {ad.media.map((asset) => (
            <li
              key={`${asset.provider}:${asset.provider_key}`}
              data-testid="detail-media"
              className="rounded-md border border-slate-200 p-3 dark:border-slate-800"
            >
              <MediaAvailability media={asset} />
              <dl className={`mt-3 ${FIELD_GRID}`}>
                <Field label="MIME type">
                  <SafeText value={asset.mime} />
                </Field>
                <Field label="Dimensions">
                  {asset.width === null || asset.height === null ? (
                    <NullValue value={null} />
                  ) : (
                    <span className="tabular-nums">
                      {asset.width} × {asset.height}
                    </span>
                  )}
                </Field>
                <Field label="First seen">
                  <SafeText value={formatUtcDateTime(asset.first_seen_at)} />
                </Field>
                <Field label="Last seen">
                  <SafeText value={formatUtcDateTime(asset.last_seen_at)} />
                </Field>
              </dl>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function MediaCount({ count }: { readonly count: number }) {
  if (count === 0) return <span className="text-xs text-slate-500 dark:text-slate-400">none recorded</span>;
  return (
    <span className="text-xs text-slate-500 dark:text-slate-400">
      {count} {count === 1 ? "reference" : "references"}
    </span>
  );
}

/* ============================================================
 * Snapshots
 * ============================================================ */

function SnapshotsSection() {
  return (
    <Section title="Historical snapshots">
      {/*
        A statement, not a link. The history lives behind its own endpoint and its own
        screen, and inventing a route here would produce a 404 that looks like a broken
        product. "Coming soon" is avoided for the same reason: it is a feature claim
        about something not built.
      */}
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Every observation of this ad is retained as a separate snapshot, append-only, and
        is served by its own endpoint. This page shows only the latest observation.
      </p>
    </Section>
  );
}

/* ============================================================
 * States
 * ============================================================ */

function LoadingState() {
  return (
    <div data-testid="detail-loading" role="status" aria-live="polite" className="flex flex-col gap-3">
      <p className="text-sm text-slate-600 dark:text-slate-400">Loading ad record…</p>
      {/* Bars, never a fake ad. */}
      {[70, 45, 90, 30].map((width, index) => (
        <div
          key={index}
          aria-hidden="true"
          className="h-4 animate-pulse rounded bg-slate-100 dark:bg-slate-800"
          style={{ width: `${width}%` }}
        />
      ))}
    </div>
  );
}

function NotFoundState() {
  return (
    <div data-testid="detail-not-found" className="flex flex-col gap-3">
      <BackLink />
      <h2 className="text-xl font-semibold tracking-tight">Ad not found</h2>
      <p className="max-w-prose text-sm text-slate-600 dark:text-slate-400">
        No record with that id. It may never have been collected, or the link may be
        mistyped.
      </p>
    </div>
  );
}

function ErrorState({ message }: { readonly message: string }) {
  return (
    <div
      data-testid="detail-error"
      role="alert"
      className="flex flex-col gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-700 dark:bg-amber-500/10"
    >
      <BackLink />
      <h2 className="font-medium text-amber-900 dark:text-amber-200">Could not load this ad</h2>
      <p className="text-sm text-amber-900 dark:text-amber-200">{message}</p>
    </div>
  );
}

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 400) return "The server rejected that id.";
    if (error.status >= 500) return "The server could not complete the request. Try again shortly.";
    if (error.status === 422) return "That id is not one this server recognises.";
    return "The request was rejected, so this record could not be loaded.";
  }
  return "The server could not be reached. Check that the API is running.";
}

export { adPath, navigate };
export default AdDetail;
/**
 * Historical snapshots: every observation of one ad, oldest last.
 *
 * ## The history is the product
 *
 * `ad_snapshots` is append-only and commercial ads that stop running disappear from Meta
 * permanently, so this list cannot be re-collected. It is also the reason the product
 * exists at all: a copy preview tells you what an ad says now, and this tells you what it
 * said before.
 *
 * ## One request, keyed on the paging string
 *
 * The effect is keyed on the serialised paging parameters rather than the state object,
 * so a `popstate` that resolves to the page already on screen -- browser history restore,
 * or Back to where you were -- produces an equal value and no request. The ad detail
 * itself is not refetched by paging here.
 *
 * ## The order is the backend's
 *
 * `ad_snapshots.created_at DESC, id DESC`. Not re-sorted, not grouped, not re-dated.
 * Re-ordering an append-only history would present a sequence of events that never
 * happened.
 *
 * ## "Copy changed" only where it can actually be established
 *
 * The badge compares the **stored copy fields** of this snapshot with the next older
 * snapshot **in the returned array**. Nothing is hashed or recomputed. When there is no
 * next snapshot to compare with -- the last row on a page -- the label is the neutral
 * "Observed snapshot", because claiming a change against a snapshot this response did not
 * contain would be a guess dressed as a finding.
 *
 * ## A snapshot's `ad_status` is not a status
 *
 * It is what the provider reported *at that observation*. It is not the S2.3 context
 * conclusion, it is not current, and it is not global. The label says so, and the endpoint
 * carries no historical `contexts[]`, so none is invented here.
 */

import { useCallback, useEffect, useState } from "react";

import { fetchSnapshots } from "../../api/library";
import { ApiError } from "../../api/client";
import type { CopyFieldsOut, SnapshotListOut, SnapshotOut } from "../../types/api";
import { MediaAvailability } from "../provenance/MediaAvailability";
import { NullValue } from "../provenance/NullValue";
import { SafeText } from "../provenance/SafeText";
import { formatUtcDateTime, truncateIdentifier } from "../provenance/format";
import { PlatformList } from "./AdsGrid";
import {
  DEFAULT_SNAPSHOT_PAGING,
  SNAPSHOT_PAGE_SIZE_OPTIONS,
  snapshotPagingFromParams,
  snapshotPagingToParams,
  type SnapshotPaging,
} from "./snapshotPaging";

/** The five stored copy fields, in the order they are displayed. */
const COPY_FIELDS = [
  ["primary_text", "Primary text"],
  ["headline", "Headline"],
  ["description", "Description"],
  ["cta", "Call to action"],
  ["destination_url", "Destination URL"],
] as const satisfies ReadonlyArray<readonly [keyof CopyFieldsOut, string]>;

type State =
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly message: string }
  | { readonly kind: "ready"; readonly snapshots: SnapshotListOut };

export function SnapshotHistory({ adId }: { readonly adId: string }) {
  const [paging, setPaging] = useState<SnapshotPaging>(() =>
    snapshotPagingFromParams(window.location.search),
  );
  const [state, setState] = useState<State>({ kind: "loading" });

  const pagingKey = snapshotPagingToParams(paging).toString();

  // Paging is written to the URL so a particular page of history is a shareable link, and
  // so a refresh returns to the same place.
  useEffect(() => {
    const url =
      pagingKey === ""
        ? window.location.pathname
        : `${window.location.pathname}?${pagingKey}`;
    const current = `${window.location.pathname}${window.location.search}`;
    if (url !== current) window.history.replaceState(null, "", url);
  }, [pagingKey]);

  useEffect(() => {
    const onPopState = () => setPaging(snapshotPagingFromParams(window.location.search));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    (async () => {
      try {
        const snapshots = await fetchSnapshots(adId, paging, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setState({ kind: "ready", snapshots });
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error("Snapshot history request failed", error);
        setState({ kind: "error", message: describe(error) });
      }
    })();
    return () => controller.abort();
  }, [adId, paging.page, paging.pageSize]);

  const onPage = useCallback((patch: Partial<SnapshotPaging>) => {
    setPaging((current) => ({
      ...current,
      ...patch,
      // Any change other than paging itself starts again at the top: staying on page 4 of
      // a history that now has one page would show an empty list and read as "no
      // snapshots", which is false.
      page: patch.page ?? 1,
    }));
  }, []);

  const total = state.kind === "ready" ? state.snapshots.total : 0;
  const lastPage = Math.max(1, Math.ceil(total / Math.max(1, paging.pageSize)));

  return (
    <section
      aria-labelledby="snapshots-heading"
      data-testid="snapshot-history"
      className="flex flex-col gap-3 border-t border-slate-200 pt-6 dark:border-slate-800"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3
          id="snapshots-heading"
          className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
        >
          Historical snapshots
        </h3>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {state.kind === "ready" ? `${total} retained` : ""}
        </p>
      </div>

      <p className="text-sm text-slate-600 dark:text-slate-400">
        Every observation this product recorded, newest first. Each row is what the
        provider reported at that moment, and rows are never edited afterwards.
      </p>

      {state.kind === "loading" ? <SnapshotSkeleton /> : null}
      {state.kind === "error" ? (
        <p
          data-testid="snapshot-error"
          role="alert"
          className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-500/10 dark:text-amber-200"
        >
          {state.message}
        </p>
      ) : null}
      {state.kind === "ready" && state.snapshots.items.length === 0 ? (
        <p data-testid="snapshots-empty" className="text-sm text-slate-600 dark:text-slate-400">
          No snapshots are recorded for this ad.
        </p>
      ) : null}

      {state.kind === "ready" && state.snapshots.items.length > 0 ? (
        <>
          {/*
            A quiet spine rather than a decorated timeline: one hairline down the left and
            a small marker per observation. The eye gets a sense of sequence without a
            chart.
          */}
          <ol className="flex flex-col gap-3 border-l border-slate-200 pl-4 dark:border-slate-800">
            {state.snapshots.items.map((snapshot, index) => (
              <SnapshotRow
                key={snapshot.id}
                snapshot={snapshot}
                // Only comparable against a snapshot this response actually contains.
                previous={state.snapshots.items[index + 1] ?? null}
              />
            ))}
          </ol>

          <nav
            aria-label="Snapshot pagination"
            data-testid="snapshot-pagination"
            className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-3 dark:border-slate-800"
          >
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Page <span className="tabular-nums">{paging.page}</span> of{" "}
              <span className="tabular-nums">{lastPage}</span>
            </p>

            <div className="flex flex-wrap items-center gap-2">
              <label
                htmlFor="snapshot-page-size"
                className="text-xs text-slate-500 dark:text-slate-400"
              >
                Per page
              </label>
              <select
                id="snapshot-page-size"
                value={String(paging.pageSize)}
                onChange={(event) => onPage({ pageSize: Number(event.target.value) })}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900"
              >
                {SNAPSHOT_PAGE_SIZE_OPTIONS.map((size) => (
                  <option key={size} value={String(size)}>
                    {size}
                  </option>
                ))}
              </select>

              <button
                type="button"
                onClick={() => onPage({ page: paging.page - 1 })}
                disabled={paging.page <= 1}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:border-slate-700 dark:focus-visible:outline-sky-400"
              >
                Previous snapshots
              </button>
              <button
                type="button"
                onClick={() => onPage({ page: paging.page + 1 })}
                disabled={paging.page >= lastPage}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:border-slate-700 dark:focus-visible:outline-sky-400"
              >
                Next snapshots
              </button>
            </div>
          </nav>
        </>
      ) : null}
    </section>
  );
}

/* ============================================================
 * One observation
 * ============================================================ */

/**
 * Compare the stored copy of two snapshots.
 *
 * `JSON.stringify` over the five fields, which is a comparison of stored values -- no
 * digest is computed, and no stored hash is read for this purpose. The backend's
 * `copy_hash` exists precisely so this is never necessary; using it here would tie a
 * rendering decision to a hash the client cannot explain.
 */
function copySignature(copy: CopyFieldsOut): string {
  return JSON.stringify([
    copy.primary_text,
    copy.headline,
    copy.description,
    copy.cta,
    copy.destination_url,
  ]);
}

function SnapshotRow({
  snapshot,
  previous,
}: {
  readonly snapshot: SnapshotOut;
  readonly previous: SnapshotOut | null;
}) {
  const comparable = previous !== null;
  const differs = comparable && copySignature(snapshot.copy_fields) !== copySignature(previous.copy_fields);

  return (
    <li
      data-testid="snapshot-row"
      className="relative flex flex-col gap-3 rounded-lg border border-slate-200 p-4 dark:border-slate-800"
    >
      {/* The marker on the spine. Decoration only, and hidden from assistive tech. */}
      <span
        aria-hidden="true"
        className="absolute -left-[1.4rem] top-5 h-2 w-2 rounded-full bg-slate-300 dark:bg-slate-600"
      />

      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-medium">
          <SafeText value={formatUtcDateTime(snapshot.created_at)} />
        </h4>
        <span
          data-testid="snapshot-label"
          // A claim about the comparison that was actually performed, so it stays honest
          // even when the next older snapshot is on another page.
          title={
            comparable
              ? "Compared with the next older snapshot returned in this result."
              : "No older snapshot in this result to compare with."
          }
          className="rounded-full border border-slate-300 px-2 py-0.5 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-400"
        >
          {differs ? "Copy changed since the previous observation" : "Observed snapshot"}
        </span>
      </div>

      {/* This snapshot's own platforms. Never the ad's current list. */}
      <div className="flex flex-wrap items-center gap-2">
        <PlatformList platforms={snapshot.platforms} />
      </div>

      {/*
        The provider's status *at that observation*. Deliberately not called "status":
        it is not the S2.3 context conclusion, not current, and not global.
      */}
      <p className="text-xs text-slate-500 dark:text-slate-400">
        Provider reported at this observation:{" "}
        <SafeText value={snapshot.ad_status} />
      </p>

      <dl className="flex flex-col gap-2">
        {COPY_FIELDS.map(([key, label]) => (
          <div key={key} className="flex flex-col gap-0.5">
            <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
            <dd className="text-sm break-words">
              {/* Not truncated. On a history page a cut-off sentence is the one thing a
                  reader cannot work around. */}
              <SafeText value={snapshot.copy_fields[key]} className="whitespace-pre-wrap" />
            </dd>
          </div>
        ))}
      </dl>

      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
        <HashField label="Content hash" value={snapshot.content_hash} />
        <HashField label="Copy hash" value={snapshot.copy_hash} />
        <HashField label="Creative hash" value={snapshot.creative_hash} />
        <div className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-xs text-slate-500 dark:text-slate-400">
            Meta-reported start
          </dt>
          <dd className="text-sm">
            <SafeText value={formatUtcDateTime(snapshot.meta_delivery_start)} />
          </dd>
        </div>
        <div className="flex min-w-0 flex-col gap-0.5">
          <dt className="text-xs text-slate-500 dark:text-slate-400">
            Analysis copy hash
          </dt>
          {/*
            A stored reference, shown as stored. Nothing here reads or requests an
            analysis -- there is no analysis endpoint on this screen, and fetching one per
            snapshot would be a request storm.
          */}
          <dd className="text-sm">{renderHash(snapshot.analysis_copy_hash)}</dd>
        </div>
      </dl>

      {snapshot.media.length > 0 ? (
        <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {snapshot.media.map((asset) => (
            <li
              key={`${asset.provider}:${asset.provider_key}`}
              data-testid="snapshot-media"
              className="rounded-md border border-slate-200 p-3 dark:border-slate-800"
            >
              <MediaAvailability media={asset} />
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/**
 * A stored digest, displayed as stored.
 *
 * Split into the value and the field so a caller can supply its own `<dt>`/`<dd>`
 * pairing. An earlier version emitted both, and a caller that wrapped it in a `<dd>` of
 * its own produced `<dd>` nested inside `<dd>` -- invalid HTML that React rightly
 * complained about, and which a reader using a definition list would have got wrong too.
 */
function renderHash(value: string | null) {
  if (value === null) {
    // Deliberately no wording like "unchanged". A null hash means the field was never
    // computed for this observation, which is not the same statement as "identical".
    return <NullValue value={null} />;
  }
  return (
    <span className="ref text-slate-500 dark:text-slate-400" title={value}>
      {truncateIdentifier(value, 10)}
    </span>
  );
}

function HashField({ label, value }: { readonly label: string; readonly value: string | null }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-sm">{renderHash(value)}</dd>
    </div>
  );
}

function SnapshotSkeleton() {
  return (
    <div data-testid="snapshots-loading" role="status" aria-live="polite" className="flex flex-col gap-3">
      <p className="text-sm text-slate-600 dark:text-slate-400">Loading observations…</p>
      {/* Bars, never a fake observation with fake copy. */}
      {[0, 1].map((row) => (
        <div key={row} aria-hidden="true" className="h-24 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
      ))}
    </div>
  );
}

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "That ad's observations are not available on this server.";
    if (error.status >= 500) return "The server could not complete the request. Try again shortly.";
    return "The request was rejected, so the history could not be loaded.";
  }
  return "The server could not be reached. Check that the API is running.";
}

export { DEFAULT_SNAPSHOT_PAGING };
export default SnapshotHistory;
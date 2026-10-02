/**
 * The Ad Library screen: filters, search, sorting, pagination over `GET /ads`.
 *
 * ## State lives in the URL, and only in the URL
 *
 * There is no `useState` copy of the research state. The URL *is* the state, read once
 * on mount and written on every change, so a person can bookmark a filtered view, share
 * it, and get the same rows back after a refresh. A second copy in component state is a
 * second thing that can disagree with the first, and the disagreement shows up as
 * "the URL says IN but the grid shows GB".
 *
 * `history.pushState` for discrete commits -- a filter, a sort, a page -- so Back works
 * as a person expects. `replaceState` while the search box is settling, so typing does
 * not bury the previous page under twenty history entries.
 *
 * ## One request per distinct query
 *
 * The ads effect is keyed on the **serialised parameter string**, not on the state
 * object. Re-rendering, an unrelated state change, or a `popstate` that resolves to the
 * same query all produce the same string and therefore no request. Keyed on the object,
 * every render would be a fresh identity and the list would refetch forever.
 *
 * `/competitors` is fetched **once**, separately. It does not vary with the filters, and
 * refetching it on every keystroke would double the traffic to make no difference to the
 * result. If it fails the grid still renders, with Page names falling back to a compact
 * identifier -- which is the honest answer anyway, since an unresolvable UUID has no
 * name to show.
 *
 * ## Search is debounced, and never filters the page in the browser
 *
 * 300 ms, long enough to stop a sentence becoming seven requests and short enough that
 * the pause is not noticeable. The term goes to the server as `q`, which searches the
 * whole corpus. Filtering the rows already in memory would look instant and would be
 * quietly wrong: it would report "no matches" for anything outside the current page.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { buildDirectory, fetchAds, fetchCompetitors, type Directory } from "../../api/library";
import { ApiError } from "../../api/client";
import type { AdListOut, CompetitorListOut } from "../../types/api";
import { AdsGrid } from "./AdsGrid";
import { ExportButton } from "./ExportButton";
import { ActiveFilters, FilterBar } from "./FilterBar";
import {
  adsQueryFromParams,
  adsQueryToParams,
  adsRequestFromParamString,
  clearedQuery,
  hasActiveFilters,
  pluralRows,
  withFilter,
  withPage,
  withoutChip,
  type AdsQuery,
} from "./adsQuery";

/** Long enough that a sentence is not seven requests, short enough to feel immediate. */
const SEARCH_DEBOUNCE_MS = 300;

type AdsState =
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly status: number | null; readonly message: string }
  | { readonly kind: "ready"; readonly ads: AdListOut };

export function AdsLibrary() {
  const [query, setQuery] = useState<AdsQuery>(() => adsQueryFromParams(window.location.search));
  const [searchDraft, setSearchDraft] = useState(query.q);

  const [adsState, setAdsState] = useState<AdsState>({ kind: "loading" });
  // Both shapes are kept: `directory` is the flat lookup the grid joins against, and
  // `competitors` is the nested list the two selects need. Storing only the flat form and
  // rebuilding the nesting would mean storing the same information twice.
  const [directory, setDirectory] = useState<Directory>(() => new Map());
  const [competitors, setCompetitors] = useState<CompetitorListOut | null>(null);
  const [directoryFailed, setDirectoryFailed] = useState(false);

  // One committed history entry, so a burst of typing cannot push twenty.
  const lastPushed = useRef<string | null>(null);

  /* ============================================================
   * URL <-> state
   * ============================================================ */

  const paramString = useMemo(() => adsQueryToParams(query).toString(), [query]);

  const commit = useCallback((next: AdsQuery, replace = false) => {
    const params = adsQueryToParams(next).toString();
    const url = params === "" ? window.location.pathname : `${window.location.pathname}?${params}`;

    if (url !== `${window.location.pathname}${window.location.search}`) {
      if (replace) {
        window.history.replaceState(null, "", url);
      } else {
        window.history.pushState(null, "", url);
      }
    }
    lastPushed.current = url;
    setQuery(next);
    // The search box follows any external change to `q` -- a chip removal, Clear all, or
    // Back -- so the input never disagrees with what was actually requested.
    setSearchDraft(next.q);
  }, []);

  // Back and forward re-read the URL rather than trying to replay an undo stack.
  useEffect(() => {
    const onPopState = () => {
      const restored = adsQueryFromParams(window.location.search);
      lastPushed.current = `${window.location.pathname}${window.location.search}`;
      setQuery(restored);
      setSearchDraft(restored.q);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  /* ============================================================
   * Debounced search
   * ============================================================ */

  useEffect(() => {
    if (searchDraft === query.q) return;
    const timer = window.setTimeout(() => {
      // `replace`, because typing should not fill the history stack.
      commit(withFilter(query, { q: searchDraft }), true);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchDraft, query, commit]);

  /* ============================================================
   * Requests
   * ============================================================ */

  // `/competitors` once. Names do not vary with the filters.
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const list = await fetchCompetitors({ signal: controller.signal });
        if (controller.signal.aborted) return;
        setDirectory(buildDirectory(list));
        setCompetitors(list);
        setDirectoryFailed(false);
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error("Competitor directory request failed", error);
        setDirectoryFailed(true);
      }
    })();
    return () => controller.abort();
  }, []);

  // Ads, keyed **only** on the serialised query string.
  //
  // `query` is deliberately not a dependency and the request is derived from
  // `paramString` rather than from the state object. With `query` in the list, a
  // `popstate` that resolves to a URL already on screen hands over a new object with
  // identical values, React sees a changed dependency, and the list refetches for
  // nothing. Deriving the request from the same string the effect depends on also makes
  // it impossible for what was requested and what the URL shows to disagree.
  useEffect(() => {
    const controller = new AbortController();
    setAdsState({ kind: "loading" });
    (async () => {
      try {
        const ads = await fetchAds(adsRequestFromParamString(paramString), {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setAdsState({ kind: "ready", ads });
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError) {
          console.error("Ads request failed", error.status, error.detail);
          setAdsState({ kind: "error", status: error.status, message: describe(error.status) });
          return;
        }
        console.error("Ads request failed", error);
        setAdsState({ kind: "error", status: null, message: describe(null) });
      }
    })();
    return () => controller.abort();
  }, [paramString]);

  /* ============================================================
   * Actions
   * ============================================================ */

  const onFilterChange = useCallback(
    (patch: Partial<AdsQuery>) => commit(withFilter(query, patch)),
    [commit, query],
  );
  const onSearch = useCallback((value: string) => setSearchDraft(value), []);
  const onRemove = useCallback(
    (key: keyof AdsQuery) => commit(withoutChip(query, key)),
    [commit, query],
  );
  const onClearAll = useCallback(() => commit(clearedQuery()), [commit]);

  /* ============================================================
   * Render
   * ============================================================ */

  const busy = adsState.kind === "loading";

  return (
    <section aria-labelledby="ads-library-heading" className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h2 id="ads-library-heading" className="text-xl font-semibold tracking-tight">
          Ad Library
        </h2>
        <p className="max-w-prose text-sm text-slate-600 dark:text-slate-400">
          Ads this product has observed, as published by Meta. Every row is one ad; the
          status inside it belongs to one Page and country, never to the ad as a whole.
        </p>
      </header>

      <FilterBar
        query={query}
        competitors={competitors ?? EMPTY_COMPETITORS}
        onChange={onFilterChange}
        onSearch={onSearch}
        searchDraft={searchDraft}
        disabled={busy}
      />

      <ActiveFilters query={query} onRemove={onRemove} onClearAll={onClearAll} />

      {directoryFailed ? (
        <p data-testid="directory-warning" className="text-xs text-amber-800 dark:text-amber-300">
          Page names could not be loaded, so Pages are shown by identifier.
        </p>
      ) : null}

      {adsState.kind === "loading" ? <LoadingState /> : null}
      {adsState.kind === "error" ? (
        <ErrorState status={adsState.status} message={adsState.message} />
      ) : null}
      {adsState.kind === "ready" ? (
        <ReadyState
          ads={adsState.ads}
          query={query}
          directory={directory}
          filtered={hasActiveFilters(query)}
          onPage={(page) => commit(withPage(query, page))}
        />
      ) : null}

      {/*
        Export sits with the results rather than above them: it exports *these* results, so
        it belongs where the result count is. It is offered even when the list is empty --
        an empty filtered result is still an export a person may want, and hiding the
        control would make its absence ambiguous.
      */}
      <ExportButton query={query} />
    </section>
  );
}

const EMPTY_COMPETITORS: CompetitorListOut = { items: [] };

function ReadyState({
  ads,
  query,
  directory,
  filtered,
  onPage,
}: {
  ads: AdListOut;
  query: AdsQuery;
  directory: Directory;
  filtered: boolean;
  onPage: (page: number) => void;
}) {
  const showing = ads.items.length;
  const total = ads.total;
  const lastPage = Math.max(1, Math.ceil(total / Math.max(1, ads.page_size)));
  const onFirst = query.page <= 1;
  const onLast = query.page >= lastPage;

  return (
    <>
      <p data-testid="result-count" className="text-sm text-slate-600 dark:text-slate-400">
        {showing === 0 ? (
          <>No ads match</>
        ) : (
          <>
            Showing <span className="font-medium tabular-nums">{showing}</span> of{" "}
            <span className="font-medium tabular-nums">{total}</span> observed{" "}
            {total === 1 ? "ad" : "ads"}
          </>
        )}
      </p>

      {showing === 0 ? (
        <EmptyState filtered={filtered} />
      ) : (
        <AdsGrid ads={ads} directory={directory} />
      )}

      <nav
        aria-label="Pagination"
        data-testid="pagination"
        className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-3 dark:border-slate-800"
      >
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Page <span className="tabular-nums">{query.page}</span> of{" "}
          <span className="tabular-nums">{lastPage}</span> · {pluralRows(total)} found
        </p>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onPage(query.page - 1)}
            disabled={onFirst}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:border-slate-700 dark:focus-visible:outline-sky-400"
          >
            Previous
          </button>
          <button
            type="button"
            onClick={() => onPage(query.page + 1)}
            disabled={onLast}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:border-slate-700 dark:focus-visible:outline-sky-400"
          >
            Next
          </button>
        </div>
      </nav>
    </>
  );
}

function LoadingState() {
  return (
    <div data-testid="loading-state" className="flex flex-col gap-2" role="status" aria-live="polite">
      <p className="text-sm text-slate-600 dark:text-slate-400">Loading observed ads…</p>
      {/* Placeholder bars, not placeholder *data*. No fake ad, no fake competitor, no
          fake count -- a skeleton that looks like a result would be one. */}
      {[0, 1, 2].map((row) => (
        <div
          key={row}
          aria-hidden="true"
          className="h-14 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800"
        />
      ))}
    </div>
  );
}

function EmptyState({ filtered }: { filtered: boolean }) {
  return (
    <div
      data-testid="empty-state"
      className="rounded-lg border border-dashed border-slate-300 p-6 dark:border-slate-700"
    >
      <p className="font-medium">
        {filtered ? "No ads match these filters" : "No observed ads are available"}
      </p>
      <p className="mt-1 max-w-prose text-sm text-slate-600 dark:text-slate-400">
        {filtered ? (
          <>
            The request was answered and there were no matches. Widen or remove a filter
            above. Note that this is different from an ad having stopped running: an ad
            that stops is one that was seen and then was not, and it stays in this list.
          </>
        ) : (
          <>
            Nothing has been collected yet, so there is nothing to show. This is different
            from an ad having stopped running: an ad that stops is one that was seen and
            then was not, and it stays in this list.
          </>
        )}
      </p>
    </div>
  );
}

function ErrorState({ status, message }: { status: number | null; message: string }) {
  return (
    <div
      data-testid="error-state"
      role="alert"
      className="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-700 dark:bg-amber-500/10"
    >
      <p className="font-medium text-amber-900 dark:text-amber-200">Could not load observed ads</p>
      <p className="mt-1 text-sm text-amber-900 dark:text-amber-200">{message}</p>
      {status !== null ? (
        <p className="mt-1 text-xs text-amber-800 dark:text-amber-300">
          HTTP status <span className="tabular-nums">{status}</span>
        </p>
      ) : null}
    </div>
  );
}

/**
 * A sentence a reader can act on, and nothing that could leak a server internal.
 * Deliberately keyed on status only -- the response body is not shown.
 */
function describe(status: number | null): string {
  if (status === 400) return "The filters were rejected. Clear one and try again.";
  if (status === 404) return "The ads endpoint is not available on this server.";
  if (status === 413) return "That request was too large for the server to answer.";
  if (status !== null && status >= 500) {
    return "The server could not complete the request. Try again shortly.";
  }
  if (status !== null && status >= 400) {
    return "The request was rejected, so no ads could be loaded.";
  }
  return "The server could not be reached. Check that the API is running.";
}

export default AdsLibrary;
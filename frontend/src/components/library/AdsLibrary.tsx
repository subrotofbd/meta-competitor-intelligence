/**
 * The Ad Library screen: the first thing in this product that shows real data.
 *
 * ## State is a union, not a set of booleans
 *
 * `loading` / `ready` / `error` are one discriminated value, so the combinations a
 * boolean soup allows -- loading *and* errored, ready with no items *and* an error --
 * cannot be represented at all. The three states are genuinely exclusive and the type
 * says so.
 *
 * ## What an error shows, and what it deliberately does not
 *
 * The reader gets the HTTP status and a sentence they can act on. They do **not** get
 * the response body: `ApiError.detail` can carry a validation problem list with
 * internal field names, and a stack trace or a raw driver message on a research screen
 * is both noise and a small disclosure. The detail goes to `console.error` where a
 * developer can reach it and a competitor cannot.
 *
 * ## No retry button
 *
 * Not because retrying is wrong, but because a button with no behaviour is worse than
 * no button, and "reload the page" is a thing people already know how to do. A retry
 * belongs here when there is something to configure about it.
 *
 * ## Two requests, once
 *
 * `/ads` and `/competitors`, fired together because neither depends on the other, and
 * both guarded by an abort on unmount so a response that arrives after the screen is
 * gone cannot set state on a dead component. A grid that fires per row is exactly the
 * fan-out this avoids.
 */

import { useCallback, useEffect, useState } from "react";

import { buildDirectory, fetchAds, fetchCompetitors, PAGE_SIZE } from "../../api/library";
import { ApiError } from "../../api/client";
import type { AdListOut } from "../../types/api";
import { AdsGrid } from "./AdsGrid";

type LoadState =
  | { readonly kind: "loading" }
  | { readonly kind: "error"; readonly status: number | null; readonly message: string }
  | {
      readonly kind: "ready";
      readonly ads: AdListOut;
      readonly directory: ReturnType<typeof buildDirectory>;
    };

export function AdsLibrary() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const load = useCallback(async (signal: AbortSignal) => {
    setState({ kind: "loading" });
    try {
      // Neither depends on the other, so they go together.
      const [ads, competitors] = await Promise.all([
        fetchAds({ signal }),
        fetchCompetitors({ signal }),
      ]);
      if (signal.aborted) return;
      setState({ kind: "ready", ads, directory: buildDirectory(competitors) });
    } catch (error) {
      // An abort is a deliberate cancellation, not a failure to report.
      if (signal.aborted) return;

      if (error instanceof ApiError) {
        console.error("Ad Library request failed", error.status, error.detail);
        setState({
          kind: "error",
          status: error.status,
          message: describe(error.status),
        });
        return;
      }

      // A network failure never became an ApiError. The message is still not shown:
      // it can be a browser-level string with a URL in it.
      console.error("Ad Library request failed", error);
      setState({ kind: "error", status: null, message: describe(null) });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

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

      {state.kind === "loading" ? <LoadingState /> : null}
      {state.kind === "error" ? <ErrorState status={state.status} message={state.message} /> : null}
      {state.kind === "ready" ? <ReadyState state={state} /> : null}
    </section>
  );
}

function ReadyState({
  state,
}: {
  state: { ads: AdListOut; directory: ReturnType<typeof buildDirectory> };
}) {
  const { ads, directory } = state;
  const showing = ads.items.length;

  return (
    <>
      {/* The count is a count of observations, phrased so it cannot be read as
          performance. `-- of N`, and never anything about how well anything did. */}
      <p data-testid="result-count" className="text-sm text-slate-600 dark:text-slate-400">
        {showing === 0 ? (
          <>No ads to show</>
        ) : (
          <>
            Showing <span className="font-medium tabular-nums">{showing}</span> of{" "}
            <span className="font-medium tabular-nums">{ads.total}</span> observed ads
            {ads.page_size !== PAGE_SIZE ? (
              <> (page size {ads.page_size})</>
            ) : null}
          </>
        )}
      </p>

      {showing === 0 ? <EmptyState /> : <AdsGrid ads={ads} directory={directory} />}
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

function EmptyState() {
  return (
    <div
      data-testid="empty-state"
      className="rounded-lg border border-dashed border-slate-300 p-6 dark:border-slate-700"
    >
      <p className="font-medium">No observed ads are available</p>
      <p className="mt-1 max-w-prose text-sm text-slate-600 dark:text-slate-400">
        Nothing has been collected yet, so there is nothing to show. This is different
        from an ad having stopped running: an ad that stops is one that was seen and
        then was not, and it stays in this list.
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
      <p className="font-medium text-amber-900 dark:text-amber-200">
        Could not load observed ads
      </p>
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
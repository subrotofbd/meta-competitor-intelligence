/**
 * CSV export.
 *
 * ## One source of truth for "what is filtered"
 *
 * The URL comes from `adsCsvUrl(query)`, which reads the same
 * `adsQueryToFilterParams` the list request and the list URL read. There is no second
 * filter builder anywhere. That matters more here than anywhere else in the app: a bug
 * that drops a filter from the list still renders *something*, but a bug that drops one
 * from the export produces a plausible-looking file containing the wrong rows, and nothing
 * about it looks broken.
 *
 * ## Why the body is read in the browser
 *
 * The endpoint is a streamed attachment, and the obvious approach -- an `<a href>` -- would
 * let the browser stream it straight to disk with nothing buffered here. That is the
 * better mechanism, and it is unusable: a 400, a 413 or a 500 would either download a JSON
 * error body as `ads.csv` or navigate away, and the user would be told nothing. Reporting
 * that a download failed requires seeing the status, so the response is read once, here,
 * and only after it is known to have succeeded. The file never passes through React state
 * and is never parsed.
 *
 * ## The row ceiling is a real limit, not a failure to paper over
 *
 * Above `MAX_EXPORT_ROWS` the backend answers 413 **before** it starts streaming, so this
 * receives a status rather than a truncated file. That is said plainly. Nothing is
 * silently truncated and nothing claims a download that did not happen.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { adsCsvUrl, fetchAdsCsv } from "../../api/library";
import type { AdsQuery } from "./adsQuery";

/** Used only when the server sends no usable filename. Matches the server's own. */
const FALLBACK_FILENAME = "ads.csv";

type Phase =
  | { readonly kind: "idle" }
  | { readonly kind: "exporting" }
  | { readonly kind: "error"; readonly message: string };

/**
 * The server's filename, if it is safe to use.
 *
 * `Content-Disposition` is attacker-influenced in the general case, so the value is taken
 * as text and reduced to a bare filename: any path component is dropped, and anything that
 * is not a plausible name is refused in favour of the fallback. A download name is a thing
 * a person's filesystem will act on.
 */
export function filenameFromDisposition(header: string | null): string {
  if (!header) return FALLBACK_FILENAME;

  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  if (!match?.[1]) return FALLBACK_FILENAME;

  let name = match[1].trim();
  try {
    name = decodeURIComponent(name);
  } catch {
    // A malformed escape means the header could not be interpreted, so the name is
    // refused rather than taken from the mangled remainder. Falling back still downloads
    // the correct bytes under a name we chose, which is better than a download called
    // `%E0%A4%A.csv`.
    return FALLBACK_FILENAME;
  }
  name = name.split(/[\\/]/).pop() ?? "";
  // eslint-disable-next-line no-control-regex
  name = name.replace(/[\u0000-\u001f<>:"|?*]/g, "").trim();

  return name === "" || name === "." || name === ".." ? FALLBACK_FILENAME : name;
}

export function ExportButton({ query }: { readonly query: AdsQuery }) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  // A ref, not state: the double-click guard has to hold *within* a single event, before
  // React has re-rendered and disabled the button. Two rapid clicks are two events, and
  // two exports is exactly the failure this prevents.
  const locked = useRef(false);

  // A download in flight must not resolve into state after the screen is gone.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const onExport = useCallback(async () => {
    if (locked.current) return;
    locked.current = true;
    setPhase({ kind: "exporting" });

    let objectUrl: string | null = null;
    try {
      const response = await fetchAdsCsv(adsCsvUrl(query));

      if (!response.ok) {
        if (mounted.current) setPhase({ kind: "error", message: describe(response.status) });
        return;
      }

      const filename = filenameFromDisposition(response.headers.get("Content-Disposition"));
      const blob = await response.blob();
      objectUrl = URL.createObjectURL(blob);

      // A real anchor click, so the browser's own download machinery does the work and the
      // bytes go straight to disk rather than through React state.
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = filename;
      anchor.rel = "noopener";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();

      // Nothing is claimed on success. The browser already shows the download; a
      // "success" line here would be a second, weaker version of the same fact.
      if (mounted.current) setPhase({ kind: "idle" });
    } catch (error) {
      console.error("CSV export failed", error);
      if (mounted.current) {
        setPhase({
          kind: "error",
          message: "The export could not be downloaded. Check that the API is running.",
        });
      }
    } finally {
      // Released once the browser has taken the blob. Revoking earlier cancels the
      // download in some browsers.
      if (objectUrl) {
        // Captured in a const: the callback closes over the binding, whose declared type is
        // `string | null`, and narrowing does not carry into a closure.
        const url = objectUrl;
        window.setTimeout(() => URL.revokeObjectURL(url), 0);
      }
      locked.current = false;
    }
  }, [query]);

  const exporting = phase.kind === "exporting";

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={onExport}
        disabled={exporting}
        aria-busy={exporting}
        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium transition-colors hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800 dark:focus-visible:outline-sky-400"
      >
        {exporting ? "Exporting…" : "Export CSV"}
      </button>

      {/*
        One polite live region for the failure message. `role="status"` rather than
        `alert`, so a failed export is announced without interrupting the reader.
      */}
      <p
        role="status"
        aria-live="polite"
        data-testid="export-status"
        className={`min-h-4 text-xs ${
          phase.kind === "error" ? "text-amber-800 dark:text-amber-300" : "text-slate-500 dark:text-slate-400"
        }`}
      >
        {phase.kind === "error" ? phase.message : ""}
      </p>
    </div>
  );
}

/** A sentence a reader can act on, keyed on status only. The body is never shown. */
function describe(status: number): string {
  if (status === 400) return "The export was rejected. Narrow or clear a filter and try again.";
  if (status === 413) {
    // The export is refused whole rather than truncated, so the remedy is a narrower
    // filter -- not a partial file, and not a silent truncation.
    return "This export is larger than the server allows, so nothing was exported. Narrow the filters to export fewer ads.";
  }
  if (status >= 500) return "The server could not complete the export. Try again shortly.";
  return "The export request was rejected, so nothing was exported.";
}

export default ExportButton;
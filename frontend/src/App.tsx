import { useCallback, useEffect, useState } from "react";

import { AdDetail } from "./components/library/AdDetail";
import { AdsLibrary } from "./components/library/AdsLibrary";
import { useRoute } from "./router";

/**
 * The shell: header, theme toggle, the one screen, footer.
 *
 * The chrome lives here; the product lives in `components/library`. Still no filters,
 * no detail page, no snapshots UI, no AI panel, no media, no CSV -- each of those is its
 * own step, and none of them is stubbed out with a "coming soon" that would imply an
 * answer this product cannot give.
 *
 * ## The shell makes no API request of its own
 *
 * Mounting the header, the theme toggle and the footer is not consent to call the
 * backend. A component that fires a fetch in an effect "just to see" makes every page
 * load depend on the API being up, and turns a frontend bug into an outage report.
 *
 * The first request belongs to the first screen that needs data, and that screen is
 * `AdsLibrary` -- which makes exactly two calls, `GET /ads` and `GET /competitors`. The
 * shell itself makes none.
 *
 * ## Two routes, no router library
 *
 * `resolveRoute` reads `window.location.pathname`: `/` is the library, `/ads/{id}` is
 * the record. Two shapes do not justify a dependency and a provider tree, and the
 * browser already owns history. A detail link is a real `href`, so it can be copied
 * and shared -- which is the point of a research product.
 */

type Theme = "light" | "dark";

const STORAGE_KEY = "brandset.theme";

/** The user's stored choice, falling back to the OS preference. */
function initialTheme(): Theme {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme(theme: Theme): void {
  // On `<html>`, not on a wrapper: `color-scheme` and the page background both need
  // it above the app's own elements, or the edges stay light behind dark content.
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    applyTheme(theme);
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }, []);

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="page-shell flex items-center justify-between gap-4 py-4">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold tracking-tight sm:text-xl">
              Brandset
            </h1>
            <p className="truncate text-sm text-slate-600 dark:text-slate-400">
              Meta competitor intelligence — public Ad Library data only
            </p>
          </div>

          <button
            type="button"
            onClick={toggleTheme}
            aria-pressed={theme === "dark"}
            className="shrink-0 rounded-md border border-slate-300 px-3 py-2 text-sm font-medium transition-colors hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
        </div>
      </header>

      <main className="page-shell flex-1 py-8">
        <Routes />
      </main>

      <footer className="border-t border-slate-200 dark:border-slate-800">
        <div className="page-shell py-4 text-xs text-slate-500 dark:text-slate-500">
          Spend, leads, ROAS and reach for commercial ads are not public. This product
          does not estimate or display them.
        </div>
      </footer>
    </div>
  );
}

/**
 * The whole of the routing: two cases.
 *
 * A malformed id renders the not-found state **without a request**. Fetching
 * `/ads/not-a-uuid` would turn a typo into a 422 and a wasted round trip.
 */
function Routes() {
  const route = useRoute();

  if (route.kind === "ad") return <AdDetail adId={route.adId} />;
  if (route.kind === "malformed") return <MalformedRoute requested={route.requested} />;
  return <AdsLibrary />;
}

function MalformedRoute({ requested }: { readonly requested: string }) {
  return (
    <div data-testid="detail-malformed" className="flex flex-col gap-3">
      <h2 className="text-xl font-semibold tracking-tight">Ad not found</h2>
      <p className="max-w-prose text-sm text-slate-600 dark:text-slate-400">
        <span className="ref break-all">{requested}</span> is not an ad id, so there is
        nothing to look up. An ad id is a UUID.
      </p>
      <a
        href="/"
        className="w-fit rounded-md text-sm text-slate-600 underline underline-offset-4 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:text-slate-400 dark:hover:text-slate-100 dark:focus-visible:outline-sky-400"
      >
        ← Back to Ad Library
      </a>
    </div>
  );
}

export default App;
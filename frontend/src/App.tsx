import { useCallback, useEffect, useState } from "react";

import { BASE_PATH, apiUrl } from "./api/client";

/**
 * The shell. Nothing is built yet, on purpose.
 *
 * S3.3 step 4 is the foundation only: React mounts, Tailwind's tokens resolve, the
 * theme can be chosen by the user, and the layout responds. No ad grid, no filters,
 * no detail page, no AI panel, no media, no CSV -- each of those is its own step.
 *
 * ## The most important line in this file
 *
 * **No API request is made on load.** Mounting the shell is not consent to call the
 * backend. A component that fires a fetch in an effect "just to see" makes every
 * page load depend on the API being up, and turns a frontend bug into an outage
 * report. The first request belongs to the first screen that needs data.
 *
 * `apiUrl` is imported and called, because building a URL is not a request -- that
 * proves the client module loads and exports what the app will use, with no network.
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
        <section
          aria-labelledby="shell-status"
          className="rounded-lg border border-dashed border-slate-300 p-6 dark:border-slate-700"
        >
          <h2 id="shell-status" className="text-base font-semibold">
            S3.3 step 4 — frontend foundation
          </h2>
          <p className="mt-2 max-w-prose text-sm text-slate-600 dark:text-slate-400">
            The foundation is in place and deliberately empty. Ads, filters, ad detail,
            snapshot history, copy analysis, media, and CSV export each arrive in their
            own step.
          </p>

          {/* Not a claim about the backend: no request was made to find this out. */}
          <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div className="flex justify-between gap-4 border-b border-slate-200 pb-2 dark:border-slate-800">
              <dt className="text-slate-600 dark:text-slate-400">Theme</dt>
              <dd className="font-medium">{theme}</dd>
            </div>
            <div className="flex justify-between gap-4 border-b border-slate-200 pb-2 dark:border-slate-800">
              <dt className="text-slate-600 dark:text-slate-400">API base path</dt>
              {/* Rendering the real constant, so this cannot drift from the client. */}
              <dd className="font-mono text-xs">{BASE_PATH}</dd>
            </div>
            <div className="flex justify-between gap-4 border-b border-slate-200 pb-2 dark:border-slate-800">
              <dt className="text-slate-600 dark:text-slate-400">Example URL</dt>
              <dd className="truncate font-mono text-xs">
                {apiUrl("/ads", { page: 1, page_size: 25, competitor_id: null })}
              </dd>
            </div>
            <div className="flex justify-between gap-4 border-b border-slate-200 pb-2 dark:border-slate-800">
              <dt className="text-slate-600 dark:text-slate-400">Requests on load</dt>
              <dd className="font-medium">0</dd>
            </div>
          </dl>
        </section>
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

export default App;
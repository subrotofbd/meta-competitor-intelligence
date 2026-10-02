/**
 * Routing, with no routing library.
 *
 * ## Why this is hand-rolled
 *
 * There are two screens. `react-router` would add a dependency, a provider tree and a
 * `<Routes>` abstraction to answer "is the pathname `/` or `/ads/{id}`" -- and it would
 * own the history in a way that has to be reconciled with the URL-state work in step 7.
 * `window.location` already answers the question, and the browser already owns history.
 *
 * ## Every link is a real link
 *
 * Routes are expressed as genuine `href` values, so a person can copy an ad's URL,
 * middle-click it, or open it in a new tab, and it works. JavaScript intercepts the click
 * only to avoid a full reload. A route that exists only in component state is a URL a
 * person cannot share, and this product's whole point is reproducible research.
 *
 * ## Navigation and `popstate` are the same event
 *
 * `navigate` pushes the URL and then dispatches `popstate`, so there is one code path for
 * "the URL changed" whether it came from a click or from the Back button. Two mechanisms
 * would mean two places where the screen and the URL can disagree.
 */

import { useEffect, useState } from "react";

export type Route =
  | { readonly kind: "library" }
  | { readonly kind: "ad"; readonly adId: string }
  /** A path shaped like a detail route whose id is not a UUID. Never fetched. */
  | { readonly kind: "malformed"; readonly requested: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Work out the screen from a pathname.
 *
 * A malformed id resolves to `malformed` rather than to `ad`, so the screen can show a
 * not-found state **without issuing a request**. Fetching `/ads/not-a-uuid` would turn a
 * typo into a 422 and a wasted round trip, and the backend would rightly refuse it.
 */
export function resolveRoute(pathname: string): Route {
  const match = /^\/ads\/([^/?#]+)\/?$/.exec(pathname);
  if (!match) return { kind: "library" };

  const requested = decodeURIComponent(match[1] ?? "");
  if (!UUID.test(requested)) return { kind: "malformed", requested };
  return { kind: "ad", adId: requested.toLowerCase() };
}

/** The canonical URL for one ad. */
export function adPath(adId: string): string {
  return `/ads/${adId}`;
}

/**
 * Change the route without a full reload.
 *
 * Pushes, then dispatches `popstate` so the same listener handles this and the Back
 * button. `push` is the default; step 7's search box uses its own `replaceState` for
 * settling keystrokes and does not come through here.
 */
export function navigate(url: string, options: { replace?: boolean } = {}): void {
  if (options.replace) {
    window.history.replaceState(null, "", url);
  } else {
    window.history.pushState(null, "", url);
  }
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/** The current route, re-read whenever history changes. */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => resolveRoute(window.location.pathname));

  useEffect(() => {
    const onChange = () => setRoute(resolveRoute(window.location.pathname));
    window.addEventListener("popstate", onChange);
    return () => window.removeEventListener("popstate", onChange);
  }, []);

  return route;
}

/**
 * Intercept a click on a real link so it stays in the app.
 *
 * Modified clicks and non-primary buttons are left alone: "open in new tab" must keep
 * working, and swallowing it would make the link a lie.
 */
export function routeLinkProps(href: string) {
  return {
    href,
    onClick: (event: React.MouseEvent<HTMLAnchorElement>) => {
      if (event.defaultPrevented) return;
      if (event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      navigate(href);
    },
  };
}
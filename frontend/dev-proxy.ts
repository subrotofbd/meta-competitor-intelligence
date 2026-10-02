/**
 * The development API proxy's contract, kept out of `vite.config.ts` on purpose.
 *
 * ## Why this is its own file
 *
 * `vite.config.ts` imports the Vite plugins, which pull in esbuild. esbuild refuses to
 * load inside jsdom -- its `new TextEncoder().encode("") instanceof Uint8Array`
 * realm check fails there -- so a test that imports the Vite config dies before it
 * runs, with an error about a `TextEncoder` that says nothing about proxies.
 *
 * These two values are the whole proxy contract, they depend on nothing, and they are
 * the one part of the dev setup that cannot be verified by looking at a build. Keeping
 * them here makes them directly testable. `vite.config.ts` imports from this file, so
 * there is still exactly one definition and the test asserts against the real thing
 * rather than a copy of it.
 */

/** The backend's origin in development. Never reachable from app code by design. */
export const API_PROXY_TARGET = "http://localhost:8000";

/** The prefix the client speaks. Mirrors `api/client.ts`'s `BASE_PATH`. */
export const API_PREFIX = "/api";

/**
 * Strip our `/api` prefix so the backend receives the path it actually routes.
 *
 * The backend mounts its routers at the **root** (`app.include_router(ads_router)`,
 * with no `prefix=`), so the real endpoints are `GET /ads` and `GET /competitors`.
 * Without this rewrite, `/api/ads` reaches the backend as `/api/ads` and 404s --
 * and a 404 on every endpoint is indistinguishable, from the browser, from the API
 * being down. That is the specific failure this prevents.
 *
 * The pattern is anchored. A path that merely *contains* `/api` is a different route
 * and must survive untouched.
 */
export function rewriteApiPath(path: string): string {
  return path.replace(/^\/api/, "");
}
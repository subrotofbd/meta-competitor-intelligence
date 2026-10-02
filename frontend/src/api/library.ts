/**
 * The Ads Library's two endpoints, and the name lookup the grid needs.
 *
 * ## Only two requests, ever
 *
 * `GET /ads` and `GET /competitors`. Nothing else. No detail fetches, no media, no
 * discovery probing. A grid that quietly fans out to `/ads/{id}` per row would issue
 * one request per row to fill columns the detail screen owns, which is both slower and
 * a step backwards from the detail screen being a deliberate destination.
 *
 * `request()` prefixes `/api` itself, so nothing here contains an origin, a host, or a
 * port. A hardcoded `http://localhost:8000` here would bypass the dev proxy, break in
 * production, and turn every call into a cross-origin request the backend has no CORS
 * support for.
 */

import { request } from "./client";
import { truncateIdentifier } from "../components/provenance/format";
import type { AdDetailOut, AdListOut, CompetitorListOut } from "../types/api";

// The default and maximum page sizes live in `components/library/adsQuery.ts` as
// `DEFAULT_PAGE_SIZE` and `MAX_PAGE_SIZE`. A second copy of "25" here would be two
// constants both claiming to be the backend's `DEFAULT_PAGE_SIZE`, and they would
// eventually disagree.

export type FetchOptions = { readonly signal?: AbortSignal };

/**
 * One page of ads.
 *
 * `query` is passed through as-is, and the caller is responsible for it being already
 * validated -- `components/library/adsQuery.ts` is what turns URL input into an
 * allowlisted parameter set. Nothing here re-checks it, because a second validation
 * layer is a second thing to keep in step and would only ever disagree with the first.
 *
 * Defaults are omitted rather than sent as empty values, so "no country filter" is the
 * absence of `country` and not `country=`.
 */
export function fetchAds(
  query: Readonly<Record<string, string | number>> = {},
  options: FetchOptions = {},
) {
  return request<AdListOut>("/ads", {
    query,
    ...(options.signal ? { signal: options.signal } : {}),
  });
}

/**
 * One ad in full: identity, copy, contexts, media and any stored analysis.
 *
 * The only request the Ad Detail screen makes. No list, no directory, no media URL -- the
 * media references come back as references and are never fetched.
 */
export function fetchAd(adId: string, options: FetchOptions = {}) {
  return request<AdDetailOut>(`/ads/${encodeURIComponent(adId)}`, {
    ...(options.signal ? { signal: options.signal } : {}),
  });
}

export function fetchCompetitors(options: FetchOptions = {}) {
  return request<CompetitorListOut>("/competitors", {
    ...(options.signal ? { signal: options.signal } : {}),
  });
}

/* ============================================================
 * Name resolution
 * ============================================================ */

/**
 * What `/ads` cannot tell us about a context's Page.
 *
 * `ContextOut` carries `facebook_page_id` and `country` and nothing else -- no name,
 * no competitor. `GET /competitors` is where those names live, so the grid joins the
 * two in memory rather than asking the backend to denormalise names into `/ads`.
 */
export type DirectoryEntry = {
  /** Provider-reported. `null` when the provider reported no name -- never `""`. */
  readonly pageName: string | null;
  /** The operator's competitor name. `null` is not possible for a listed page. */
  readonly competitorName: string | null;
  /** The provider's own identity for the Page, e.g. `mock-page-0001`. */
  readonly pageId: string | null;
  readonly country: string | null;
  readonly isTracked: boolean | null;
};

/** Keyed by `FacebookPageOut.id` -- the internal UUID that `ContextOut` references. */
export type Directory = ReadonlyMap<string, DirectoryEntry>;

/**
 * Flatten the nested competitor tree into a lookup.
 *
 * Both `page.id` (internal UUID) and `page.page_id` (provider identity) are indexed,
 * because a context references the internal UUID and a human reading the grid cares
 * about the provider identity. Keying on both costs nothing and means a caller that
 * holds either one still resolves.
 *
 * A later entry for the same key overwrites an earlier one rather than throwing:
 * `FacebookPageOut.id` is the primary key, so a duplicate can only arrive from a
 * malformed response, and refusing to render the grid over it is worse than rendering
 * the last value.
 */
export function buildDirectory(list: CompetitorListOut): Directory {
  const byId = new Map<string, DirectoryEntry>();

  for (const competitor of list.items) {
    for (const page of competitor.pages) {
      const entry: DirectoryEntry = {
        pageName: page.name,
        competitorName: competitor.name,
        pageId: page.page_id,
        country: page.country,
        isTracked: page.is_tracked,
      };
      byId.set(page.id, entry);
      if (page.page_id !== page.id) byId.set(page.page_id, entry);
    }
  }

  return byId;
}

/** Resolve one Page, or `undefined` when `/competitors` does not list it. */
export function lookupPage(directory: Directory, id: string): DirectoryEntry | undefined {
  return directory.get(id);
}

/**
 * A compact rendering of a UUID we could not resolve to a name.
 *
 * The requirement is to show *something* rather than invent a name, so this shows the
 * identifier itself and nothing else. `6825…398f` keeps both ends, so the same Page can
 * be recognised across rows even when no name is known for it.
 */
export function compactUuid(id: string): string {
  return truncateIdentifier(id, 4);
}
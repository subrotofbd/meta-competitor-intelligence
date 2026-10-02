/**
 * Paging state for the snapshot history, in the URL and nowhere else.
 *
 * ## Why it is separate from the snapshot UI
 *
 * `page` and `page_size` arrive from a URL a person can edit, and both end up in a
 * request. Parsing, clamping and serialising are pure functions so that boundary is
 * testable with no component and no request -- the same reasoning as `adsQuery.ts`.
 *
 * ## Why the key is prefixed
 *
 * The snapshot parameters live under `snapshot_page` and `snapshot_page_size` rather than
 * bare `page`. Ad Detail and the Ads Library are different screens that can both be
 * described by a URL, and reusing the bare names would make "which page?" ambiguous the
 * moment a link to one is pasted while the other is on screen.
 *
 * Nothing here touches the Ads Library's own parameters (`q`, `country`, `sort`, ...), so
 * navigating back and forward cannot disturb the library's filter state.
 */

export const DEFAULT_SNAPSHOT_PAGE_SIZE = 25;
export const SNAPSHOT_PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
export const MAX_SNAPSHOT_PAGE_SIZE = 100;

export type SnapshotPaging = {
  readonly page: number;
  readonly pageSize: number;
};

export const DEFAULT_SNAPSHOT_PAGING: SnapshotPaging = {
  page: 1,
  pageSize: DEFAULT_SNAPSHOT_PAGE_SIZE,
};

function integer(raw: string | null, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

export function snapshotPagingFromParams(params: URLSearchParams | string): SnapshotPaging {
  const search =
    typeof params === "string"
      ? new URLSearchParams(params.startsWith("?") ? params.slice(1) : params)
      : params;
  return {
    page: integer(search.get("snapshot_page"), 1, 10_000, 1),
    pageSize: integer(
      search.get("snapshot_page_size"),
      1,
      MAX_SNAPSHOT_PAGE_SIZE,
      DEFAULT_SNAPSHOT_PAGE_SIZE,
    ),
  };
}

/** Only non-default values, so the common case adds nothing to the URL at all. */
export function snapshotPagingToParams(paging: SnapshotPaging): URLSearchParams {
  const params = new URLSearchParams();
  if (paging.page > 1) params.set("snapshot_page", String(paging.page));
  if (paging.pageSize !== DEFAULT_SNAPSHOT_PAGE_SIZE) {
    params.set("snapshot_page_size", String(paging.pageSize));
  }
  return params;
}
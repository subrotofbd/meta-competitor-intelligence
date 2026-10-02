/**
 * The Ads Library's research state, as one plain object, and its URL form.
 *
 * ## Why this file exists separately from the UI
 *
 * Every filter is a value that arrives from a URL a person can edit by hand, and every
 * one of them ends up in a query string the backend validates or rejects. Keeping the
 * parse, the validation and the serialisation in pure functions means that boundary can
 * be tested directly, without a DOM and without a request, and it keeps `FilterBar` a
 * component that renders controls rather than a place where trust decisions hide.
 *
 * So: **nothing is forwarded on faith.** A hand-typed `?sort=; DROP TABLE` is dropped
 * back to the default rather than sent, because the alternative is a UI that turns a
 * typo into a 400 with no explanation.
 *
 * ## The provider filter is an exact-match text box
 *
 * `GET /ads` supports `provider`, but the approved research filter list does not include
 * it, and there is no endpoint that enumerates provider values -- so there is nothing
 * honest to populate a dropdown from. Inventing a list of providers would be inventing
 * data. It is therefore an optional exact-match text input, and the empty case is
 * simply omitted from the query.
 */

/* ============================================================
 * The shipped contract, mirrored
 * ============================================================ */

/** `_SORT_COLUMNS` in `services/ad_query.py`. There is no relevance sort, deliberately. */
export const SORT_FIELDS = [
  "last_seen_at",
  "first_seen_at",
  "meta_delivery_start",
  "meta_ad_id",
] as const;
export type SortField = (typeof SORT_FIELDS)[number];

/** Human labels for the allowlist. Nothing outside `SORT_FIELDS` may be sent. */
export const SORT_LABELS: Readonly<Record<SortField, string>> = {
  last_seen_at: "Last seen",
  first_seen_at: "First seen",
  meta_delivery_start: "Meta-reported start",
  meta_ad_id: "Ad id",
};

export const DEFAULT_SORT: SortField = "last_seen_at";
export const DEFAULT_DIRECTION = "desc";

export const STATUSES = ["seen", "not_seen_since", "presumed_inactive"] as const;
export type StatusValue = (typeof STATUSES)[number];

/** `AGENTS.md` section 7 wording, carried into the control itself. */
export const STATUS_LABELS: Readonly<Record<StatusValue, string>> = {
  seen: "Seen",
  not_seen_since: "Not seen since",
  presumed_inactive: "Presumed inactive",
};

export const DATA_ORIGINS = ["official_api", "public_ui", "third_party", "user_import"] as const;
export type DataOriginValue = (typeof DATA_ORIGINS)[number];

export const DATA_ORIGIN_LABELS: Readonly<Record<DataOriginValue, string>> = {
  official_api: "Official API",
  public_ui: "Public UI",
  third_party: "Third party",
  user_import: "Imported by operator",
};

/**
 * `provider_active` is tri-state and the **absence** of the filter is a third option.
 *
 * There is deliberately no "provider said nothing" filter: the backend cannot express
 * one, so offering it would be a control that either lies or silently does nothing.
 */
export const PROVIDER_ACTIVE_OPTIONS = [
  { value: "", label: "Any" },
  { value: "true", label: "Reported active" },
  { value: "false", label: "Not reported active" },
] as const;

export const DEFAULT_PAGE_SIZE = 25;
export const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
export const MAX_PAGE_SIZE = 100;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/* ============================================================
 * The state
 * ============================================================ */

/**
 * `""` means "not filtered". Every optional field uses that rather than `undefined`, so
 * "cleared" has exactly one representation and an empty filter never becomes the string
 * `"undefined"` in a query string.
 */
export type AdsQuery = {
  readonly q: string;
  readonly provider: string;
  readonly competitorId: string;
  readonly facebookPageId: string;
  readonly country: string;
  readonly currentStatus: "" | StatusValue;
  readonly providerActive: "" | "true" | "false";
  readonly dataOrigin: "" | DataOriginValue;
  readonly firstSeenFrom: string;
  readonly firstSeenTo: string;
  readonly lastSeenFrom: string;
  readonly lastSeenTo: string;
  readonly sort: SortField;
  readonly direction: "asc" | "desc";
  readonly page: number;
  readonly pageSize: number;
};

export const DEFAULT_QUERY: AdsQuery = {
  q: "",
  provider: "",
  competitorId: "",
  facebookPageId: "",
  country: "",
  currentStatus: "",
  providerActive: "",
  dataOrigin: "",
  firstSeenFrom: "",
  firstSeenTo: "",
  lastSeenFrom: "",
  lastSeenTo: "",
  sort: DEFAULT_SORT,
  direction: DEFAULT_DIRECTION,
  page: 1,
  pageSize: DEFAULT_PAGE_SIZE,
};

/* ============================================================
 * Parsing
 * ============================================================ */

/** Trim and bound a free-text value. Long query strings are trimmed server-side too. */
function text(raw: string | null, max = 200): string {
  return (raw ?? "").trim().slice(0, max);
}

function oneOf<T extends string>(raw: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(raw as T) ? (raw as T) : fallback;
}

function date(raw: string | null): string {
  const value = text(raw, 10);
  return ISO_DATE.test(value) ? value : "";
}

function uuid(raw: string | null): string {
  const value = text(raw, 36);
  return UUID.test(value) ? value.toLowerCase() : "";
}

function integer(raw: string | null, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

/**
 * Read research state out of a query string, validating every value.
 *
 * An unrecognised value falls back to the default rather than being forwarded. A URL is
 * user input, and the backend's own behaviour on a bad sort field is a 400 with a
 * message -- which in a research tool is worse than quietly using the default.
 */
export function adsQueryFromParams(params: URLSearchParams | string): AdsQuery {
  const search =
    typeof params === "string" ? new URLSearchParams(params.startsWith("?") ? params.slice(1) : params) : params;

  const providerActiveRaw = search.get("provider_active") ?? "";
  const providerActive: AdsQuery["providerActive"] =
    providerActiveRaw === "true" || providerActiveRaw === "false" ? providerActiveRaw : "";

  return {
    q: text(search.get("q")),
    provider: text(search.get("provider")),
    competitorId: uuid(search.get("competitor_id")),
    facebookPageId: uuid(search.get("facebook_page_id")),
    // Upper-cased because the backend does the same; sending "in" and getting no rows
    // would be a silent failure.
    country: text(search.get("country"), 2).toUpperCase(),
    currentStatus: oneOf(search.get("current_status"), STATUSES, "" as AdsQuery["currentStatus"]),
    providerActive,
    dataOrigin: oneOf(search.get("data_origin"), DATA_ORIGINS, "" as AdsQuery["dataOrigin"]),
    firstSeenFrom: date(search.get("first_seen_from")),
    firstSeenTo: date(search.get("first_seen_to")),
    lastSeenFrom: date(search.get("last_seen_from")),
    lastSeenTo: date(search.get("last_seen_to")),
    sort: oneOf(search.get("sort"), SORT_FIELDS, DEFAULT_SORT),
    direction: oneOf(search.get("direction"), ["asc", "desc"], DEFAULT_DIRECTION) as AdsQuery["direction"],
    page: integer(search.get("page"), 1, 10_000, 1),
    pageSize: integer(search.get("page_size"), 1, MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE),
  };
}

/* ============================================================
 * Serialising
 * ============================================================

/** Query-parameter names, matching `GET /ads` exactly. */
const PARAM = {
  q: "q",
  provider: "provider",
  competitorId: "competitor_id",
  facebookPageId: "facebook_page_id",
  country: "country",
  currentStatus: "current_status",
  providerActive: "provider_active",
  dataOrigin: "data_origin",
  firstSeenFrom: "first_seen_from",
  firstSeenTo: "first_seen_to",
  lastSeenFrom: "last_seen_from",
  lastSeenTo: "last_seen_to",
  sort: "sort",
  direction: "direction",
  page: "page",
  pageSize: "page_size",
} as const;

/**
 * The request parameters, omitting everything at its default.
 *
 * Omission is not tidiness. An empty filter must not become `country=` or `sort=`, and
 * the request layer already drops nullish values; doing it here means the URL and the
 * request are byte-identical, so what a person can share is exactly what was asked for.
 */
export function adsQueryToParams(query: AdsQuery): URLSearchParams {
  const params = new URLSearchParams();
  const put = (key: string, value: string | number | undefined) => {
    if (value === undefined || value === "") return;
    params.set(key, String(value));
  };

  put(PARAM.q, query.q);
  put(PARAM.provider, query.provider);
  put(PARAM.competitorId, query.competitorId);
  put(PARAM.facebookPageId, query.facebookPageId);
  put(PARAM.country, query.country);
  put(PARAM.currentStatus, query.currentStatus);
  put(PARAM.providerActive, query.providerActive);
  put(PARAM.dataOrigin, query.dataOrigin);
  put(PARAM.firstSeenFrom, query.firstSeenFrom);
  put(PARAM.firstSeenTo, query.firstSeenTo);
  put(PARAM.lastSeenFrom, query.lastSeenFrom);
  put(PARAM.lastSeenTo, query.lastSeenTo);

  // Sorting and paging are omitted when they are the default, but `direction` on its own
  // is meaningful -- "sort by ad id ascending" is a real request -- so it is only omitted
  // alongside a default sort in a descending order.
  if (query.sort !== DEFAULT_SORT) put(PARAM.sort, query.sort);
  if (query.direction !== DEFAULT_DIRECTION || query.sort !== DEFAULT_SORT) {
    put(PARAM.direction, query.direction);
  }

  if (query.page > 1) put(PARAM.page, query.page);
  if (query.pageSize !== DEFAULT_PAGE_SIZE) put(PARAM.pageSize, query.pageSize);

  return params;
}

/** The flat object `fetchAds` sends. Identical to the parameters the URL shows. */
export function adsQueryToRequest(query: AdsQuery): Record<string, string | number> {
  return adsRequestFromParamString(adsQueryToParams(query));
}

/**
 * The flat request record for an already-serialised query string.
 *
 * This is what the ads effect uses, rather than `adsQueryToRequest(query)`, and the
 * difference is not cosmetic. Keying that effect on the *state object* means a
 * `popstate` landing on a URL already showing -- browser history restore, or Back to
 * where you were -- produces a new object with identical values and therefore a wasted
 * request. Deriving the request from the serialised string instead means the request and
 * the URL cannot disagree, and the effect depends only on a value that compares by
 * content.
 */
export function adsRequestFromParamString(
  params: URLSearchParams | string,
): Record<string, string | number> {
  const search =
    typeof params === "string"
      ? new URLSearchParams(params.startsWith("?") ? params.slice(1) : params)
      : params;
  const out: Record<string, string | number> = {};
  for (const [key, value] of search) out[key] = value;
  return out;
}

/* ============================================================
 * Transitions
 * ============================================================ */

/**
 * Any change other than paging returns to page 1.
 *
 * Staying on page 7 of a result set that now has 2 pages shows an empty grid and reads
 * as "your filter matched nothing", which is a false statement about the data.
 */
export function withFilter(query: AdsQuery, patch: Partial<AdsQuery>): AdsQuery {
  return { ...query, ...patch, page: 1 };
}

/** Paging alone preserves every active filter, search term and sort. */
export function withPage(query: AdsQuery, page: number): AdsQuery {
  return { ...query, page: Math.max(1, Math.floor(page)) };
}

/** Everything except the sort, back to defaults. Paging resets too. */
export function clearedQuery(): AdsQuery {
  return { ...DEFAULT_QUERY };
}

/* ============================================================
 * Active-filter summary
 * ============================================================ */

export type ActiveChip = {
  /** The query field this removes, or `"q"` for search. */
  readonly key: keyof AdsQuery;
  readonly label: string;
  readonly value: string;
};

/**
 * The active filters, for the compact summary row.
 *
 * Ordered the way the controls are laid out rather than alphabetically, so the row reads
 * in the same order a person filled them in. `sort` is included because an unexpected
 * order is exactly the thing someone needs to notice when a result set looks wrong.
 */
export function activeChips(query: AdsQuery): ActiveChip[] {
  const chips: ActiveChip[] = [];
  const add = (key: keyof AdsQuery, label: string, value: string) => {
    if (value !== "") chips.push({ key, label, value });
  };

  add("q", "Search", query.q);
  add("provider", "Provider", query.provider);
  add("competitorId", "Competitor", query.competitorId);
  add("facebookPageId", "Page", query.facebookPageId);
  add("country", "Country", query.country);
  add("currentStatus", "Status", query.currentStatus ? STATUS_LABELS[query.currentStatus] : "");
  add(
    "providerActive",
    "Provider active",
    query.providerActive === "true"
      ? "Reported active"
      : query.providerActive === "false"
        ? "Not reported active"
        : "",
  );
  add("dataOrigin", "Origin", query.dataOrigin ? DATA_ORIGIN_LABELS[query.dataOrigin] : "");

  for (const [key, label, value] of [
    ["firstSeenFrom", "First seen from", query.firstSeenFrom],
    ["firstSeenTo", "First seen to", query.firstSeenTo],
    ["lastSeenFrom", "Last seen from", query.lastSeenFrom],
    ["lastSeenTo", "Last seen to", query.lastSeenTo],
  ] as const) {
    add(key, label, value);
  }

  if (query.sort !== DEFAULT_SORT) chips.push({ key: "sort", label: "Sort", value: SORT_LABELS[query.sort] });
  if (query.direction !== DEFAULT_DIRECTION) {
    chips.push({ key: "direction", label: "Direction", value: query.direction === "asc" ? "Ascending" : "Descending" });
  }

  return chips;
}

/** Whether anything at all is filtered. Drives the "Clear all" affordance. */
export function hasActiveFilters(query: AdsQuery): boolean {
  return activeChips(query).length > 0;
}

/** Removing one chip. Sort and direction are cleared together -- neither alone is sensible. */
export function withoutChip(query: AdsQuery, key: keyof AdsQuery): AdsQuery {
  if (key === "sort" || key === "direction") {
    return { ...query, sort: DEFAULT_SORT, direction: DEFAULT_DIRECTION, page: 1 };
  }
  return withFilter(query, { [key]: "" } as Partial<AdsQuery>);
}

/** Total result count in words. Used by the pagination row. */
export function pluralRows(count: number): string {
  return `${count} ${count === 1 ? "ad" : "ads"}`;
}
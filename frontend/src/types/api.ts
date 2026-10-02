/**
 * TypeScript mirror of the backend response contracts.
 *
 * ## These are hand-written, and that is the point
 *
 * They are not generated from the OpenAPI schema. Generating them would be tidy, but
 * it would also mean the client silently accepts whatever the backend happens to
 * emit today, and a backend field added by accident would appear in the client as a
 * supported one. `schemas/base.py` makes every response `extra="forbid"` precisely
 * because an undeclared field is a bug rather than a feature; a generated type would
 * throw that intent away.
 *
 * So each type here is written against a named backend model, and when the backend
 * changes, the compiler says so instead of the client quietly adapting.
 *
 * ## Three traps, and why they are easy to get wrong
 *
 * 1. **`extra="forbid"` has no TypeScript equivalent.** These interfaces cannot
 *    express "an unexpected field is an error". What they *can* do is describe the
 *    contract exactly, so that adding a field is a compile-time decision. Treat any
 *    field here as load-bearing: do not add one because a response happens to carry
 *    it.
 *
 * 2. **`MediaReferenceOut.duration_seconds` is a `string`, not a `number`.** It is a
 *    Python `Decimal`, and Pydantic serialises `Decimal` as a JSON **string** to avoid
 *    the float precision loss that turns `19.9` into `19.900000000000002`. Typing it
 *    as `number` would be wrong twice: it would mis-type the payload, and it would
 *    invite arithmetic that reintroduces the very error the string avoids. Parse it
 *    only where a duration is actually displayed, and never store it back.
 *
 * 3. **`AnalysisOut.interpretation` is an open mapping, not fourteen fields.** The
 *    backend deliberately does not flatten the analysis into typed columns: the field
 *    set is versioned by `analysis_version`, and freezing v1's fourteen names into
 *    this contract would make a v2 a breaking change.
 *
 *    So it is `Readonly<Record<string, unknown>>`, and the value type is `unknown`
 *    rather than `string | null`. The backend declares
 *    `interpretation: dict[str, str | None]` today, but that is a property of v1 and
 *    not of the endpoint: a later `analysis_version` may carry a number, a nested
 *    object or a list, and none of those are broken data. Pinning the value type here
 *    would make a v2 arrive as a type error at every call site, instead of as
 *    something one renderer has to handle.
 *
 *    `unknown` obliges a reader to narrow before use, which is the point. A UI reads
 *    the keys it knows and renders anything it does not recognise as `null` -- never
 *    as a guessed default -- and has to decide what a non-string value means rather
 *    than having that decided by a type annotation.
 *
 * ## `null` stays `null`
 *
 * Every optional field below is genuinely optional and nothing fills it in. `null`
 * means "the source did not say". It is never `0`, never `""`, and never a
 * placeholder. Optional chaining (`?.`) and `?? null` are correct; `?? 0` and `|| ""`
 * are how a missing value becomes a lie. Render `null` as an em dash.
 */

/* ============================================================
 * Enums
 * Mirrored from `app.providers.data.provenance`,
 * `app.services.ad_duration`, and `app.models.ads`'s status vocabulary.
 * String-valued on the wire, so these are plain string unions.
 * ============================================================ */

/** How a value was obtained. Independent of `EvidenceClass`; never collapse them. */
export type DataOrigin = "official_api" | "public_ui" | "third_party" | "user_import";

/** How much the product can stand behind a value. */
export type EvidenceClass =
  | "VERIFIED_PUBLIC_DATA"
  | "PROVIDER_DATA"
  | "ESTIMATE"
  /** Model output. Must always render with an `AI INTERPRETATION` badge. */
  | "AI_INTERPRETATION";

/**
 * Which start timestamp a duration was measured from.
 *
 * `AGENTS.md` section 8: `meta_delivery_start` (the provider's claim) and
 * `first_seen_at` (our first observation) are separate and must never be merged. Any
 * duration display must state which one it used -- which is why this is a required
 * field on `DurationOut` rather than optional context.
 */
export type DurationSource = "meta_delivery_start" | "first_seen_at";

/**
 * A longevity proxy. Never a verdict.
 *
 * `LONG_RUNNING` renders only as **LONG-RUNNING SIGNAL**, with the tooltip that
 * duration is a public proxy and not performance. Never "winner", "loser", "best", or
 * "top performer".
 */
export type DurationBucket = "New" | "Testing" | "Established" | "Long-running" | "Evergreen";

/**
 * One ad's status in one Page + country context.
 *
 * `presumed_inactive` is a **presumption**, not a verdict: it requires N consecutive
 * COMPLETE runs without the ad, and is never set after a failed or partial run.
 * `not_seen_since` is explicitly *not* "stopped" -- absence from a run is not
 * evidence.
 *
 * `models.ads` defines the three values; `ContextOut.current_status` is declared as
 * a plain `str` on the wire, so a fourth value is technically possible and would
 * arrive as an unhandled string. Render the unknown case as `null`/em dash rather
 * than guessing a meaning for it.
 */
export type AdStatus = "seen" | "not_seen_since" | "presumed_inactive";

/* ============================================================
 * Competitors — `app.schemas.competitors`
 * ============================================================ */

/**
 * One Meta Page belonging to a competitor.
 *
 * `id` is this project's internal key and is what `/ads?facebook_page_id=` takes.
 * `page_id` is the provider's own identity for the same Page. They are different
 * things and must not be conflated.
 *
 * Carries no `data_origin` or `evidence_class`: neither a competitor nor a page is
 * collected data (`models/tracking.py`), so neither has an origin to declare.
 */
export interface FacebookPageOut {
  readonly id: string;
  readonly page_id: string;
  /** `null` when the provider reported no name. Never `""`. */
  readonly name: string | null;
  /** Always `http(s)` when present; the column refuses anything else. */
  readonly url: string | null;
  /** ISO 3166 alpha-2. Mandatory, unlike `name`. */
  readonly country: string;
  /**
   * Not a delete flag. An untracked page is reported as untracked and its history
   * stays visible, because `ad_snapshots` is append-only with `RESTRICT` foreign
   * keys -- hiding the page would hide real history.
   */
  readonly is_tracked: boolean;
  /** Free text, not a closed vocabulary. A scheduling decision, not a fact. */
  readonly tracking_frequency: string;
  readonly created_at: string;
}

/** One competitor the operator tracks, with every Page they advertise from. */
export interface CompetitorOut {
  /** Reuse verbatim as `/ads?competitor_id=`. */
  readonly id: string;
  /** **Not unique.** Two brands may share a name in different markets. */
  readonly name: string;
  readonly created_at: string;
  /** Always present, possibly empty: a competitor with no Pages is still real. */
  readonly pages: readonly FacebookPageOut[];
}

/**
 * Every tracked competitor.
 *
 * No `total` / `page` / `page_size`: the directory is small and is not paged.
 * No ad counts either -- a count beside a competitor name invites reading it as
 * performance, which this product cannot answer.
 */
export interface CompetitorListOut {
  readonly items: readonly CompetitorOut[];
}

/* ============================================================
 * Ads — `app.schemas.ads`
 * ============================================================ */

/** Elapsed running time, and which timestamp it was measured from. */
export interface DurationOut {
  readonly days: number;
  readonly bucket: DurationBucket;
  /** Required: any duration display must say which start it used. */
  readonly source: DurationSource;
  /** A longevity proxy. Never a performance claim. */
  readonly is_long_running_signal: boolean;
}

/** One ad's status in one Page + country context. Status lives here and nowhere else. */
export interface ContextOut {
  readonly facebook_page_id: string;
  readonly country: string;
  readonly current_status: AdStatus;
  /** Tri-state. `null` means the provider made no assertion; never round it to `false`. */
  readonly provider_active: boolean | null;
  /** When *we* last observed this ad in a complete run. Never `meta_delivery_start`. */
  readonly not_seen_since_at: string | null;
  readonly last_status_run_id: string | null;
}

/**
 * The snapshot an ad currently looks like.
 *
 * Deliberately excludes `raw_ref`: it is an internal pointer into the raw payload, and
 * exposing it invites a client to fetch evidence this API does not serve.
 */
export interface SnapshotSummaryOut {
  readonly id: string;
  readonly created_at: string;
  readonly content_hash: string;
  /** `null` for a snapshot written before S2.2; it cannot be backfilled. */
  readonly copy_hash: string | null;
  readonly creative_hash: string | null;
  /** The provider's own reported status, untranslated. */
  readonly ad_status: string | null;
  readonly meta_delivery_start: string | null;
}

/**
 * The four copy fields, read straight out of `normalized`.
 *
 * Provider text, verbatim: no canonicalisation, no trimming, no rewriting.
 */
export interface CopyFieldsOut {
  readonly primary_text: string | null;
  readonly headline: string | null;
  readonly description: string | null;
  readonly cta: string | null;
  readonly destination_url: string | null;
}

/**
 * One creative asset, as a **reference**.
 *
 * `bytes_available` is `false` by construction -- true is the truth until an approved
 * byte-acquisition phase exists. `source_url` is stored verbatim and is never
 * requested by this API.
 */
export interface MediaReferenceOut {
  readonly provider: string;
  readonly provider_key: string;
  readonly source_url: string | null;
  readonly mime: string | null;
  readonly width: number | null;
  readonly height: number | null;
  /**
   * A **string**, not a number -- see trap 2 in the module docstring.
   *
   * `null` when the provider reported no duration, which is normal for an image.
   * Do not coerce it to `0`: a static image has no duration, and `0` would read as
   * "an instant video".
   */
  readonly duration_seconds: string | null;
  readonly first_seen_at: string;
  readonly last_seen_at: string;
  readonly bytes_available: boolean;
}

/**
 * Model interpretation of this ad's copy.
 *
 * Copy-scoped and reusable: the same words on two ads resolve to one analysis, so
 * this is a property of the *copy*, not of the ad. Always badged
 * `AI_INTERPRETATION` -- a client must never present it as provider data.
 */
export interface AnalysisOut {
  readonly evidence_class: EvidenceClass;
  readonly copy_hash: string;
  readonly analysis_version: string;
  readonly prompt_version: string;
  readonly provider: string;
  readonly model: string | null;
  readonly language: string | null;
  readonly confidence: string | null;
  /**
   * The fourteen fields, or `{}` when a model answered with all of them `null` --
   * an empty mapping is a real reading of sparse copy, not missing data. See trap 3.
   *
   * The value type is `unknown`: today's values are `string | null`, but that belongs
   * to `analysis_version` v1 rather than to this endpoint, so a later version may
   * carry values of other types without anything being wrong. Narrow before use.
   */
  readonly interpretation: Readonly<Record<string, unknown>>;
  readonly source_snapshot_id: string;
  readonly created_at: string;
}

/**
 * One ad in a list response.
 *
 * There is deliberately **no** `current_status` here: S2.3 gives each
 * `(ad, Page, country)` context its own conclusion, so a single ad-level status would
 * be a claim the product cannot support. `contexts` carries them all.
 */
export interface AdListItemOut {
  readonly id: string;
  readonly provider: string;
  readonly meta_ad_id: string;
  readonly data_origin: DataOrigin;
  readonly first_seen_at: string;
  readonly last_seen_at: string;
  readonly latest_snapshot: SnapshotSummaryOut | null;
  readonly duration: DurationOut | null;
  readonly contexts: readonly ContextOut[];
  readonly media: readonly MediaReferenceOut[];
  /**
   * Where the provider reported this ad running, in the provider's own order.
   *
   * `[]` means **the stored record lists no platforms** -- which is not the claim
   * "this ad ran nowhere". A provider that reports nothing is recorded as nothing.
   */
  readonly platforms: readonly string[];
}

/**
 * A page of ads.
 *
 * `page` past the end returns `items: []` with the real `total`, not a 404.
 */
export interface AdListOut {
  readonly items: readonly AdListItemOut[];
  readonly total: number;
  readonly page: number;
  readonly page_size: number;
}

/**
 * One ad in full: the list item plus copy text, the AI interpretation, and media.
 *
 * `analysis` is `null` when no analysis exists -- **not** an object with fourteen
 * null fields, which would read as "we analysed it and found nothing".
 */
export interface AdDetailOut {
  readonly id: string;
  readonly provider: string;
  readonly meta_ad_id: string;
  readonly data_origin: DataOrigin;
  readonly first_seen_at: string;
  readonly last_seen_at: string;
  readonly latest_snapshot: SnapshotSummaryOut | null;
  readonly duration: DurationOut | null;
  readonly contexts: readonly ContextOut[];
  readonly copy_fields: CopyFieldsOut | null;
  readonly analysis: AnalysisOut | null;
  readonly media: readonly MediaReferenceOut[];
  /** The latest snapshot's reported platforms. `[]` means the record lists none. */
  readonly platforms: readonly string[];
}

/**
 * One observation, as stored.
 *
 * Named `SnapshotOut` here; the backend model is `SnapshotListItemOut`. The shorter
 * name is used because there is only one snapshot item shape and `ListItem` is
 * noise at the call site. The mapping is noted so the two are not mistaken for
 * unrelated contracts.
 *
 * `copy_fields` is present on snapshots and not on the list endpoint because a
 * snapshot page *is* a history page: showing what the ad said at a point in time is
 * the point of it.
 */
export interface SnapshotOut {
  readonly id: string;
  readonly created_at: string;
  readonly collection_run_id: string;
  readonly content_hash: string;
  readonly copy_hash: string | null;
  readonly creative_hash: string | null;
  readonly ad_status: string | null;
  readonly meta_delivery_start: string | null;
  readonly copy_fields: CopyFieldsOut;
  readonly media: readonly MediaReferenceOut[];
  /**
   * This snapshot's own reported platforms, not the ad's latest value.
   *
   * Per snapshot, because a snapshot records what the provider said at a moment, and
   * the platforms an ad ran on can legitimately differ between two observations of
   * the same ad. Reading the latest value for every row would make history claim
   * things it never saw.
   */
  readonly platforms: readonly string[];
  /**
   * Referenced, not embedded: copy-scoped analysis means the analysis an ad currently
   * resolves to may originate from a *different* snapshot, and saying so honestly is
   * better than pretending this observation produced it.
   */
  readonly analysis_copy_hash: string | null;
}

/** A page of one ad's history, newest first. */
export interface SnapshotListOut {
  readonly items: readonly SnapshotOut[];
  readonly total: number;
  readonly page: number;
  readonly page_size: number;
}
/**
 * One ad's status in one Page + country context.
 *
 * ## There is no ad-level status, and that is deliberate
 *
 * S2.3 gives each `(ad, Page, country)` context its own conclusion, and this component
 * takes a `ContextOut` rather than an ad. Collapsing several contexts into one status
 * would be a claim about something the product does not know -- an ad can be active on
 * one Page and absent from another, and that difference is the finding.
 *
 * ## Three wordings, and none of them is "stopped"
 *
 * | Status | Rendered as | Why |
 * |---|---|---|
 * | `seen` | Seen | The only positive statement we can make. |
 * | `not_seen_since` | Not seen since <date> | Absence from a run is **not** evidence an ad stopped. `AGENTS.md` section 8 is explicit that `not_seen_since` is not "stopped", so the word never appears. |
 * | `presumed_inactive` | **Presumed** inactive | A presumption, requiring N consecutive *complete* runs, never set after a failed one. The word "presumed" is load-bearing and is not styling. |
 *
 * `presumed_inactive` also carries "not a verdict" in its tooltip, because a badge that
 * says "inactive" and nothing else reads as a conclusion.
 *
 * ## `provider_active` is tri-state, and `null` is not `false`
 *
 * `null` means the provider made no assertion at all. Rounding it to `false` would
 * manufacture a finding -- "we checked and it was not running" -- from the absence of a
 * check. So `null` renders as an em dash via `NullValue`, and the label beside it says
 * what is missing rather than what was found.
 */

import type { AdStatus, ContextOut } from "../../types/api";
import { NullValue } from "./NullValue";
import { SafeText } from "./SafeText";
import { formatUtcDateTime } from "./format";

/** Literal labels. The status names are shown to the reader, not paraphrased. */
const STATUS_LABEL: Readonly<Record<AdStatus, string>> = {
  seen: "Seen",
  not_seen_since: "Not seen since",
  presumed_inactive: "Presumed inactive",
};

const STATUS_TITLE: Readonly<Record<AdStatus, string>> = {
  seen: "Observed in the latest complete run for this context",
  not_seen_since:
    "Not present in the latest complete runs. Absence from a run is not evidence that an ad stopped running.",
  presumed_inactive:
    "A presumption, not a verdict: absent from at least two consecutive complete runs. Never set after a failed or partial run.",
};

const STATUS_TONE: Readonly<Record<AdStatus, string>> = {
  seen: "badge--verified",
  not_seen_since: "badge--provider",
  presumed_inactive: "badge--estimate",
};

export type ContextStatusProps = {
  readonly context: ContextOut;
  /** Page display name, when the caller has one. `ContextOut` carries only an id. */
  readonly pageName?: string | null;
  /** The provider's Page identity, for disambiguating two Pages with the same name. */
  readonly pageId?: string | null;
  readonly className?: string;
};

export function ContextStatus({ context, pageName, pageId, className }: ContextStatusProps) {
  const { current_status, provider_active, not_seen_since_at, country } = context;

  return (
    <span
      className={`inline-flex flex-col items-start gap-1 text-sm ${className ?? ""}`.trim()}
      data-context-status={current_status}
      data-provider-active={provider_active === null ? "unknown" : String(provider_active)}
    >
      <span className="flex flex-wrap items-center gap-2">
        <span
          className={`badge ${STATUS_TONE[current_status]}`}
          title={STATUS_TITLE[current_status]}
        >
          {STATUS_LABEL[current_status]}
        </span>

        {/* Country is mandatory in the schema, but rendered defensively: an em dash is
            the honest answer if a context ever arrives without one. */}
        <SafeText value={country} className="text-xs text-slate-500 dark:text-slate-400" />

        {pageName !== undefined || pageId !== undefined ? (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {pageName ? <SafeText value={pageName} /> : <NullValue value={null} />}
            {pageId ? (
              <span className="ref ml-1 text-slate-400 dark:text-slate-500" title={pageId}>
                {pageId}
              </span>
            ) : null}
          </span>
        ) : null}
      </span>

      <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-slate-500 dark:text-slate-400">
        {/*
          Tri-state, stated explicitly. `true` / `false` / em dash. The `false` branch
          says "not reported active" rather than "inactive", because `false` is the
          provider declining to assert activity -- not this product concluding the ad
          stopped.
        */}
        <span data-testid="provider-active">
          Provider:{" "}
          {provider_active === null ? (
            <NullValue value={null} />
          ) : provider_active ? (
            "reported active"
          ) : (
            "not reported active"
          )}
        </span>

        {current_status === "not_seen_since" ? (
          <span data-testid="not-seen-since">
            Last seen:{" "}
            <SafeText value={formatUtcDateTime(not_seen_since_at)} />
          </span>
        ) : null}
      </span>
    </span>
  );
}

export default ContextStatus;
/**
 * How a value was **obtained**.
 *
 * ## Neutral on purpose, and not a stylistic choice
 *
 * All four values get the same tone. `data_origin` answers *where this came from*; it
 * does not answer *how much we stand behind it*. Colour-coding the four would invite a
 * reader to rank them, and `official_api` would read as more trustworthy than
 * `user_import` when the only difference is provenance.
 *
 * Trust lives on `evidence_class` -- see `EvidenceClassBadge` -- and that is the badge
 * that carries colour. The two axes answer different questions and `AGENTS.md` section 7
 * forbids collapsing them into one field, so they are also styled differently: this one
 * is flat grey, that one is tinted.
 *
 * The distinction matters most for `official_api`, which maps to
 * `VERIFIED_PUBLIC_DATA` while `user_import` maps to `PROVIDER_DATA`. Same origin axis,
 * different evidence axis, and only the second badge tells you which.
 */

import type { DataOrigin } from "../../types/api";

/**
 * Display labels. Kept as a literal map rather than computed from the value, because
 * `user_import` is not a phrase anyone says out loud.
 */
const LABELS: Readonly<Record<DataOrigin, string>> = {
  official_api: "Official API",
  public_ui: "Public UI",
  third_party: "Third party",
  user_import: "Imported by operator",
};

/** Short descriptions, for the `title` attribute. */
const TITLES: Readonly<Record<DataOrigin, string>> = {
  official_api: "Obtained from Meta's official API",
  public_ui: "Read from Meta's public Ad Library interface",
  third_party: "Obtained from a third party",
  user_import: "Entered by the operator, not obtained from a provider",
};

export type DataOriginBadgeProps = {
  readonly origin: DataOrigin;
  readonly className?: string;
};

export function DataOriginBadge({ origin, className }: DataOriginBadgeProps) {
  return (
    <span
      className={`badge badge--neutral ${className ?? ""}`.trim()}
      data-origin={origin}
      title={TITLES[origin]}
    >
      {LABELS[origin]}
    </span>
  );
}

export default DataOriginBadge;
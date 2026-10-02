/**
 * How much the product can **stand behind** a value.
 *
 * ## This is the badge that carries meaning
 *
 * Where `DataOriginBadge` is deliberately flat, the four values here are tinted, and the
 * two extremes are far apart on purpose:
 *
 * - `AI_INTERPRETATION` is **violet**, a hue used nowhere else in the app. Model output
 *   is the one thing a reader can mistake for something a provider said, so it does not
 *   get a shade of the provider blue.
 * - `ESTIMATE` is **amber**, not a pale green. An estimate is not verified data in a
 *   friendlier colour, and it must not sit beside `VERIFIED_PUBLIC_DATA` looking like a
 *   variation on it.
 *
 * ## `ESTIMATE` has nothing to show yet, and says so
 *
 * `AGENTS.md` section 7 requires an estimate to render with its stated method and
 * confidence. No estimate exists anywhere in this API, so there is no method to state.
 * Rather than invent one, the badge explains the requirement. The moment an estimate
 * reaches a client, it needs somewhere to put its method -- that is a real gap in the
 * contract, recorded here instead of papered over.
 */

import type { EvidenceClass } from "../../types/api";

/**
 * Tone per value, as literal class names.
 *
 * These strings must be written out in full. Tailwind scans source files, so a class
 * assembled from a variable would never be emitted and the badge would render unstyled
 * in production while looking correct in development.
 */
const TONE: Readonly<Record<EvidenceClass, string>> = {
  VERIFIED_PUBLIC_DATA: "badge--verified",
  PROVIDER_DATA: "badge--provider",
  ESTIMATE: "badge--estimate",
  AI_INTERPRETATION: "badge--ai",
};

const LABELS: Readonly<Record<EvidenceClass, string>> = {
  VERIFIED_PUBLIC_DATA: "Verified public data",
  PROVIDER_DATA: "Provider data",
  ESTIMATE: "Estimate",
  /** Spelled out in full, not "AI". The badge must be unambiguous on its own. */
  AI_INTERPRETATION: "AI interpretation",
};

const TITLES: Readonly<Record<EvidenceClass, string>> = {
  VERIFIED_PUBLIC_DATA: "Published by an official source, reproduced as published",
  PROVIDER_DATA: "Reported by a provider or entered by the operator; not independently verified",
  ESTIMATE:
    "Computed by this product. An estimate must also state its method and confidence, which the current API does not carry.",
  AI_INTERPRETATION:
    "Model interpretation of the copy. Not something the provider said, and not a fact about the ad.",
};

export type EvidenceClassBadgeProps = {
  readonly evidenceClass: EvidenceClass;
  readonly className?: string;
};

export function EvidenceClassBadge({ evidenceClass, className }: EvidenceClassBadgeProps) {
  return (
    <span
      className={`badge ${TONE[evidenceClass]} ${className ?? ""}`.trim()}
      data-evidence-class={evidenceClass}
      title={TITLES[evidenceClass]}
    >
      {LABELS[evidenceClass]}
    </span>
  );
}

export default EvidenceClassBadge;
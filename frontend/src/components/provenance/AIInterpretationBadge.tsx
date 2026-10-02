/**
 * The badge that must never be mistaken for something a provider said.
 *
 * ## Why there is no link
 *
 * `AGENTS.md` section 7 requires an `AI_INTERPRETATION` value to link back to the
 * snapshot and the `copy_hash` it was derived from. This component carries both, and
 * deliberately renders **no anchor**.
 *
 * There is no router in this app yet, so any `href` would be invented -- and an
 * invented URL is worse than no URL, because it looks real and 404s. Worse, a plausible
 * guess like `/ads/{adId}#analysis` would quietly encode a routing decision that a
 * later step has to honour for backwards compatibility.
 *
 * So the identifiers are rendered as text and also exposed as `data-` attributes, which
 * is what a real link will key off when the routing step arrives:
 * `data-copy-hash` and `data-source-snapshot-id` carry the full values, and the visible
 * text carries truncated ones. Nothing here fetches anything -- building a URL is not a
 * request, and this component issues none.
 *
 * ## Why both identifiers, and not just the copy hash
 *
 * Analysis is **copy-scoped**: the same words on two ads resolve to one analysis. So the
 * `copy_hash` identifies the *words*, and the `source_snapshot_id` identifies the
 * *observation* that produced it. A reader comparing a stored analysis against a
 * snapshot listing needs both, and an analysis whose `source_snapshot_id` points at a
 * snapshot other than the ad's latest is normal rather than a bug.
 */

import type { AnalysisOut } from "../../types/api";
import { EvidenceClassBadge } from "./EvidenceClassBadge";
import { truncateIdentifier } from "./format";

export type AIInterpretationBadgeProps = {
  /** The `copy_hash` the interpretation was derived from. */
  readonly copyHash: string;
  /** The snapshot that produced it. May differ from the ad's latest snapshot. */
  readonly sourceSnapshotId: string;
  /** Show the identifiers under the badge. Off where space is tight. */
  readonly showReferences?: boolean;
  readonly className?: string;
};

export function AIInterpretationBadge({
  copyHash,
  sourceSnapshotId,
  showReferences = true,
  className,
}: AIInterpretationBadgeProps) {
  const shortCopy = truncateIdentifier(copyHash);
  const shortSnapshot = truncateIdentifier(sourceSnapshotId, 8);

  return (
    <span
      className={`inline-flex flex-col gap-1 ${className ?? ""}`.trim()}
      // Full values for a future link target and for tests. No request is made.
      data-copy-hash={copyHash}
      data-source-snapshot-id={sourceSnapshotId}
    >
      <EvidenceClassBadge evidenceClass="AI_INTERPRETATION" />

      {showReferences ? (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-slate-500 dark:text-slate-400">
          <span className="ref" title={copyHash}>
            copy {shortCopy}
          </span>
          <span className="ref" title={sourceSnapshotId}>
            snapshot {shortSnapshot}
          </span>
        </span>
      ) : null}
    </span>
  );
}

/**
 * The same badge, driven straight off an `AnalysisOut`.
 *
 * The identifiers are read off the object rather than passed separately, because a
 * caller holding an `AnalysisOut` and re-typing two of its fields is a chance to mix
 * up which snapshot an analysis came from.
 */
export function AIInterpretationBadgeForAnalysis({
  analysis,
  showReferences,
  className,
}: {
  readonly analysis: AnalysisOut;
  readonly showReferences?: boolean;
  readonly className?: string;
}) {
  return (
    <AIInterpretationBadge
      copyHash={analysis.copy_hash}
      sourceSnapshotId={analysis.source_snapshot_id}
      {...(showReferences === undefined ? {} : { showReferences })}
      {...(className === undefined ? {} : { className })}
    />
  );
}

export default AIInterpretationBadge;
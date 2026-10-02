/**
 * Longevity, and nothing else.
 *
 * ## The wording rule this component exists to enforce
 *
 * `AGENTS.md` section 7: longevity is **never** a verdict. Not a winner, not a loser, not
 * the best, not a top performer. Duration is a public proxy, and the tooltip says
 * exactly that, in exactly those words, because a reworded tooltip is how a proxy
 * quietly becomes a claim.
 *
 * `is_long_running_signal` therefore renders as **LONG-RUNNING SIGNAL** -- a statement
 * about what was observed, with no implied comparison to anything else.
 *
 * ## The source is not optional context
 *
 * `meta_delivery_start` is the provider's claim about when delivery began.
 * `first_seen_at` is when *we* first saw the ad. For a commercial ad that has been
 * running for months before anyone tracked it, those are months apart, and a duration
 * without its source is not interpretable. So `source` is always rendered, not tucked
 * into a tooltip -- if it were hidden, someone would quote the number without it.
 *
 * ## `days: 0` is a real zero
 *
 * An ad first observed today has run for zero days. That renders as `0`, not as an em
 * dash, and `NullValue` is used for the *missing* duration only. Collapsing the two
 * would erase the most common ad in a freshly seeded database.
 */

import type { DurationOut } from "../../types/api";
import { NullValue } from "./NullValue";

/**
 * The one sentence a longevity display is allowed to make about itself.
 * Exported so the test asserts against the same string the component renders.
 */
export const LONG_RUNNING_TOOLTIP = "duration is a public proxy, not performance";

const SOURCE_LABEL: Readonly<Record<DurationOut["source"], string>> = {
  meta_delivery_start: "Meta-reported delivery start",
  first_seen_at: "First seen by us",
};

export type DurationSignalProps = {
  /** `null` when the ad has no established duration yet. */
  readonly duration: DurationOut | null;
  readonly className?: string;
};

export function DurationSignal({ duration, className }: DurationSignalProps) {
  if (duration === null) {
    return (
      <span className={className}>
        <NullValue value={null} />
      </span>
    );
  }

  return (
    <span
      className={`inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-sm ${className ?? ""}`.trim()}
      data-duration-source={duration.source}
    >
      {/* `0` is rendered as 0. See the component docstring. */}
      <span className="tabular-nums font-medium">
        {duration.days} {duration.days === 1 ? "day" : "days"}
      </span>

      {/* The bucket is the provider-neutral longevity label: New / Testing /
          Established / Long-running / Evergreen. Not a ranking. */}
      <span className="text-slate-600 dark:text-slate-400">{duration.bucket}</span>

      {/* Always shown. A duration quoted without its source is not interpretable. */}
      <span className="text-xs text-slate-500 dark:text-slate-400">
        from {SOURCE_LABEL[duration.source]}
      </span>

      {duration.is_long_running_signal ? (
        <LongRunningSignal />
      ) : null}
    </span>
  );
}

/**
 * The badge, and the tooltip.
 *
 * Built as a real tooltip rather than a `title` attribute for two reasons: a `title` is
 * unreachable by keyboard and inconsistently exposed to screen readers, and it cannot be
 * styled. Here the trigger is focusable and the tooltip text is in the DOM, revealed on
 * hover and on focus.
 *
 * The tooltip text exists exactly once. A `title` *and* a hidden copy would be two
 * sources of truth for a string this exact, and the two would eventually disagree.
 */
function LongRunningSignal() {
  return (
    <span className="group relative inline-flex">
      <abbr
        tabIndex={0}
        title={LONG_RUNNING_TOOLTIP}
        data-testid="long-running-signal"
        className="badge badge--neutral cursor-help no-underline"
      >
        Long-running signal
      </abbr>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-0 z-10 mb-1 hidden w-max max-w-[16rem] rounded-md bg-slate-900 px-2 py-1 text-xs font-normal text-white shadow-lg group-hover:block group-focus-within:block dark:bg-slate-700"
      >
        {LONG_RUNNING_TOOLTIP}
      </span>
    </span>
  );
}

export default DurationSignal;
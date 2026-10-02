/**
 * The canonical rendering of a value we do not have.
 *
 * ## The rule
 *
 * `AGENTS.md` section 7: a missing value is `null` and renders as an em dash. It is
 * never `0`, never `"N/A"`, never a plausible placeholder. A blank gap invites the
 * reader to supply the number themselves, and a placeholder reads as a fact.
 *
 * ## The trap this component exists to close
 *
 * `value={0}` renders **`0`**, not `—`. Longevity has a real zero: an ad first seen
 * today has run for zero days, and that is a true statement, not a missing one. The
 * common bug is a truthiness check (`value ? value : "—"`) that cannot tell an absent
 * value from a zero, a false, or an empty string. This uses an explicit null check so
 * `0` survives. There is a test pinning that, because it is exactly the kind of defect
 * that survives review and ships as a wrong number.
 *
 * ## Why an empty string is treated as missing
 *
 * `""` renders `—` rather than an invisible span. An empty string carries no
 * information, and rendering it literally leaves a gap that looks like a layout bug
 * rather than like "we do not know". The backend already prefers `None` over `""`
 * (`FacebookPageOut.name` says so explicitly), so this is a belt-and-braces rule for
 * a value that reached us some other way.
 */

/** The one rendering of "we do not have this value". Exported so tests agree on it. */
export const EM_DASH = "—";

export type NullValueProps = {
  /**
   * The value to render. `null` and `undefined` render the em dash.
   *
   * `boolean` is deliberately absent. A boolean is a real answer, and which boolean
   * means what is a decision for the component that owns the field -- see
   * `ContextStatus`, where `provider_active` is tri-state and `null` means "the
   * provider made no assertion" rather than "false".
   */
  readonly value: string | number | null | undefined;
  /** Optional wrapper class, for spacing and sizing at the call site. */
  readonly className?: string;
};

export function NullValue({ value, className }: NullValueProps) {
  const missing = value === null || value === undefined || value === "";

  return (
    <span
      data-testid="null-value"
      // `missing` is exposed so a test -- or a stylesheet -- can distinguish "this
      // column was unknown" from "this column held a value". Relying on the glyph
      // alone would make the two indistinguishable to a screen reader.
      data-missing={missing ? "true" : "false"}
      className={className ?? "text-slate-400 dark:text-slate-500"}
    >
      {missing ? EM_DASH : value}
    </span>
  );
}

export default NullValue;
/**
 * Renders a nullable string as plain text, or the em dash when it is absent.
 *
 * ## What "safe" means here
 *
 * React escapes interpolated text, so `{value}` cannot inject markup. That is the whole
 * mechanism, and this component adds nothing to it -- there is no
 * `dangerouslySetInnerHTML` anywhere in this directory, and there must never be one.
 *
 * The component is still worth having, for three reasons that have nothing to do with
 * sanitising:
 *
 * 1. **It makes the null rule unavoidable.** A raw `{ad.copy_fields?.headline}` in JSX
 *    renders nothing at all for `null` -- an invisible gap -- which is the exact
 *    failure `NullValue` exists to prevent. Routing through one component means there
 *    is a single place where "absent" is decided.
 * 2. **It collapses a nullable string to text once.** Callers stop writing
 *    `value ?? ""` and accidentally shipping an empty string as if it were a value.
 * 3. **It gives markup somewhere safe to live.** Provider copy may contain characters
 *    that are meaningful in other contexts -- `&`, `<`, a stray quote -- and letting the
 *    browser treat them as text is the correct and boring behaviour.
 *
 * ## What it deliberately does not do
 *
 * No link wrapping, no truncation, no formatting, no dangerously-set HTML. A component
 * that quietly turned a provider string into an anchor would be making a decision about
 * a URL that only the caller has the context to make.
 */

import { NullValue } from "./NullValue";

export type SafeTextProps = {
  /** Provider or derived text. `null` and `undefined` render as an em dash. */
  readonly value: string | null | undefined;
  readonly className?: string;
};

export function SafeText({ value, className }: SafeTextProps) {
  if (value === null || value === undefined || value === "") {
    return <NullValue className={className} value={null} />;
  }

  // Interpolated as a child, never as HTML. React escapes it.
  return <span className={className}>{value}</span>;
}

export default SafeText;
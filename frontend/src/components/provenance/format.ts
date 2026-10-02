/**
 * Formatting helpers shared by the provenance components.
 *
 * ## Why date formatting is this fussy
 *
 * A timestamp arrives as an ISO string and has to become something readable. The three
 * easy mistakes are all ways of showing the reader something that is not true:
 *
 * - `new Date(bad).toISOString()` **throws** on an unparseable value, taking the whole
 *   ad detail page down because one optional timestamp was malformed.
 * - `String(new Date(bad))` renders the literal text `Invalid Date`, which is a bug
 *   displayed to a user as though it were data.
 * - `.toLocaleString()` renders differently depending on the reader's machine, so two
 *   people comparing the same ad see different numbers, and a screenshot cannot be
 *   matched against the database.
 *
 * So: UTC, a fixed format, and the original string returned untouched if it will not
 * parse. Returning the input is not a fallback -- it is the honest answer, because the
 * value we were given is a value, and hiding it behind a dash would be worse.
 */

/** `2026-10-02 05:39 UTC`. Sorts correctly, is unambiguous, and never re-orders. */
export function formatUtcDateTime(iso: string | null | undefined): string | null {
  if (iso === null || iso === undefined || iso === "") return null;

  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;

  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${parsed.getUTCFullYear()}-${pad(parsed.getUTCMonth() + 1)}-${pad(parsed.getUTCDate())}` +
    ` ${pad(parsed.getUTCHours())}:${pad(parsed.getUTCMinutes())} UTC`
  );
}

/** `2026-10-02`, for a date with no meaningful time component. */
export function formatUtcDate(iso: string | null | undefined): string | null {
  const full = formatUtcDateTime(iso);
  return full === null ? null : full.slice(0, 10);
}

/**
 * Shorten a long opaque identifier for display, keeping both ends recognisable.
 *
 * `copy_hash` is 64 hex characters. Showing it whole turns a table into a wall of
 * digits; showing none of it removes the reader's ability to confirm two rows refer to
 * the same copy. Twelve characters at each end is enough to compare by eye.
 *
 * The **full** value is returned alongside so the caller can put it in a `title`, where
 * it stays available on hover without dominating the layout.
 */
export function truncateIdentifier(value: string | null | undefined, keep = 12): string {
  if (value === null || value === undefined || value === "") return "—";
  if (value.length <= keep * 2 + 1) return value;
  return `${value.slice(0, keep)}…${value.slice(-keep)}`;
}
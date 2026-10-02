/**
 * What we hold for a creative asset: a reference, never bytes.
 *
 * ## This component cannot fetch a byte
 *
 * S2.4 stores references only. `bytes_available` is hard-coded `false` by the backend,
 * and it is hard-coded `false` here too: when it becomes `true`, that means an approved
 * byte-acquisition phase exists and the serving route is defined, not that this
 * component may start downloading things.
 *
 * So there is no `<img src>`, no thumbnail, no proxy, no `<video>`, no background-image.
 * Rendering `source_url` as an image would make the browser fetch it on render -- a
 * request to a third party, triggered by nothing the reader asked for, from a page whose
 * entire premise is showing only what this product collected.
 *
 * ## Why `source_url` is text and not a link either
 *
 * "Text or link target" would permit an `<a href>`. An anchor is not fetched on render,
 * so it would not break the rule above -- but it would send the reader straight to the
 * provider's CDN, around the authenticated media route that `AGENTS.md` section 6
 * requires. So the URL is rendered as text and exposed as a `data-source-url`
 * attribute. It stays copyable and inspectable, and it is not a way around the media
 * route.
 */

import type { MediaReferenceOut } from "../../types/api";
import { NullValue } from "./NullValue";
import { SafeText } from "./SafeText";
import { truncateIdentifier } from "./format";

/** Shown whenever bytes are not held. Exact wording; it is the fact, stated plainly. */
export const BYTES_NOT_ACQUIRED = "bytes not acquired";

export type MediaAvailabilityProps = {
  readonly media: MediaReferenceOut;
  readonly className?: string;
};

export function MediaAvailability({ media, className }: MediaAvailabilityProps) {
  return (
    <span
      className={`inline-flex flex-col items-start gap-1 text-sm ${className ?? ""}`.trim()}
      data-source-url={media.source_url ?? undefined}
      data-bytes-available={String(media.bytes_available)}
    >
      <span className="flex flex-wrap items-center gap-2">
        <span className="badge badge--neutral">{media.provider}</span>

        {/*
          `duration_seconds` is a **string** -- Pydantic serialises `Decimal` as a string
          to avoid float precision loss. Parsing it here would reintroduce exactly the
          error the string avoids, so it is displayed as sent. `null` is the normal case
          for an image, and it stays `null`: `0` would read as "an instant video".
        */}
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {media.duration_seconds === null ? (
            <NullValue value={null} />
          ) : (
            <span className="ref">{media.duration_seconds}s</span>
          )}
        </span>
      </span>

      <span className="text-xs text-slate-500 dark:text-slate-400">
        {media.bytes_available ? (
          <span title="Held by this product and served through the authenticated media route.">
            Bytes held
          </span>
        ) : (
          <span data-testid="bytes-not-acquired">{BYTES_NOT_ACQUIRED}</span>
        )}
      </span>

      {/*
        The provider's URL, stored verbatim and never requested. The full value is in the
        `title` so a truncated display still yields the whole thing on hover.
      */}
      <span className="max-w-full truncate text-xs text-slate-400 dark:text-slate-500">
        source_url:{" "}
        {media.source_url === null ? (
          <NullValue value={null} />
        ) : (
          <span className="ref" title={media.source_url}>
            {truncateIdentifier(media.source_url, 28)}
          </span>
        )}
      </span>

      <span className="text-xs text-slate-400 dark:text-slate-500">
        key:{" "}
        <SafeText value={truncateIdentifier(media.provider_key, 10)} className="ref" />
      </span>
    </span>
  );
}

export default MediaAvailability;
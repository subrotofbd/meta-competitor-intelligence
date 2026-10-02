/**
 * The ads grid. One ad per row, always -- never one row per context.
 *
 * ## Why one DOM instead of a table that reflows
 *
 * A real `<table>` cannot become a stacked card on mobile without either duplicating
 * every cell or letting the table scroll sideways. Duplicating markup means two copies
 * to keep in step; sideways scroll means the page is unusable at phone widths, which is
 * the thing to avoid.
 *
 * So this is one CSS grid with ARIA `table`/`row`/`cell` roles: screen readers still get
 * a table, and the layout goes from a single stacked column to a wide research grid
 * purely through breakpoints. One set of cells, one source of truth, no horizontal
 * scroll at any width.
 *
 * ## Secondary columns drop out on tablet
 *
 * Platforms and the copy preview carry `max-md:block md:hidden lg:block`: visible as
 * stacked rows on a phone, hidden on a tablet where the grid is already two columns
 * wide, visible again on a desktop. Competitor, context, duration, last-seen and
 * provenance never drop -- they are what the page is for.
 *
 * ## The copy columns are empty, and that is honest
 *
 * `AdListItemOut` has **no** copy fields. `primary_text`, `headline`, `description` and
 * `cta` exist only on `AdDetailOut`. There is no field on this row to read them from,
 * and inventing one, or fetching `/ads/{id}` per row to fill it, would both be wrong --
 * the first by fabricating, the second by pre-empting the detail screen with a request
 * storm.
 *
 * So the column renders `—` and says so, once, underneath the grid. That is the honest
 * state: the list endpoint does not carry copy text. When the backend adds it, the
 * column fills in with no change here beyond reading the new field.
 */

import type { ReactNode } from "react";

import { ContextStatus } from "../provenance/ContextStatus";
import { DataOriginBadge } from "../provenance/DataOriginBadge";
import { DurationSignal } from "../provenance/DurationSignal";
import { NullValue } from "../provenance/NullValue";
import { SafeText } from "../provenance/SafeText";
import { formatUtcDateTime } from "../provenance/format";
import { compactUuid, lookupPage, type Directory } from "../../api/library";
import type { AdListItemOut, AdListOut, ContextOut } from "../../types/api";

/** Shown when `platforms` is `[]`. Never a guess at what the ad ran on. */
export const NO_PLATFORMS_RECORDED = "none recorded";

/**
 * Explains the empty copy columns. Once, for the whole grid -- repeating it per row
 * would make the grid harder to read than saying nothing.
 */
export const COPY_NOT_IN_LIST_NOTE =
  "Copy text is not part of the ads list response. It is served by the ad detail endpoint.";

type Props = {
  readonly ads: AdListOut;
  readonly directory: Directory;
};

export function AdsGrid({ ads, directory }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div
        role="table"
        aria-label="Observed ads"
        aria-rowcount={ads.total}
        data-testid="ads-grid"
        className="flex flex-col gap-2"
      >
        {/* Column headers. `sr-only` on small screens, where the cards carry their own
            per-cell labels instead -- a header row above a stacked card is noise. */}
        <div
          role="row"
          className="hidden lg:grid lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1.7fr)_minmax(0,0.9fr)_minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,0.9fr)_auto] lg:gap-4 lg:border-b lg:border-slate-200 lg:pb-2 lg:text-xs lg:font-semibold lg:uppercase lg:tracking-wide lg:text-slate-500 dark:lg:border-slate-800"
        >
          <span role="columnheader">Competitor / Page</span>
          <span role="columnheader">Context &amp; status</span>
          <span role="columnheader">Platforms</span>
          <span role="columnheader">Copy</span>
          <span role="columnheader">Duration</span>
          <span role="columnheader">Last seen</span>
          <span role="columnheader">Provenance</span>
        </div>

        {ads.items.map((ad) => (
          <AdRow key={ad.id} ad={ad} directory={directory} />
        ))}
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400">{COPY_NOT_IN_LIST_NOTE}</p>
    </div>
  );
}

const CELL =
  "min-w-0 text-sm";

function AdRow({ ad, directory }: { ad: AdListItemOut; directory: Directory }) {
  return (
    <div
      role="row"
      data-testid="ad-row"
      data-ad-id={ad.id}
      // Stacked card on mobile, one grid row on desktop. `rounded` + `border` only below
      // `lg`, where it stops being a card and becomes a row.
      className="grid grid-cols-1 gap-x-4 gap-y-2 rounded-lg border border-slate-200 p-3 md:grid-cols-2 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1.7fr)_minmax(0,0.9fr)_minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,0.9fr)_auto] lg:items-start lg:rounded-none lg:border-0 lg:border-b lg:border-slate-100 lg:p-0 lg:py-3 dark:lg:border-slate-800"
    >
      {/* 1. Competitor / Page */}
      <div role="cell" className={CELL}>
        <CellLabel>Competitor / Page</CellLabel>
        <Names ad={ad} directory={directory} />
      </div>

      {/* 2. Context & status -- one block per context, never merged */}
      <div role="cell" className={`${CELL} flex flex-col gap-2`}>
        <CellLabel>Context &amp; status</CellLabel>
        {ad.contexts.length === 0 ? (
          <NullValue value={null} />
        ) : (
          ad.contexts.map((context) => (
            // Page identity is deliberately *not* passed here. The Names cell already
            // shows it, and passing it too rendered the same page name twice in every
            // row -- once as the ad's identity and once beside its status.
            <ContextStatus key={`${context.facebook_page_id}:${context.country}`} context={context} />
          ))
        )}
      </div>

      {/* 3. Platforms -- provider order, never sorted, never inferred */}
      <div role="cell" className={`${CELL} max-md:block md:hidden lg:block`}>
        <CellLabel>Platforms</CellLabel>
        <Platforms ad={ad} />
      </div>

      {/* 4. Copy -- empty by contract, see the module docstring */}
      <div role="cell" className={`${CELL} max-md:block md:hidden lg:block`}>
        <CellLabel>Copy</CellLabel>
        <div className="flex flex-col gap-0.5">
          <NullValue value={null} />
          <NullValue value={null} />
          <NullValue value={null} />
        </div>
      </div>

      {/* 5. Duration */}
      <div role="cell" className={CELL}>
        <CellLabel>Duration</CellLabel>
        <DurationSignal duration={ad.duration} />
      </div>

      {/* 6. Last seen */}
      <div role="cell" className={CELL}>
        <CellLabel>Last seen</CellLabel>
        <SafeText value={formatUtcDateTime(ad.last_seen_at)} className="text-sm" />
      </div>

      {/* 7. Provenance -- an origin, never a confidence or a ranking */}
      <div role="cell" className={CELL}>
        <CellLabel>Provenance</CellLabel>
        <DataOriginBadge origin={ad.data_origin} />
      </div>
    </div>
  );
}

/**
 * The label a stacked card needs, hidden once the column header takes over.
 *
 * Kept as a real element rather than a `::before` so it is in the accessibility tree
 * rather than being decoration-only CSS.
 */
function CellLabel({ children }: { children: ReactNode }) {
  return (
    <span className="block text-xs font-semibold uppercase tracking-wide text-slate-400 lg:hidden dark:text-slate-500">
      {children}
    </span>
  );
}

function Names({ ad, directory }: { ad: AdListItemOut; directory: Directory }) {
  // An ad can appear under several Pages across its contexts, so this lists the distinct
  // ones rather than picking the first. Picking one would be a claim the product has no
  // basis for.
  const entries: { key: string; entry: ReturnType<typeof lookupPage> }[] = [];
  const seen = new Set<string>();
  for (const context of ad.contexts as readonly ContextOut[]) {
    if (seen.has(context.facebook_page_id)) continue;
    seen.add(context.facebook_page_id);
    entries.push({
      key: context.facebook_page_id,
      entry: lookupPage(directory, context.facebook_page_id),
    });
  }

  if (entries.length === 0) {
    return <NullValue value={null} />;
  }

  return (
    <div className="flex flex-col gap-1">
      {entries.map(({ key, entry }) => (
        <div key={key} className="min-w-0">
          {entry?.competitorName ? (
            <SafeText value={entry.competitorName} className="block font-medium" />
          ) : (
            <NullValue value={null} />
          )}

          {entry?.pageName ? (
            <SafeText value={entry.pageName} className="block text-xs text-slate-500 dark:text-slate-400" />
          ) : entry ? (
            <NullValue value={null} className="block text-xs" />
          ) : (
            // No page in `/competitors` matched this UUID. Show the identifier itself --
            // never a plausible-looking invented name.
            <span
              data-testid="unresolved-page"
              className="ref block text-slate-500 dark:text-slate-400"
              title={key}
            >
              page {compactUuid(key)}
            </span>
          )}

          {entry?.pageId ? (
            // The provider's identity for the Page, distinct from our internal UUID.
            // Two Pages can share a display name, and this is what tells them apart.
            <span className="ref block text-slate-400 dark:text-slate-500" title={entry.pageId}>
              page <SafeText value={entry.pageId} />
            </span>
          ) : null}
        </div>
      ))}

      {ad.provider ? (
        <span className="text-xs text-slate-400 dark:text-slate-500">
          provider <SafeText value={ad.provider} />
        </span>
      ) : null}

      {/*
        The provider's own ad id. Without it, two ads from the same page with the same
        platforms and the same last-seen date render as two indistinguishable rows --
        which in a competitor-research grid is not a cosmetic problem. Compact, because
        it is an identifier rather than content; the full value is on hover.
      */}
      <span className="ref text-slate-400 dark:text-slate-500" title={ad.meta_ad_id}>
        <SafeText value={ad.meta_ad_id} />
      </span>
    </div>
  );
}

function Platforms({ ad }: { ad: AdListItemOut }) {
  // `[]` means the stored record lists no platforms. That is not "this ad ran nowhere",
  // and it is not an invitation to guess Facebook. It gets its own words.
  if (ad.platforms.length === 0) {
    return (
      <span data-testid="no-platforms" className="text-slate-500 dark:text-slate-400">
        {NO_PLATFORMS_RECORDED}
      </span>
    );
  }

  return (
    <span data-testid="platform-list" className="flex flex-wrap gap-1">
      {ad.platforms.map((platform, index) => (
        // Keyed on index because the provider order is the information here, and a
        // repeated platform would collide on value alone. Order is preserved exactly as
        // sent: not sorted, not deduplicated, not completed with a guess.
        <span key={`${platform}-${index}`} className="badge badge--neutral">
          <SafeText value={platform} />
        </span>
      ))}
    </span>
  );
}

export default AdsGrid;
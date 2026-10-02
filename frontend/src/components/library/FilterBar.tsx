/**
 * The research controls.
 *
 * ## Shape, not a wall
 *
 * Search is always visible; the filters live behind a disclosure on small screens and sit
 * inline on a desktop. That ordering is deliberate -- search is what a person reaches for
 * on every visit, filters are what they reach for when narrowing, and a toolbar that
 * shows everything at once gets narrow and unusable long before it gets powerful.
 *
 * Controls are laid out in a wrapping grid rather than a single row, so nothing scrolls
 * sideways at any width. A research filter bar that requires horizontal scrolling is a
 * filter bar whose right-hand half nobody finds.
 *
 * ## The competitor and page selects
 *
 * The page list is derived from the selected competitor. With no competitor selected the
 * select is **disabled and empty** -- it does not list every page, because a page list
 * that ignores its parent reads as a competitor filter that does not work. Selecting a
 * different competitor clears the page, since a page of another competitor would
 * contradict it.
 *
 * ## Colours mean nothing here
 *
 * These controls use the neutral surface. This is a form, not a claim, and giving it
 * badges would break the rule that colour is reserved for evidence.
 */

import { useId, useState } from "react";

import type { CompetitorListOut } from "../../types/api";
import {
  DATA_ORIGIN_LABELS,
  DATA_ORIGINS,
  PAGE_SIZE_OPTIONS,
  PROVIDER_ACTIVE_OPTIONS,
  SORT_FIELDS,
  SORT_LABELS,
  STATUSES,
  STATUS_LABELS,
  activeChips,
  type AdsQuery,
} from "./adsQuery";
import { SafeText } from "../provenance/SafeText";

type Props = {
  readonly query: AdsQuery;
  readonly competitors: CompetitorListOut;
  readonly onChange: (patch: Partial<AdsQuery>) => void;
  readonly onSearch: (value: string) => void;
  /** Search text as typed, which lags `query.q` while the debounce runs. */
  readonly searchDraft: string;
  readonly disabled: boolean;
};

export function FilterBar({
  query,
  competitors,
  onChange,
  onSearch,
  searchDraft,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false);
  const ids = {
    search: useId(),
    provider: useId(),
    competitor: useId(),
    page: useId(),
    country: useId(),
    status: useId(),
    active: useId(),
    origin: useId(),
    firstFrom: useId(),
    firstTo: useId(),
    lastFrom: useId(),
    lastTo: useId(),
    sort: useId(),
    direction: useId(),
    pageSize: useId(),
    toggle: useId(),
  };

  const selectedCompetitor = competitors.items.find((c) => c.id === query.competitorId);
  const pages = selectedCompetitor?.pages ?? [];

  return (
    <div className="flex flex-col gap-3" data-testid="filter-bar">
      {/* Search first and always visible. */}
      <div className="flex flex-col gap-1">
        <label htmlFor={ids.search} className="text-xs font-medium text-slate-600 dark:text-slate-400">
          Search copy and ad ids
        </label>
        <input
          id={ids.search}
          type="search"
          value={searchDraft}
          disabled={disabled}
          onChange={(event) => onSearch(event.target.value)}
          placeholder="Words in the ad copy"
          aria-describedby={`${ids.search}-hint`}
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus-visible:outline-sky-400"
        />
        <p id={`${ids.search}-hint`} className="text-xs text-slate-500 dark:text-slate-400">
          Searches the whole corpus, not only the page on screen.
        </p>
      </div>

      {/* Disclosure. `lg:hidden` so a desktop shows the filters inline and a phone gets a
          sheet that does not push the results off the screen. */}
      <button
        type="button"
        id={ids.toggle}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={`${ids.toggle}-panel`}
        className="flex items-center justify-between gap-2 rounded-md border border-slate-300 px-3 py-2 text-sm font-medium lg:hidden dark:border-slate-700"
      >
        <span>{open ? "Hide filters" : "Show filters"}</span>
        <span aria-hidden="true">{open ? "−" : "+"}</span>
      </button>

      <div
        id={`${ids.toggle}-panel`}
        data-testid="filter-panel"
        hidden={!open}
        className="hidden lg:flex lg:flex-col lg:gap-3"
      >
        <div className="flex flex-wrap gap-3">
          {/*
            Provider is a free-text exact match, not a dropdown: nothing in the API
            enumerates provider values, and inventing a list would be inventing data.
          */}
          <Text
            id={ids.provider}
            label="Provider (exact match)"
            value={query.provider}
            disabled={disabled}
            placeholder="Any"
            onChange={(value) => onChange({ provider: value })}
          />

          <Select
            id={ids.competitor}
            label="Competitor"
            value={query.competitorId}
            disabled={disabled}
            onChange={(value) => onChange({ competitorId: value, facebookPageId: "" })}
            options={[
              { value: "", label: "All competitors" },
              ...competitors.items.map((c) => ({ value: c.id, label: c.name })),
            ]}
          />

          <Select
            id={ids.page}
            label="Facebook Page"
            value={query.facebookPageId}
            disabled={disabled || !query.competitorId}
            hint={
              query.competitorId
                ? undefined
                : "Choose a competitor first. No Page list is offered without one, because a list that ignores its parent reads as a broken filter."
            }
            onChange={(value) => onChange({ facebookPageId: value })}
            options={[
              { value: "", label: query.competitorId ? "All Pages" : "No competitor selected" },
              ...pages.map((p) => ({ value: p.id, label: p.name ?? p.page_id })),
            ]}
          />

          <Text
            id={ids.country}
            label="Country"
            value={query.country}
            disabled={disabled}
            placeholder="IN"
            maxLength={2}
            onChange={(value) => onChange({ country: value.toUpperCase() })}
          />

          <Select
            id={ids.status}
            label="Current status"
            value={query.currentStatus}
            disabled={disabled}
            onChange={(value) => onChange({ currentStatus: value as AdsQuery["currentStatus"] })}
            options={[
              { value: "", label: "Any status" },
              ...STATUSES.map((s) => ({ value: s, label: STATUS_LABELS[s] })),
            ]}
          />

          <Select
            id={ids.active}
            label="Provider active"
            value={query.providerActive}
            disabled={disabled}
            onChange={(value) => onChange({ providerActive: value as AdsQuery["providerActive"] })}
            options={PROVIDER_ACTIVE_OPTIONS.map((o) => ({ ...o }))}
          />

          <Select
            id={ids.origin}
            label="Data origin"
            value={query.dataOrigin}
            disabled={disabled}
            onChange={(value) => onChange({ dataOrigin: value as AdsQuery["dataOrigin"] })}
            options={[
              { value: "", label: "Any origin" },
              ...DATA_ORIGINS.map((o) => ({ value: o, label: DATA_ORIGIN_LABELS[o] })),
            ]}
          />

          <Text
            id={ids.firstFrom}
            label="First seen from"
            type="date"
            value={query.firstSeenFrom}
            disabled={disabled}
            onChange={(value) => onChange({ firstSeenFrom: value })}
          />
          <Text
            id={ids.firstTo}
            label="First seen to"
            type="date"
            value={query.firstSeenTo}
            disabled={disabled}
            onChange={(value) => onChange({ firstSeenTo: value })}
          />
          <Text
            id={ids.lastFrom}
            label="Last seen from"
            type="date"
            value={query.lastSeenFrom}
            disabled={disabled}
            onChange={(value) => onChange({ lastSeenFrom: value })}
          />
          <Text
            id={ids.lastTo}
            label="Last seen to"
            type="date"
            value={query.lastSeenTo}
            disabled={disabled}
            onChange={(value) => onChange({ lastSeenTo: value })}
          />
        </div>

        <div className="flex flex-wrap items-end gap-3 border-t border-slate-200 pt-3 dark:border-slate-800">
          <Select
            id={ids.sort}
            label="Sort by"
            value={query.sort}
            disabled={disabled}
            onChange={(value) => onChange({ sort: value as AdsQuery["sort"] })}
            options={SORT_FIELDS.map((f) => ({ value: f, label: SORT_LABELS[f] }))}
          />

          <Select
            id={ids.direction}
            label="Direction"
            value={query.direction}
            disabled={disabled}
            onChange={(value) => onChange({ direction: value as AdsQuery["direction"] })}
            options={[
              { value: "desc", label: "Descending" },
              { value: "asc", label: "Ascending" },
            ]}
          />

          <Select
            id={ids.pageSize}
            label="Rows per page"
            value={String(query.pageSize)}
            disabled={disabled}
            onChange={(value) => onChange({ pageSize: Number(value) })}
            options={PAGE_SIZE_OPTIONS.map((n) => ({ value: String(n), label: String(n) }))}
          />
        </div>
      </div>
    </div>
  );
}

type SelectProps = {
  readonly id: string;
  readonly label: string;
  readonly value: string;
  readonly options: ReadonlyArray<{ value: string; label: string }>;
  readonly onChange: (value: string) => void;
  readonly disabled?: boolean;
  readonly hint?: string;
};

function Select({ id, label, value, options, onChange, disabled, hint }: SelectProps) {
  const hintId = `${id}-hint`;

  return (
    <div className="flex min-w-[10rem] flex-1 flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-slate-600 dark:text-slate-400">
        {label}
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus-visible:outline-sky-400"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {hint ? (
        <p id={hintId} className="text-xs text-slate-500 dark:text-slate-400">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

type TextProps = {
  readonly id: string;
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly type?: "text" | "date";
  readonly disabled?: boolean;
  readonly placeholder?: string;
  readonly maxLength?: number;
};

function Text({ id, label, value, onChange, type = "text", disabled, placeholder, maxLength }: TextProps) {
  return (
    <div className="flex min-w-[10rem] flex-1 flex-col gap-1">
      <label htmlFor={id} className="text-xs font-medium text-slate-600 dark:text-slate-400">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        maxLength={maxLength}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus-visible:outline-sky-400"
      />
    </div>
  );
}

/**
 * The active filters, compact.
 *
 * One muted row of removable chips, never a badge per field. A filter bar that shows all
 * fourteen controls at once tells you nothing about what is actually applied; this says
 * it at a glance, and each chip removes exactly one thing.
 *
 * Chips are buttons rather than badges on purpose. A badge is an assertion about a value;
 * this is a control, and it has to be focusable and labelled as one.
 */
export function ActiveFilters({
  query,
  onRemove,
  onClearAll,
}: {
  readonly query: AdsQuery;
  readonly onRemove: (key: keyof AdsQuery) => void;
  readonly onClearAll: () => void;
}) {
  const chips = activeChips(query);

  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="active-filters">
      <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Filtering by</span>
      <ul className="flex flex-wrap items-center gap-1.5">
        {chips.map((chip) => (
          <li key={String(chip.key)}>
            <button
              type="button"
              onClick={() => onRemove(chip.key)}
              className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800 dark:focus-visible:outline-sky-400"
            >
              <span className="text-slate-500 dark:text-slate-400">{chip.label}:</span>
              <SafeText value={chip.value} />
              <span aria-hidden="true">×</span>
              <span className="sr-only">{`Remove filter ${chip.label}`}</span>
            </button>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={onClearAll}
        className="rounded-md px-2 py-0.5 text-xs font-medium text-slate-600 underline underline-offset-2 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 dark:text-slate-300 dark:hover:text-white dark:focus-visible:outline-sky-400"
      >
        Clear all
      </button>
    </div>
  );
}
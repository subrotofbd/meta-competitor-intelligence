# Architecture (Vertical Slice 1)

Scope: add competitor -> configure country/page -> collect via one provider -> keep raw response -> normalize ->
historical snapshots -> archive creatives -> basic AI copy analysis -> Ad Library UI (filter, search, ad detail).
Everything else (video, landing-page intelligence, patterns, generators, alerts, campaigns, spend estimates) is out of
scope and only leaves seams. See IMPLEMENTATION_PLAN.md.

## Stack
- Frontend: React + Vite + TypeScript + Tailwind, responsive, dark/light.
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2.
- DB: PostgreSQL 16 (also used as the job queue via `SELECT ... FOR UPDATE SKIP LOCKED`, so no Redis in slice 1).
- Worker: same Python package, separate entrypoint (`python -m worker`). Scheduler + queue consumer.
- Media: `MediaStore` interface with `LocalFsStore` (dev) and `S3Store` (MinIO/S3/R2). Content-addressed keys.
- AI: `AIProvider` interface; `OpenAIProvider`, `GeminiProvider`. Model names come from settings, never hard-coded.
- Deployment: Docker Compose (postgres, minio optional, backend, worker, frontend). Windows via Docker Desktop/WSL2.

## Layout
```
frontend/  backend/app/{api,core,db,models,schemas,services}  worker/  database/migrations
scripts/   docs/   docker/   storage/   tests/
backend/app/providers/data/{base.py, official_api.py, public_ui.py, apify.py, manual_import.py}
backend/app/providers/ai/{base.py, openai.py, gemini.py}
```

## Provider abstraction
```python
class AdDataProvider(Protocol):
    name: str; origin: DataOrigin           # official_api | public_ui | third_party | user_import
    def capabilities(self) -> ProviderCapabilities: ...   # countries, categories, has_history, ...
    def fetch_page_ads(self, page: PageRef, country: str, *, cursor=None) -> ProviderResult: ...
    def canary(self) -> CanaryResult: ...   # cheap "is the provider still working" probe
```
`ProviderResult` = `{raw: dict|list, next_cursor, request_meta, cost_estimate}`. A provider returns
provider data and nothing else — it does not read its own payload. The orchestrator stores `raw` and
**commits it** before anything parses it, so a parser bug never loses data. A provider never touches the DB.
Errors are typed (`RateLimited`, `Blocked`, `SchemaChanged`, `Transient`). `Blocked` stops the run; it is never
worked around. `Transient` retries with capped exponential backoff + jitter.

### Collection safety
A cursor walk has three ways to end badly, all of which would otherwise leave a page permanently
uncollectible. Each has one documented stop:

- **Cursor cycle.** A cursor already followed in this execution is not followed again. The walk
  reports `error_type = cursor_cycle` and ends `partial`. Cursors are opaque: only equality is
  compared, and no provider-specific cursor semantics are assumed.
- **Record ceiling.** `collection_max_records_per_run` (default 10,000) bounds what one run holds in
  memory. It stops the walk *before* the next fetch, so it never reports a limit the provider did
  not cause, and it never truncates a page — a single page larger than the ceiling is stored and read
  whole. The run ends `partial` with `error_type = record_limit`. This is a memory bound, not a
  statement about any competitor's ad volume.
- **Stale runs.** A `running` run is abandoned only when three signals agree: it is `running`, no job
  for it holds a live lease, and it has added no provider call for `collection_stale_run_timeout`
  (default 30 minutes, which must exceed the 5-minute job lease). The third signal is what keeps a
  slow run from being taken from a live worker. Recovery marks such a run `failed` and **never
  `complete`** — elapsed time is not evidence that work was finished — which is what returns the page
  to the scheduler, since `pending`/`running` runs block a new one. It touches no `provider_run` or
  `raw_response`: a run that died at page nine still collected eight pages of evidence, and that
  evidence is the only copy.

## Data model (slice 1 tables)
Identity: `users`(role admin/analyst/viewer), `settings`, `audit_logs`.
Tracking: `competitors`, `facebook_pages`(page_id, country, tracking_frequency, is_tracked).
Runs: `collection_runs`(status, started/finished, counts, provider), `provider_runs`(request_meta, http status, error,
cost_estimate), `raw_responses`(run_id, provider, payload JSONB or object-store ref, payload_hash).
Ads: `ads`(stable UUID; `meta_ad_id` unique per provider source; first_seen_at, last_seen_at, current_status, latest
snapshot id), **`ad_snapshots`** (immutable, one row per ad per run seen: run_id, normalized JSONB, copy_hash,
creative_hash, content_hash, provider status fields, `raw_ref`), `ad_creatives`(cards/formats, card_key),
`media_assets`(sha256 unique, mime, bytes, width/height, storage_key, source_url, downloaded_at),
`ad_platforms`, `ad_countries`, `landing_pages`(canonical URL only in slice 1).
AI: `ad_analysis`(ad_id, copy_hash, analysis_version, model, provider, prompt_version, result JSONB, tokens,
cost_estimate, status), `ai_jobs`.
All tables: `id` (UUID), `created_at`, `updated_at`, and `provider`/`data_origin`/`collection_run_id` where relevant.
Deferred tables (created later, not now): video_*, scene_*, hooks/offers/ctas banks, patterns, reports, alerts.

## Historical tracking rules
- Snapshots are append-only. Updating an ad only moves `last_seen_at` and `latest_snapshot_id`; changed content adds a
  snapshot. A new snapshot row is written only if `content_hash` changed, otherwise a light `seen_in_run` link row, so
  history stays complete without bloat.
- **Hashes.** Three *independently versioned* digests, all siblings rather than
  parts of one another. Each is length-prefix framed and SHA-256; a stored value keeps
  meaning what it meant, because changing any of them is a new version literal and never a
  recomputation of old rows.
  - `content_hash` v1 (`s2.1-content-v1`, **frozen**): the eight S2.1 content inputs --
    primary text, headline, description, CTA, destination URL, display shape, platforms,
    and provider media keys. **It is not a composition of the other two.** An earlier
    draft of this line specified `content_hash = sha256(copy_hash + creative_hash +
    display_format + platforms)`; that was never built, and building it now would either
    rewrite history or force a v2 of a contract S2.1 froze deliberately. Corrected here to
    match what shipped.
  - `copy_hash` v1 (`s2.2-copy-v1`): the ad's *words* only -- primary text, headline,
    description, CTA, and the destination URL **exactly as validated and stored**. No URL
    canonicalization, no rewriting, no case folding: `landing_pages` does not exist, and a
    digest that moved because we tidied the URL would claim the provider had changed
    something it had not.
  - `creative_hash` v1 (`s2.2-creative-v1`): the ad's **provider media keys**, sorted for
    the hash representation only. This is an *identity*, not a content digest -- `AGENTS.md`
    section 12 forbids media byte downloads in S0-S3, so two ads re-served under a rotated
    key look different here and a creative duplicate is a hint rather than proof. S2.4's
    media-byte hash becomes a **v2** of this function and reinterprets nothing.
  - Both S2.2 columns live on `ad_snapshots`, are **nullable**, and are never backfilled:
    `NULL` means the observation predates S2.2. The table is append-only, so an older row
    cannot be enriched without rewriting history.
  - **Duplicate detection** groups snapshots by `copy_hash` and by `creative_hash` -- two
    *different* questions, which `content_hash` cannot answer because it hashes words and
    assets together. Identity is the digest, never a `UNIQUE` constraint: two advertisers
    running identical copy is a finding, not a violation. Groups require
    `count(DISTINCT ad_id) > 1` so one ad's history is never a duplicate of itself, and
    `NULL` digests are excluded. Group-to-competitor attribution is deferred; it needs the
    `seen_in_run` -> `collection_run` -> `facebook_page` -> `competitor` join and is an API
    concern.
- **`ad_creatives` is deferred.** It is listed above as `ad_creatives`(cards/formats,
  `card_key`), and it is deliberately **not built**. `app/providers/data/normalize.py`
  reads only the first creative body and flattens it into `RawAdRecord`; the committed
  corpus holds nine ads, every one single-bodied. There is no card-level structure in the
  current normalized contract, so a per-card table built now would fabricate rows rather
  than record observations. Carousel cards survive only as unmodelled `provider_metadata`.
  Building it needs a normalizer change first, which is its own checkpoint.
- **`ad_platforms`, `ad_countries` and `landing_pages` are not S2.2 scope.** They appear in
  the slice-1 list above for completeness and remain unbuilt. S2.2 added two columns and
  two indexes and no tables at all.
- Status semantics, kept explicit:
  - `provider_active` = provider says the ad is running (only trusted when returned).
  - `not_seen_since` = we did not see it in the latest complete run for that Page/country. **This is not "stopped".**
    An ad is marked `presumed_inactive` only after N consecutive complete runs without it (default 2), and never after
    a failed or partial run.
- Two duration figures, never merged: `meta_delivery_start` (provider-reported) and `first_seen_at` (our own first
  observation). Duration bucket uses the provider start date when present, else first_seen_at, and says which.
- Buckets (configurable defaults, my assumption): New 0-6 d, Testing 7-29, Established 30-59, Long-running 60-89,
  Evergreen 90+. UI label: **LONG-RUNNING SIGNAL** with tooltip "duration is a public proxy, not performance".

## Creative archive
**Deferred, and not S2.2.** `AGENTS.md` section 12 forbids media byte downloads in S0-S3, so
none of the following has been built; it is recorded here as the intended later shape, and
`creative_hash` v1 above is explicitly the *provider-key fallback* rather than a byte digest.
Download at collection time (URLs expire), only when the provider returned a media URL. Hash
bytes; skip if sha256 exists. Images stored as-is plus a WebP thumbnail; video stored as-is in
slice 1 (no ffmpeg processing yet, only ffprobe for duration if available). Failures are
recorded per asset, not per run. Media is served through authenticated backend routes, never
public buckets. When this lands, byte hashing becomes `creative_hash` **v2**; no stored
`s2.2-creative-v1` value is reinterpreted.

## AI copy analysis (slice 1)
- Input: normalized copy fields per ad (all cards' text joined with markers), country, language hint.
- Output JSON (validated with Pydantic, one retry on invalid JSON): hook, problem, promise, offer, cta, persona,
  pain_point, angle, proof, urgency, awareness_level, funnel_stage, copy_structure, why_it_may_work, plus `language`
  and `confidence` (low/med/high). Empty fields are `null`, never invented.
- Prompt states: no performance claims; interpretation only. UI badge `AI INTERPRETATION`.
- Dedupe: skip when `(copy_hash, analysis_version)` already has a successful result. Track tokens and estimated cost.
- Hindi/Hinglish copy is analyzed in original language; English summary fields produced alongside.

## API surface (slice 1)
`/auth/*`, `/competitors`, `/competitors/{id}/pages`, `/collections` (start run, list runs, run detail),
`/ads` (filters: competitor, country, platform, status, media_type, date range, min/max duration, funnel_stage,
q full-text), `/ads/{id}` (+ `/snapshots`, `/media/{asset_id}`), `/ads/{id}/analyze`, `/exports/ads.csv`, `/healthz`.
Search: PostgreSQL `tsvector` over copy + AI fields, `pg_trgm` for fuzzy. No external search engine in slice 1.

## Security
Secrets only in env (`.env.example`, `.env` gitignored). Argon2 password hashing, short-lived JWT + refresh, role checks
on every route, audit log for logins, competitor changes, runs, exports, analysis. Provider tokens never sent to the browser.

## Testing
Unit: normalizer, hashing, status transitions, bucket logic, URL canonicalization. Contract tests per provider using
sanitized recorded payloads (`tests/fixtures/`). Integration: Postgres via testcontainers. A `scripts/smoke_real.py`
drives one real collection and writes a report for the checkpoint.

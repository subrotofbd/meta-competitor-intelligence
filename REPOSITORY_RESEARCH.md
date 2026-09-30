# Repository Research

Date: 2026-09-30. Method: shallow `git clone` of each repo, reading LICENSE, README, dependency files and
(for the tracker) schema, normalizer and glossary. The GitHub REST API was rate-limited from the sandbox, so
licenses were read from each repo's LICENSE file, not the SPDX API. I confirmed the "MIT License" header and
copyright line; I did not diff the full text against the canonical MIT text.

**Depth of inspection differs and is stated per repo. "Not inspected" means exactly that.**

## Summary

| # | Repository | License | Last commit | Real code? | Reuse decision |
|---|---|---|---|---|---|
| 1 | kalilfagundes/meta-ads-competitor-tracker | MIT | 2026-09-24 | Yes, Python, ~3.6k lines in `tracker/` | Ideas + schema concepts. Reimplement, no wholesale copy |
| 2 | logiover/meta-ad-library-scraper | MIT (docs only) | 2026-07-13 | **No. README/examples only.** Scraper is a closed Apify actor | Field list as reference only |
| 3 | gntrs/swipefile | MIT | 2026-07-23 | Yes, React 18 + Vite 5 + Supabase, JS | Ideas only (hook bank, compare) |
| 4 | JRJthegreat/facebook-ads-spy-agent | MIT | 2026-08-31 | n8n workflow JSON + export script | Ideas only (media-type routing) |
| 5 | dantedelao89/analisis-competencia-ads | MIT | 2026-05-14 | Python scripts + Claude Code skill (Spanish) | Ideas only, video phase. Not read in depth |
| 6 | steadyfetch/n8n-templates | **NO LICENSE FILE** | 2026-09-15 | n8n workflow JSONs | **Not reusable. Reference only** |

Rule applied: no license = all rights reserved = no code reuse. MIT repos are legally reusable with notice, but we
still reimplement, because none of them match our stack or data-integrity rules (see conflicts).

Transitive dependency checked: `meta-ads-collector` 1.4.0 (used by repo 1) is MIT per its PyPI metadata.

---

## 1. meta-ads-competitor-tracker (most relevant)

- URL: https://github.com/kalilfagundes/meta-ads-competitor-tracker
- License: MIT, "meta-ads-competitor-tracker contributors"
- Architecture: Python 3.12, FastAPI + Jinja server-rendered UI, SQLAlchemy 2 + Alembic + psycopg3, boto3 to
  S3-compatible storage (bundled Garage), Docker Compose, EN/ES/PT i18n. Worker package: `collector`, `normalize`,
  `persist`, `resolver`, `linking`, `scheduler`, `canary`. Tables: companies, pages, collection_runs, ads,
  landing_pages, creatives, ad_appearances, collections, collection_items, page_snapshots, users, app_settings, proxies.
- Collection sources: (a) self-hosted via `meta-ads-collector` from your own IP or a rotating proxy pool, or
  (b) the author's paid Apify actor. Both feed one `from_meta_record` normalizer.
- **Key finding:** `meta-ads-collector` describes itself as reverse-engineering Meta's internal GraphQL API
  (hard-coded `doc_id`s, `lsd` token mined from the homepage, Chrome TLS/header impersonation via `curl_cffi`,
  proxy rotation). It is not the official API. This is the main terms/fragility risk in the whole project.
- Useful concepts:
  - `ad_appearances`: immutable "ad X seen in run Y" rows. This is our snapshot model.
  - Company has N Pages; Page is the unit of collection; Page is not an ad account (`act_...`, private).
  - Country belongs to the Page (per-page override of a default).
  - Creative vs Format vs Version (`collation_id`): carousel cards are creatives; multiple aspect ratios of one ad are
    formats, not cards; Meta-grouped versions are separate ads.
  - `card_key` = media file id + destination, not position, because Meta reorders cards.
  - Canonical landing URL with utm/fbclid/fragment stripped; landing-page snapshots keyed by content hash.
  - Expiring media URLs, so mirror media at collection time. Images to WebP, video via ffmpeg.
  - "Active" (running on Meta) vs "Tracked" (we collect it) are different words.
- Conflicts with our requirements:
  - Its tiers include "Winner" and "Gold". We use LONG-RUNNING SIGNAL and never "winner".
  - Its README states time-on-air is "the best public signal that an ad works". We label it a public proxy only.
  - Jinja UI, we need React/Vite/TS. Garage bootstrap is a deployment detail we replace with MinIO/local.
  - No AI layer, no raw-payload retention table as far as I read (not verified exhaustively).
  - Proxy pool + impersonation: see DATA_ACCESS.md open decision D1.
- Dependencies of note: alembic, SQLAlchemy, psycopg[binary], boto3, fastapi, uvicorn, jinja2, httpx, Babel,
  meta-ads-collector, Pillow.
- WILL use: schema concepts above; the idea of a canary check that detects provider breakage; CSV export shape.
- WILL NOT use: its code verbatim, its UI, its tier names, its proxy management, its Garage setup.

## 2. meta-ad-library-scraper (logiover)

- URL: https://github.com/logiover/meta-ad-library-scraper, License: MIT (covers the README/examples only)
- Architecture: none in the repo. It is documentation for a closed-source Apify actor. Nothing here is executable.
- Useful: the flat output field list: `adArchiveId, adLibraryUrl, pageId/pageName/pageUrl, pageCategories,
  pageLikeCount, isActive/status, startDate/endDate, totalActiveTime (seconds), publisherPlatform, bodyText, title,
  caption, linkDescription, linkUrl, ctaText/ctaType, displayFormat, cardTexts, byline, media, spend bounds
  (political/issue), impressions (political/issue), reach (EU)`.
- Conflicts: none; nothing to conflict with. Its marketing claims ("no login", "every past ad") are not evidence.
- WILL use: field list as a checklist for our normalized schema.
- WILL NOT use: the actor as a hard dependency (Apify stays optional).

## 3. swipefile (gntrs)

- URL: https://github.com/gntrs/swipefile, License: MIT
- Architecture: React 18 + Vite 5 SPA, Supabase (`db-setup.sql`), Node scripts, cron shell scripts. Scope has grown
  into a CRM: team chat, Stripe alerts, creator outreach, PostHog, SEO tracking.
- Useful: hook bank, side-by-side compare, tags, saved ads, CSV import, "morning brief".
- Conflicts: **infers winner/loser verdicts from ad longevity** ("auto-verdicts"). That directly contradicts our
  rule. Supabase couples the app to a hosted BaaS. Large unrelated surface.
- WILL use: hook bank and compare UX ideas in later phases.
- WILL NOT use: verdict automation, Supabase, CRM/ops features. Not inspected in depth: `src/` components.

## 4. facebook-ads-spy-agent (JRJthegreat)

- URL: https://github.com/JRJthegreat/facebook-ads-spy-agent, License: MIT
- Architecture: single n8n workflow. Apify scrape (200 ads, last 7 days) -> filter page likes > 1000 -> route by media
  type -> video: Gemini 2.0 Flash description; image: GPT-4o vision; then GPT-4.1 summary + rewritten copy -> Google Sheet.
- Useful: media-type routing; separating "describe the creative" from "summarize/rewrite"; audience-size prefilter
  to cut cost.
- Conflicts: model names are dated. Video path uploads to Google Drive as a workaround; we would not.
  "Rewrite ad copy" must be redesigned so output is original, not paraphrase of competitor wording.
- WILL use: routing idea, cost-prefilter idea. WILL NOT use: workflow JSON, Drive/Sheets plumbing.

## 5. analisis-competencia-ads (dantedelao89)

- URL: https://github.com/dantedelao89/analisis-competencia-ads, License: MIT
- Architecture: Claude Code skill + Python scripts (`process_all_videos.py`, `analyze_video.py`, `classify_audience.py`,
  `competitor_timeline.py`, `build_dashboard.py`); Apify actors for scraping/transcription; static HTML dashboard.
- Useful (video phase): transcribe -> translate -> analyze pipeline; audience classification; competitor timeline.
- WILL use: pipeline shape when we reach video analysis. Not inspected in depth: script internals. WILL NOT use: its code.

## 6. n8n-templates (steadyfetch)

- URL: https://github.com/steadyfetch/n8n-templates
- **License: none. No LICENSE file. Treat as all rights reserved.**
- Architecture: eight n8n workflow JSONs (Facebook/TikTok/LinkedIn/Google ad transcripts, teardown, IG, keyword volume);
  all call the author's paid Apify actors.
- Useful (ideas only): first-3-seconds hook + CTA + transcript per ad row; "charged only if transcribed" cost framing.
- WILL NOT copy any workflow JSON or text. Concepts (hook_first_3s, CTA extraction) are generic and we design our own.

## Cross-cutting conclusions

1. Only repo 1 is a real reference architecture, and it already covers most of our vertical slice conceptually.
2. Every repo's collection path is either unofficial GraphQL scraping or a paid Apify actor. None uses the official API,
   because the official API does not serve commercial ads in India (see DATA_ACCESS.md).
3. None retain provider raw payloads as a first-class, versioned table. We do.
4. Three repos treat longevity as a verdict. We will not.

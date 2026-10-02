# Implementation Plan

## Environment constraint
The sandbox I work in cannot reach facebook.com or Apify (network allow-list). I can build, unit-test and
contract-test against fixtures here. **The real-data acceptance run must happen on your machine or server**
(ideally a normal residential/office connection). I will ship `scripts/smoke_real.py` and a report template so
the run is one command.

## Slice 1 milestones
| Step | Deliverable | Verified how |
|---|---|---|
| S0 | Repo scaffold, Docker Compose, Alembic, CI lint/test | `docker compose up`, tests green |
| S1 | Auth + roles, competitors, pages, settings, audit log | API tests |
| S2 | Provider interface, `ManualImportProvider`, fixtures, normalizer, hashing | Unit + contract tests |
| S3 | Orchestrator: runs, raw response store, snapshots, status logic, retries | Integration tests with fixtures |
| S4 | `MetaPublicUiProvider` (wrapping `meta-ads-collector`, conservative defaults, per D1/D2) + canary | **Real-data smoke run (yours)** |
| S5 | Media archive: download, hash, thumbnails, S3/local store | Integration + real run |
| S6 | AI provider interface, copy-analysis pipeline, dedupe, cost tracking | Unit with mocked LLM + one live call |
| S7 | Frontend: Add competitor, Runs, Ad Library grid/table, filters, search, Ad Detail, snapshots, analysis panel, CSV | Manual walkthrough of your 11 acceptance items |
<!-- S7 reconciliation: see "S7 -> S3.3 naming" below. The row above is the original plan and is
     left as written; the reconciliation records what actually shipped under it. -->
| S8 | Real-data checkpoint report | see below |

`MetaOfficialApiProvider` is implemented as an interface-complete adapter (EU/UK/political) after S4 if you supply a token;
it is not on the India critical path.

## Slice 1 acceptance (your 11 items)
1 add competitor, 2 run collection, 3 real ads visible, 4 open an ad, 5 public copy, 6 creative/media, 7 first/last seen,
8 active/inactive where available, 9 run AI analysis, 10 search/filter, 11 historical snapshots.
Complete only when all 11 pass on real data. Anything not passing is reported as such, not papered over.

## STOP gate: real-data report (`docs/SLICE1_REPORT.md`)
What worked / What data was unavailable / Provider limitations / What broke / Recommended next phase.
I stop after writing it and wait for you.

## S7 -> S3.3 naming, and what of S7 actually shipped

The S0-S8 milestones above are the original plan. Work did not run to those letters: the
read API and the frontend were built inside **S3.3**, so what the plan calls S7 is now
called **S3.3**. The row is left as originally written so the plan's meaning survives.

**Shipped under S3.3**

| Planned as S7 | Shipped | Commit |
|---|---|---|
| Ad Library grid/table | Ads Library grid, one row per ad, contexts rendered inside the row | `62de95a` |
| filters, search | all twelve `/ads` filters plus debounced `q`, shared with the export | `a108aec` |
| sort | the backend allowlist only: `last_seen_at`, `first_seen_at`, `meta_delivery_start`, `meta_ad_id` | `a108aec` |
| pagination | `page`/`page_size` in the URL, 25/50/100 | `a108aec` |
| Ad Detail | identity, copy, contexts, longevity, stored analysis, media references | `48df868` |
| snapshots | historical observation list with its own paging | `61d89a7` |
| analysis panel | read-only display of a stored analysis; "not analysed" when absent | `22e6c41`, `48df868` |
| CSV | filtered CSV export | `39016a6` |

Supporting work that was not in the S7 row at all: `GET /competitors` (`438f4af`), the
`copy_fields` addition to `AdListItemOut` (`b7fc1a4`), the AI fixture re-keying onto real
production digests (`7d02882`), and the locked UI/UX direction (`a5a78b4`, `de28b0e`).

**Not shipped, and still outstanding from that row**

- **Add competitor** — no write route. `GET /competitors` reads only. Competitors and Pages
  are created by the operator directly, or by `scripts/seed_demo.py`. There is no
  competitor-management UI and no create/edit/delete API.
- **Runs** — no `/collections` routes and no runs UI. Collection runs are visible only as
  the `collection_run_id` on a snapshot; there is no start-run control, no run list and no
  run detail page.

Both are real gaps against the original acceptance list, not oversights of wording, and
neither has been started.

## Later phases (separate, in your order, each with its own plan)
2 creative intelligence, 3 landing-page intelligence, 4 video transcription + scenes, 5 competitor patterns + compare,
6 original ad generator + briefs, 7 alerts + scheduling polish + cost dashboard, 8 campaign planner, 9 hardening.
Estimated Spend Signal is a separate module with published methodology, after patterns.

## Risks
- Provider blocked/changed mid-build (mitigation: canary, fixtures, manual import, swappable interface).
- India commercial ads not actually visible (D3): discovered at S4; fallback is manual import or Apify.
- AI cost on large Pages: per-run cap on analyses, dedupe by copy_hash.
- Meta terms exposure for public-UI collection: documented in DATA_ACCESS.md; your decision D1/D2.

## Decisions I need before S4
D1 aggressiveness, D2 wrap vs own client (see DATA_ACCESS.md), plus: which AI provider key you have (OpenAI, Gemini, both),
and one real Indian competitor Page URL for the smoke run.

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

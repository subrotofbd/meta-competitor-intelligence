# AGENTS.md — Brandset Meta Competitor Intelligence

Permanent operating rules for OpenCode sessions on this repository.
This file is a rulebook, not a specification. Detailed design lives in the
project documents listed under **Read order**.

---

## 1. Read order

Read in this order before making changes. Do not assume prior session context.

1. `AGENTS.md` — this file (rules)
2. `PROJECT_MEMORY.md` — **source of truth for current state and next checkpoint**
3. `ARCHITECTURE.md` — stack, data model, provider/AI interfaces
4. `DATA_ACCESS.md` — what Meta does and does not publish; provider matrix
5. `IMPLEMENTATION_PLAN.md` — phased plan
6. `REPOSITORY_RESEARCH.md` — reference repos, licences, conflicts

These six files live in the **repository root**. Do not move them, rename them,
or duplicate them into `docs/`.

---

## 2. Project purpose

Track competitors' **public** Meta/Facebook/Instagram advertising, normalise it,
keep historical snapshots of what was observed on every collection run, run AI
copy analysis, and browse it in an Ad Library UI.

We analyse only what Meta already publishes. We are not an ad intelligence
service that infers private performance.

---

## 3. Architecture summary

- **Backend** — Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2.
  Package root `app` lives in `backend/app`, layered
  `api / core / db / models / schemas / services`.
- **Worker** — separate process, `python -m worker`, same Python package.
- **Database** — PostgreSQL 16. Primary store **and** the first queue
  implementation, but the queue sits behind a `JobQueue` Protocol so it stays
  replaceable. Search is `tsvector` + `pg_trgm`; no external search engine.
- **Frontend** — React + Vite + TypeScript + Tailwind in `frontend/`. A pure API
  client. S3 only; not created in S0.
- **Media** — `MediaStore` Protocol, content-addressed keys, served through
  authenticated backend routes. No byte downloads in S0–S3.
- **AI** — `AIProvider` Protocol. Model names come from settings, never
  hard-coded. No AI SDK is installed.
- **Dependencies** — `uv` manages Python. `uv.lock` is committed.
  **Never `pip install` globally.**

---

## 4. Checkpoint rules

Work in small checkpoints (S0 → S3, then later phases). **Never silently jump
from one checkpoint to a later one.**

At the end of every checkpoint, and then **STOP**:

1. Run the focused tests for what changed.
2. Inspect every changed file (`git status`, `git diff`).
3. Verify no unrelated files changed. If something unrelated changed, revert it
   and say so.
4. Append an entry to `PROJECT_MEMORY.md`: what changed, what was validated,
   tooling status, git status, known limitations, next checkpoint.
5. Report what changed, what remains, and any failures.
6. **Do not start the next checkpoint without explicit human approval.**

Never claim a check passed when the command failed. "4 of 11 acceptance items
pass, 7 deferred to the real-data run" is a valid result. Claiming an unverified
pass is not.

---

## 5. Data access rules — strict, non-negotiable

The product analyses **public** Meta advertising data only. The following are
**absolutely prohibited**, with no exceptions and no "temporary" exemptions:

- CAPTCHA bypass or solving
- authentication bypass
- private data or private endpoints
- access-control circumvention
- anti-bot protection evasion
- proxy rotation used for evasion
- TLS/header fingerprint impersonation (e.g. `curl_cffi`-style browser mimicry)
- `lsd` token mining
- reverse-engineered internal GraphQL / hard-coded `doc_id`s
- rate-limit circumvention

**If a provider is blocked, the run stops and the block is reported.** A blocked
provider is never retried aggressively and never worked around.

Hard product constraint: Meta's official Ad Library API does **not** serve normal
commercial ads for India (political/issue ads worldwide, any ad type in the
EU/UK). Do not design around it for India. See `DATA_ACCESS.md`.

**Never claim or display** competitor spend, leads, sales, ROAS, conversions, or
reach for commercial ads. That data is not public. `Not publicly available` is
the correct answer, and an em dash `—` is the correct UI rendering for a value
that is genuinely unknown.

---

## 6. Security rules

- Secrets live in the environment only. `.env` is gitignored. `.env.example`
  holds placeholders only. **Never commit a real key, token, or password.**
- Provider credentials must never reach the browser or any API response.
- Role checks on every route (auth is a post-S3 seam; no login UI in S0–S3).
- Media is served through authenticated backend routes. Never a public bucket.
- Untrusted input: raw provider payloads and AI output are untrusted. Never
  interpolate them into shell commands, SQL, or file paths without
  parameterisation or escaping. Use bound parameters, never f-strings in SQL.
- Log security-relevant events (auth failures, privilege escalation attempts).
- Do not point the `AIProvider` configuration at a plaintext `http://` endpoint
  while holding real credentials.
- **Before any destructive database command** — `DROP`, `TRUNCATE`, or a broad
  `DELETE` with no `WHERE` — halt, explain the impact, and get explicit human
  consent. See `.opencode/skills/accidental-data-loss-prevention/SKILL.md`.

---

## 7. Provenance rules

Every stored or displayed value must resolve to a provenance class. Keep the
two axes **independent** — they answer different questions and must never be
collapsed into one field:

**`data_origin`** — how the value was obtained
`official_api` | `public_ui` | `third_party` | `user_import`

**`evidence_class`** — how much the product can stand behind the value
`VERIFIED_PUBLIC_DATA` | `PROVIDER_DATA` | `ESTIMATE` | `AI_INTERPRETATION`

Working mapping (first cut; confirm before relying on it in UI copy):

| `data_origin` | `evidence_class` |
|---|---|
| `official_api` | `VERIFIED_PUBLIC_DATA` |
| `public_ui` | `PROVIDER_DATA` |
| `third_party` | `PROVIDER_DATA` |
| `user_import` | `PROVIDER_DATA` |
| — (computed) | `ESTIMATE` |
| — (model output) | `AI_INTERPRETATION` |

- `ESTIMATE` must always render with an `ESTIMATE` label plus its stated method
  and confidence. Never as fact. No estimates exist in S0–S3.
- `AI_INTERPRETATION` must always render with the `AI INTERPRETATION` badge and
  must link back to the snapshot and `copy_hash` it was derived from.
- A missing value is `null` and renders as `—`. It is never `0`, never `N/A`,
  and never filled with a plausible-looking placeholder.
- Never label longevity a verdict. **"LONG-RUNNING SIGNAL"** only, with the
  tooltip that duration is a public proxy, not performance. Never "winner",
  "loser", "best", or "top performer".

---

## 8. Historical snapshot rules

The history is the product. It cannot be re-collected, because commercial ads
that stop running disappear from Meta permanently.

- `ad_snapshots` is **APPEND-ONLY**. Never update or delete an observation.
- Never silently overwrite a previous ad observation.
- Write a new snapshot row **only** when `content_hash` changed. Otherwise write
  a light `seen_in_run` link row so history stays complete without bloat.
- An ad missing from a run is **not** evidence it stopped. `not_seen_since` is
  not "stopped".
- `presumed_inactive` requires **N = 2 consecutive COMPLETE runs** without the
  ad, and must **never** be set after a failed or partial run.
- Keep three statuses distinct, never a single boolean: `provider_active`,
  `not_seen_since`, `presumed_inactive`.
- `meta_delivery_start` (provider-reported) and `first_seen_at` (our first
  observation) are separate fields and must never be merged. Any duration
  display must state which one it used.
- Persist the raw provider payload **before** parsing, with `payload_hash`. A
  parser bug must never destroy collected data.
- Every migration must be reversible, or the reason it cannot be must be
  written down next to it.

---

## 9. Provider abstraction rules

- Business logic depends **only** on the `AdDataProvider` Protocol. A concrete
  provider module must never be imported outside its own module and the
  composition root.
- A provider **must not** touch the database, decide ad status, or write files.
  It returns data; the orchestrator persists.
- A provider returns `ProviderResult` and raises **only** typed errors:
  `RateLimited`, `Blocked`, `SchemaChanged`, `Transient`.
  - `Blocked` → stop the run, log it, do not work around it.
  - `Transient` → retry with capped exponential backoff + jitter.
- `MockProvider` is a **first-class provider**, not a throwaway test stub. It is
  registered through the same interface and the same composition root as any
  real provider. The initial slice must work with mock data and no external
  network access.
- Every provider needs contract tests against sanitized fixtures.
  **Real Page IDs, Ad IDs, and personal data must be scrubbed before commit.**
- To add a provider: implement the Protocol, add fixtures + contract tests,
  register it in the composition root. Nothing else may change.
- Do not copy code from an external repository. Reimplement. **A repository with
  no LICENSE is all rights reserved — reference only, no code reuse.**

---

## 10. AI rules

- All AI access goes through the `AIProvider` Protocol. No SDK calls in business
  logic. No AI SDK is installed in S0–S3.
- Analysis output is validated by Pydantic. Invalid JSON gets exactly **one**
  retry, then fails loudly.
- **A field absent from the source is `null`. Never invent, guess, or infer a
  value to fill a field.**
- The prompt must forbid performance claims. Interpretation only.
- Deduplicate on `(copy_hash, analysis_version)`. Track tokens and estimated
  cost per call.
- Hindi/Hinglish copy is analysed in its original language, and the analysis
  fields are written in that same language. **S3.1 has no separate English
  summary fields.** This line previously promised "English summary fields
  produced alongside", which no version of the schema ever had; adding fourteen
  `*_en` companions would double a contract meant to stay at sixteen names and
  force a UI rule about which column to trust. English summaries, if ever
  wanted, arrive as a **new `analysis_version` with its own schema** -- never as
  columns bolted onto v1.
- Copy analysis lands in **S3**, not before.

---

## 11. Windows rules

- The project path contains a **space** (`C:\Users\DELL\Downloads\Meta Audit`).
  Always quote paths in shell commands, Docker bind mounts, and scripts.
- Use `python` (3.12) or `py`. **`python3` does not work on this machine** — it
  resolves to the Microsoft Store alias stub and fails.
- Virtualenv executables are at `.venv\Scripts\`, **not** `.venv/bin/`. Skills
  written for POSIX paths must be translated, not copied.
- **Docker Desktop + PostgreSQL 16 is the primary runtime path.** A native
  PostgreSQL 16 install is the documented fallback. Do not claim Docker works
  unless the daemon has been verified this session.
- Prefer `uv` for all Python work. Never install Python packages globally.
- Keep Python and TypeScript source files at LF line endings to avoid noisy
  diffs.
- See `SETUP_WINDOWS.md` for the full verification and startup procedure.

---

## 12. Do-not-change rules

Do not change these without an explicit human decision in the conversation.

- **Do not** move, rename, or duplicate the six root-level documents listed in
  §1.
- **Do not** add video/transcription/ffmpeg, spend estimation, campaign builder,
  alerts, PDF reports, pattern mining, or scaling infrastructure. Those are
  later phases. Leave named seams only.
- **Do not** add Redis, Celery, Elasticsearch, a browser-automation library, a
  TLS-impersonation library, or an AI SDK in S0–S3.
- **Do not** add a second queue technology. Extend the `JobQueue` Protocol.
- **Do not** swap PostgreSQL for another primary store.
- **Do not** collapse `data_origin` and `evidence_class` into one field, and do
  not rename or drop their values. Additive enum changes need a migration and a
  UI label.
- **Do not** add media byte downloads in S0–S3.
- **Do not** implement authentication, login UI, or business endpoints in S0.
- **Do not** commit `.env`, credentials, API keys, unredacted provider payloads,
  or real Page/Ad IDs in fixtures.
- **Do not** create a git remote or push without explicit instruction.
- **Do not** replace `uv` with pip, poetry, or conda.
- **Do not** start S0.2 (or any later checkpoint) without explicit approval.

---

## 13. Current state

`PROJECT_MEMORY.md` is the source of truth for what is done, what is open, and
what the next checkpoint is. Read it first; do not rely on this file for
progress state, only for rules.

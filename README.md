# Brandset Meta Competitor Intelligence

Competitor ad intelligence for **public** Meta / Facebook / Instagram advertising.

We track what Meta already publishes about a competitor's pages, normalise it,
keep append-only historical snapshots of what was observed on every collection
run, run AI copy analysis, and browse it in an Ad Library UI.

> We do not infer private performance. Competitor spend, leads, sales, ROAS and
> conversions are **not public** for commercial ads and are never claimed or
> displayed. See [`DATA_ACCESS.md`](DATA_ACCESS.md).

---

## Status

**Checkpoint S3.3 complete.** The backend read API, the collection pipeline, the
append-only snapshot history, and the Ad Library frontend are built and tested.

**Shipped today**

| | |
|---|---|
| Routes | `GET /ads`, `GET /ads/{id}`, `GET /ads/{id}/snapshots`, `GET /competitors`, `GET /exports/ads.csv` |
| Frontend | Ad Library with filters, search, sort and pagination; Ad Detail; historical snapshots; CSV export |
| Database | PostgreSQL 16 via Docker Compose, Alembic migrations applied |
| Worker | Separate process; claims jobs and executes collection |
| Data | `MockProvider` against a sanitised fixture corpus |

**Deliberately not built.** No authentication of any kind — no login, no JWT, no roles, no
audit log; the app is single-operator. No `/healthz`. No platform, display-format or media
filter. No media **bytes**: creative assets are references only and nothing is ever fetched,
proxied or thumbnailed. No AI generation and no AI vendor — `MockAIProvider` reads stored
interpretations, and there is no trigger endpoint. No spend, ROAS, leads, revenue, reach or
impression figures anywhere, because those are not public for commercial ads. No PDF or
report generation; CSV export only. No dashboard charts.

**No real Meta provider exists and nothing here collects from Meta.** The only data
provider is `MockProvider`. A real provider for India commercial ads — plus whatever access
that requires — is a separate, later problem, not a configuration flag.

Current state and the next checkpoint: [`PROJECT_MEMORY.md`](PROJECT_MEMORY.md)

---

## Documents

| Document | Purpose |
|---|---|
| [`AGENTS.md`](AGENTS.md) | **Start here.** Permanent operating rules for AI sessions. |
| [`PROJECT_MEMORY.md`](PROJECT_MEMORY.md) | Checkpoint log, current state, open decisions. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Stack, data model, provider and AI interfaces. |
| [`DATA_ACCESS.md`](DATA_ACCESS.md) | What Meta does and does not publish; provider matrix. |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | Phased delivery plan. |
| [`REPOSITORY_RESEARCH.md`](REPOSITORY_RESEARCH.md) | Reference repositories, licences, conflicts. |
| [`SETUP_WINDOWS.md`](SETUP_WINDOWS.md) | Windows setup, verification, troubleshooting. |

---

## Stack

Backend Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic · Database PostgreSQL 16 ·
Frontend React 19 / Vite 7 / TypeScript / Tailwind 4 · Worker separate process ·
Python dependencies via [`uv`](https://docs.astral.sh/uv), frontend via npm

---

## Quick start (Windows)

```powershell
Set-Location "C:\Users\DELL\Downloads\Meta Audit"
Copy-Item .env.example .env     # then set POSTGRES_PASSWORD

docker compose up -d postgres   # compose defines PostgreSQL only
uv sync                         # creates .venv from pyproject.toml + uv.lock
uv run alembic upgrade head     # create the schema
uv run python scripts/seed_demo.py   # optional: demo rows from the fixture corpus

uv run uvicorn app.main:app --reload --port 8000   # API
uv run python -m worker                            # worker, separate window
```

```powershell
Set-Location frontend
npm install
npm run dev      # http://localhost:5173 -- proxies /api to the backend on :8000
```

The frontend reaches the API **only** through that dev proxy, which is also why the backend
needs no CORS configuration. There is no one-command production deployment; see
[`SETUP_WINDOWS.md`](SETUP_WINDOWS.md) §9 for what actually runs today.

---

## Data access

Strict rules, enforced in [`AGENTS.md`](AGENTS.md) §5. No CAPTCHA bypass, no
authentication bypass, no anti-bot evasion, no TLS/header fingerprint
impersonation, no `lsd` token mining, no reverse-engineered internal GraphQL, no
private endpoints, no rate-limit circumvention. A blocked provider **stops and
reports**; it is never worked around.

Ad data is collected through a replaceable `AdDataProvider` interface. `MockProvider`
is the only implementation that exists, and it reads a sanitised fixture corpus from disk,
so every slice so far has run with **no external network access**. A blocked provider stops
and reports; it is never worked around.
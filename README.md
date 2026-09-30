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

**Checkpoint S0.1 — repository and governance foundation. Complete.**

No database, no providers, no AI, no frontend yet. Nothing in this repository
collects data from Meta.

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
Frontend React / Vite / TypeScript / Tailwind (S3) · Worker separate process ·
Dependencies managed with [`uv`](https://docs.astral.sh/uv/)

---

## Quick start (Windows)

```powershell
Set-Location "C:\Users\DELL\Downloads\Meta Audit"
Copy-Item .env.example .env
```

Python dependencies require `uv` (see [`SETUP_WINDOWS.md`](SETUP_WINDOWS.md) §3).
Full setup, Docker verification and troubleshooting are documented there.

```powershell
uv run python -m worker        # worker entrypoint (no-op in S0.1)
uv run pytest                  # test suite (empty in S0.1)
```

---

## Data access

Strict rules, enforced in [`AGENTS.md`](AGENTS.md) §5. No CAPTCHA bypass, no
authentication bypass, no anti-bot evasion, no TLS/header fingerprint
impersonation, no `lsd` token mining, no reverse-engineered internal GraphQL, no
private endpoints, no rate-limit circumvention. A blocked provider **stops and
reports**; it is never worked around.

Ad data is collected through a replaceable `AdDataProvider` interface.
`MockProvider` is the first implementation and the first slice runs entirely on
mock data with no external network access.

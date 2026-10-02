# SETUP_WINDOWS.md — Brandset Meta Competitor Intelligence

Windows setup and verification for this project.

**Verified state as of 2026-09-30 (re-verified during S0.1 remediation), on this machine:**

| Tool | Version | Status |
|---|---|---|
| Python (`python`) | 3.12.10 | ✅ Working |
| Python (`py`) | 3.14.3 | ⚠️ Installed but **wrong version** — do not use for this project |
| `python3` | — | ❌ **Does not work.** Microsoft Store alias stub |
| `uv` | 0.12.21 | ✅ Installed and working (`C:\Users\DELL\.local\bin\uv.exe`) |
| Node.js | v24.19.0 | ✅ Working |
| npm | 11.19.0 | ✅ Working |
| Git | 2.56.0.windows.1 | ✅ Working |
| Docker CLI | 29.8.0 | ✅ Working |
| Docker Compose | v5.5.1 | ✅ Working |
| **Docker daemon** | 29.8.0 | ✅ **RUNNING.** Verified with `docker info` |
| PostgreSQL client (`psql`) | — | ❌ Not installed (provided by the container in S0.2) |

> **The daemon was stopped when this document was first written; it is running
> now.** `docker --version` succeeding still does **not** mean Docker works.
> Run `docker info` (section 6) to confirm the daemon is actually up. Do not
> claim Docker is working based on the CLI version alone, and re-verify if the
> machine has been rebooted.

---

## 0. Prerequisites

- Windows 10/11
- PowerShell 5.1+ (built in). All commands below are PowerShell.
- Git
- Python 3.12
- Node.js + npm (needed from S3, for the Vite frontend)
- Docker Desktop with WSL2 backend (primary path for PostgreSQL 16)

---

## 1. Confirm the working directory

The project path **contains a space**. This is the single most common source of
breakage on Windows.

```powershell
Set-Location "C:\Users\DELL\Downloads\Meta Audit"
Get-Location
```

Expected: `C:\Users\DELL\Downloads\Meta Audit`

> **Rule:** always quote this path. Unquoted, PowerShell splits it into
> `C:\Users\DELL\Downloads\Meta` and `Audit`.

---

## 2. Verify Python 3.12

```powershell
python --version
```

Expected: `Python 3.12.10`

Check the interpreter actually in use:

```powershell
python -c "import sys; print(sys.version); print(sys.executable)"
```

Expected `sys.executable`:
`C:\Users\DELL\AppData\Local\Programs\Python\Python312\python.exe`

### ⚠️ Use `python`, not `python3`

`python3` is **not** available on this machine. It resolves to the Microsoft
Store execution alias and fails with a Store redirect message. Use:

- `python` → 3.12.10 ✅ (correct)
- `py` → **3.14.3** ⚠️ (installed, but the wrong version for this project)

If `py` is ever needed, pin the version explicitly: `py -3.12`.

### Composite pre-flight probe

Run environment checks as one command, not a sequence of one-liners:

```powershell
python -c "import sys,importlib.util; print('python:',sys.version.split()[0]); print('exe:',sys.executable); print({p:('found' if importlib.util.find_spec(p) else 'NOT FOUND') for p in ['fastapi','sqlalchemy','alembic','pydantic','pytest']})"
```

---

## 3. Install and verify `uv` (required)

`uv` is the approved package manager for this project. It **is installed and
working on this machine** (0.12.21). The install step below is retained for a
fresh machine or a reset.

```powershell
# Check first
uv --version

# Install (official standalone installer, no global pip involved)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then **close and reopen PowerShell** so `PATH` refreshes, and verify:

```powershell
uv --version
```

> **Never** run `pip install` globally. Never add a second package manager
> (poetry, conda, pipenv). `uv.lock` is committed so installs are reproducible.

---

## 4. Verify Node.js and npm

Needed from **S3** (Vite + React frontend). Not required for S0–S2.

```powershell
node --version   # expected: v24.19.0
npm --version    # expected: 11.19.0
```

---

## 5. Verify Git

```powershell
git --version    # expected: git version 2.56.0.windows.1
git status
```

This repository has **no remote** by design. Do not add one or push without
explicit instruction.

If a commit fails with *"Please tell me who you are"*, set a **repo-local**
identity (never global):

```powershell
git config user.name  "Your Name"
git config user.email "you@example.com"
```

---

## 6. Start and verify Docker Desktop

**The Docker daemon is running** (verified 2026-09-30 via `docker info`,
ServerVersion 29.8.0). If it is **not** running on your machine, start Docker
Desktop from the Start Menu (or the system tray icon), and wait for the whale
icon to report running.

Then verify the **daemon**, not just the CLI:

```powershell
docker --version          # CLI only - proves nothing about the daemon
docker compose version    # CLI only - proves nothing about the daemon
docker info               # <-- THIS is the real check
```

`docker info` must print a `Server:` block. If it fails with:

```
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
```

then the daemon is **not** running — start Docker Desktop and retry.

Confirm the container is actually up:

```powershell
docker ps
```

### WSL2

Docker Desktop on Windows requires WSL2. If `docker info` reports a WSL error,
run in an elevated PowerShell:

```powershell
wsl --install
wsl --update
```

Then restart Docker Desktop.

---

## 7. PostgreSQL — primary path vs fallback

### Primary: Docker Compose

PostgreSQL 16 runs as a container. `docker-compose.yml` **exists** and defines a single
service named `postgres` — not `db`. The compose file does **not** define the backend, the
worker or the frontend; those run from the host (see §9).

```powershell
docker compose up -d postgres
docker compose ps            # wait for "healthy"
docker compose logs -f postgres
```

The service has a `pg_isready` healthcheck, so `docker compose ps` reporting `healthy` is the
signal that migrations can run.

Stop (keeps data):

```powershell
docker compose stop postgres
```

Destroy the container and its volume (**destructive — see the data-loss rule in
`AGENTS.md` §6 and get consent first**):

```powershell
# DESTRUCTIVE. Requires explicit human consent before running.
# docker compose down -v
```

> `docker compose down -v` deletes the volume, and therefore **every seeded demo row and
> every snapshot**. `ad_snapshots` refuses `UPDATE` and `DELETE`, so those rows cannot be
> re-created by re-seeding alone — they would be gone. Never run it to tidy up.

### Fallback: native PostgreSQL 16

If Docker cannot be made to work, install PostgreSQL 16 natively, create a
database and role matching `.env.example`, and point `DATABASE_URL` at it:

```
postgresql+psycopg://brandset:<password>@localhost:5432/brandset
```

> Use the **psycopg3** URL format (`postgresql+psycopg://`). The older
> `postgresql+psycopg2://` is wrong for this project.

---

## 8. Project setup (venv + dependencies)

From the repository root:

```powershell
Set-Location "C:\Users\DELL\Downloads\Meta Audit"

# Create and sync the environment from pyproject.toml + uv.lock.
# The `dev` dependency group is installed by default -- no --extra flag.
uv sync
```

Verify:

```powershell
uv run python -c "import fastapi, sqlalchemy, alembic, pydantic; print('backend deps OK')"
uv run python -c "import app; print('app package OK', app.__version__)"
```

### Windows path note

The virtualenv lives at `.venv\Scripts\`, **not** `.venv/bin/`.

```powershell
# Windows
.\.venv\Scripts\python.exe -c "print('ok')"
```

> Skills and documentation written for Linux/macOS use `.venv/bin/python`.
> On this machine that path does not exist. Translate, do not copy.

---

## 9. Running things (current state, verified)

Everything below actually runs today. There is no one-command deployment: `docker-compose.yml`
defines **PostgreSQL only**, and the backend, worker and frontend each start from the host.

### 9.1 Database and schema

```powershell
docker compose up -d postgres     # the only compose service
docker compose ps                 # wait for healthy
uv run alembic upgrade head       # 0011_api_search_indexes is head
uv run python scripts/check_db.py # confirms reachable AND migrated
```

### 9.2 Optional demo data

```powershell
uv run python scripts/seed_demo.py
```

Drives one real collection through the real pipeline against `MockProvider`: 1 competitor,
3 pages, 8 ads, 8 append-only snapshots, 8 media **references**, and 3 collection runs.

**It writes permanent rows.** `ad_snapshots` is append-only and refuses `UPDATE` and
`DELETE` (there are triggers), and `ads` is foreign-key blocked, so seeded rows cannot be
cleaned up afterwards. Several API tests assume an empty corpus and will fail while demo
rows are present. That is a known, recorded condition, not a broken setup.

### 9.3 API and worker

```powershell
uv run uvicorn app.main:app --reload --port 8000    # API, http://localhost:8000
uv run python -m worker                             # separate window
```

Five routes are served: `/ads`, `/ads/{id}`, `/ads/{id}/snapshots`, `/competitors`,
`/exports/ads.csv`. There is **no** `/healthz` and **no** authentication of any kind, so
anything that can reach port 8000 can read every stored ad. Keep it bound to localhost.

The worker claims jobs from the PostgreSQL queue and runs collection. With only
`MockProvider` available it will do nothing until `seed_demo.py` has enqueued work.

### 9.4 Frontend

```powershell
Set-Location frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api` to the backend on port 8000 and strips
the prefix, so the browser only ever makes same-origin calls -- which is why the backend
needs no CORS configuration. Other scripts: `npm run build` (typecheck + production build),
`npm run preview`, `npm test`.

### 9.5 What is not available

No `/healthz`. No authentication. No media bytes are ever served, because none are
acquired. No real Meta provider, so nothing here reaches facebook.com.

---

## 10. Environment variables

```powershell
Copy-Item .env.example .env
```

`.env` is gitignored. **Never commit it.** `.env.example` holds safe
placeholders only and documents every supported variable.

---

## 11. Tests

```powershell
# Backend suite. Needs the Docker daemon, because the DB tests use testcontainers.
uv run pytest

# By marker
uv run pytest -m unit
uv run pytest -m contract
uv run pytest -m integration     # needs the Docker daemon + Postgres

# Lint / format / types
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

> The `-m smoke` marker runs real-data collection against live Meta. It
> requires explicit human approval every time. Never run it unattended.

---

## 12. Line endings

Keep source files at LF to avoid noisy diffs across Windows and containers.
This is enforced by the committed `.gitattributes` (`* text=auto eol=lf`).

Check your local Git is not fighting it:

```powershell
git config core.autocrlf false
git check-attr text eol -- pyproject.toml   # expect: text: auto, eol: lf
```

---

## 13. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `python3` opens the Microsoft Store | Store execution alias | Use `python`, not `python3` |
| `uv` not recognised after install | `PATH` not refreshed | Close and reopen PowerShell |
| `docker info` fails, `docker --version` works | Daemon stopped | Start Docker Desktop, wait, retry |
| `'Meta' is not recognised` | Unquoted path with a space | Always quote: `"C:\Users\DELL\Downloads\Meta Audit"` |
| `ModuleNotFoundError: No module named 'app'` | Wrong directory or env not synced | Run from repo root, then `uv sync` |
| `.venv\bin\python` not found | POSIX habit | Windows path is `.venv\Scripts\python.exe` |
| Connection refused on port 5432 | DB container not running | `docker compose up -d postgres` |
| `could not translate host name` in compose | Unquoted bind mount path | Quote every bind-mount path |

# PROJECT_MEMORY

## 2026-09-30, Checkpoint 0 (research + architecture)
Completed: REPOSITORY_RESEARCH.md, DATA_ACCESS.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md.
Decisions: vertical slice first; Apify optional; provider + AI abstractions; append-only snapshots; Postgres as queue;
"LONG-RUNNING SIGNAL" instead of winner labels; no spend numbers in slice 1.
Findings: official Meta API does not serve India commercial ads; only 1 of 6 repos is a real reference architecture; steadyfetch/n8n-templates has no license (reference only); the tracker's collector uses reverse-engineered GraphQL.
Known limitations: nothing tested against live Meta; sandbox cannot reach Meta/Apify; provider terms risk unresolved.
Open: D1, D2, D3, AI key choice, sample Page URL.
Next: S0-S3 (no live network needed), then S4 real-data run on user's machine.

## 2026-09-30, Checkpoint S0.1 (repository + governance foundation)

Created (13 new files): `AGENTS.md`, `SETUP_WINDOWS.md`, `README.md`, `.gitignore`, `.gitattributes`,
`.env.example`, `pyproject.toml`, `backend/app/{__init__,main}.py`, `backend/app/{api,core,db,models,
schemas,services}/__init__.py`, `backend/tests/__init__.py`, `worker/{__init__,__main__}.py`.
Existing docs were NOT modified, moved, renamed, or duplicated.

Decisions confirmed this checkpoint (approved by user, now binding):
- S0-S3 is the authoritative checkpoint structure. `IMPLEMENTATION_PLAN.md` still lists the older S0-S8
  milestone table; it is SUPERSEDED but was deliberately left unedited. Mapping recorded in AGENTS.md and
  here rather than silently rewriting the plan.
- Two independent provenance axes: `data_origin` (official_api|public_ui|third_party|user_import) and
  `evidence_class` (VERIFIED_PUBLIC_DATA|PROVIDER_DATA|ESTIMATE|AI_INTERPRETATION). Never collapsed.
- No login UI in S0-S3; auth stays a future seam. No media byte downloads in S0-S3.
- Docker Desktop + PostgreSQL 16 is primary; native Postgres is the documented fallback.
- `uv` is the approved package manager. Never global pip.
- Strict no-bypass data access rules, written into AGENTS.md section 5.
- Postgres-as-queue is now explicitly behind a `JobQueue` Protocol so the queue stays replaceable
  (this tightens the earlier "Postgres as queue" decision from Checkpoint 0).

Validated: git repo initialized, NO remote added, no push. pyproject.toml parses (7 runtime + 6 dev deps,
zero forbidden deps). `import app` OK and all 7 subpackages import OK. `python -m worker` runs and exits 0
as an intentional no-op. .gitignore verified against 11 must-ignore and 13 must-track paths. Secret scan
over staged content clean; `.env` absent and untracked. `.gitattributes` added to force LF.

Tooling status: Python 3.12.10 OK. Node v24.19.0 / npm 11.19.0 OK. Git 2.56.0 OK. Docker CLI 29.8.0 and
Compose v5.5.1 present BUT THE DOCKER DAEMON IS NOT RUNNING (Docker Desktop not started) - not usable yet.
`uv` IS NOT INSTALLED - required before any `uv sync`. `python3` does not work on this machine (Store
alias stub); use `python`. `py` resolves to 3.14.3, wrong version.

Git status: initial commit only, on the default branch, no remote, nothing pushed. Repo-local
`user.name`/`user.email` were unset and had to be set to a placeholder to commit - CHANGE THESE to the
real identity before ever pushing.

Known limitations: `import app.main` FAILS until dependencies are installed (fastapi not present). No
uv.lock yet, so installs are not yet reproducible. No tests exist yet (first arrive S1.1). No
docker-compose.yml yet (arrives S0.2). No database, no migrations, no providers, no AI, no frontend.
Nothing has been tested against live Meta.

Open / needs human decision before S0.2: install `uv`; start Docker Desktop or accept the native
Postgres fallback; set a real git identity.

Next checkpoint: S0.2 (config + logging + SQLAlchemy base + Alembic + Postgres + interfaces). NOT started.

## 2026-09-30, Checkpoint S0.1 remediation (close review findings)

**S0.1 remediation complete.** Scope was strictly the five required fixes from the S0.1
review. S0.2 was NOT started. No database, migrations, compose services, providers, AI,
frontend, auth, media or video code was added. The S0.1 entry above is left intact as a
historical record; this addendum corrects the facts in it that had since gone stale.

Fixes made (5 files changed, 23 insertions, 17 deletions):
1. `PROJECT_MEMORY.md` - this addendum. Corrects the stale tooling/git facts below.
2. `SETUP_WINDOWS.md` - status table now records `uv` 0.12.21 installed and the Docker
   daemon RUNNING (ServerVersion 29.8.0, verified with `docker info`). Also corrected the
   two stale status claims inside the instruction sections (section 3 `uv`, section 6
   Docker). All setup and verification instructions were left intact; no tooling status
   was invented.
3. `pyproject.toml` - added `extend-exclude = ["*.md"]` under `[tool.ruff]`. Ruff 0.16
   formats Python code blocks inside Markdown, so `ruff format .` would have rewritten
   `ARCHITECTURE.md` and other protected governance documents. No other Ruff rule changed.
4. `.gitignore` - removed the bare `storage/` line. Git cannot re-include a file when a
   parent directory is excluded, so that line silently made `!storage/.gitkeep` and
   `!storage/README.md` dead. Replaced with a comment recording why it must not return.
5. `worker/__main__.py` - removed the duplicate `print(...)` placeholder, kept
   `logger.info(...)`. No structured logging was built; S0.2 owns that.

Facts resolved since the S0.1 entry was written (each re-verified on this machine):
- `uv` 0.12.21 IS installed and working at `C:\Users\DELL\.local\bin\uv.exe`.
- FastAPI and the backend dependencies ARE installed (fastapi 0.142.2, uvicorn 0.54.0,
  sqlalchemy 2.0.54, alembic 1.20.0, pydantic 2.13.5, pydantic-settings 2.15.0,
  psycopg 3.3.6). The earlier "import app.main FAILS" note is no longer true.
- `uv.lock` EXISTS and is committed. `uv lock --check` passes, so installs are reproducible.
- The **Docker daemon is RUNNING** (ServerVersion 29.8.0), not stopped.
- Prerequisite "install `uv`" is RESOLVED. Prerequisite "start Docker Desktop" is RESOLVED.
- Latest commit before this remediation was `dc3acc4` (2 commits at that point).
- Remediation commit hash: see the follow-up line appended under this entry.

Validation run after the five fixes (all passed):
- `ruff check .` -> All checks passed, exit 0. (Was exit 1 on S0.1: T201 print.)
- `ruff format --check .` -> 11 files already formatted, exit 0. Previously it wanted to
  reformat `ARCHITECTURE.md`; the 10 Markdown files are now out of ruff's scope.
- `uv lock --check` -> exit 0, 52 packages resolved, lock still consistent with pyproject.
- `uv run python -c "import app.main"` -> OK, exit 0.
- `uv run python -c "import worker"` -> OK, exit 0.
- `uv run mypy` -> Success, no issues in 8 source files, exit 0 (no type regression).
- `uv run python -m worker` -> exit 0. Note: it is now SILENT on the console, because the
  `print` was removed and `logger.info` has no handler configured until S0.2. Expected.
- `git diff --check` -> clean, no whitespace errors and no conflict markers.
- `.gitignore` storage behaviour verified with `git check-ignore`:
  `storage/.gitkeep` and `storage/README.md` are COMMITTABLE again, while `storage/photo.jpg`
  and `storage/media/x.mp4` remain ignored.
- Only 4 non-memory files were modified. No unrelated file changed. Nothing was deleted.

Known limitations carried forward (unchanged by this remediation): no tests exist yet
(pytest still exits 5, EXIT_NOTESTSCOLLECTED, by design until S1.1); no docker-compose.yml,
no database, no migrations, no providers, no AI, no frontend; nothing has been tested
against live Meta. Open review items deferred on purpose and NOT fixed here (they are not
blockers): unauthenticated `/docs` and `/openapi.json` in `backend/app/main.py` should be
gated on `app_env` in S0.2; `.ruff_cache` writes fail with os error 5 (ACL/AV interference,
cache is gitignored); the detailed S0-S8 -> S0-S3 step mapping is still not written into
any file.

Git status: no remote configured, nothing pushed, nothing staged from outside this
checkpoint. The repo-local `user.name`/`user.email` are still the placeholder identity set
during S0.1 - CHANGE THESE to a real identity before ever pushing.

Next checkpoint: S0.2 (config + logging + SQLAlchemy base + Alembic + Postgres +
AdDataProvider/AIProvider/MediaStore/JobQueue interfaces). NOT started. Requires explicit
human approval.

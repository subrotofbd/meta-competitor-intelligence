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

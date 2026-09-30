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
- Remediation commit: `7c2040e` "fix: close S0.1 review findings" (5 files, +90/-17).
  It could not contain its own hash, so it is recorded here in this follow-up commit.

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

---

## Checkpoint S0.2 -- Configuration + Database Foundation (COMPLETE)

Approved and built. Configuration, structured logging, PostgreSQL 16 and Alembic all work.
`pytest` no longer exits 5: the suite now has 56 tests.

### Files created (17)

Runtime:
- `backend/app/core/config.py` -- `Settings` (pydantic-settings), `AppEnv`/`LogLevel`/`LogFormat`,
  cached `get_settings()`.
- `backend/app/core/logging.py` -- `configure_logging()`, `run_id_context()`, `get_run_id()`,
  `StructuredFormatter`, private `_RunIdFilter`. Standard library only.
- `backend/app/db/base.py` -- `Base(DeclarativeBase)` with the constraint naming convention.
- `backend/app/db/session.py` -- `get_engine()`, `get_session_factory()`, `session_scope()`,
  `get_session()` (FastAPI dependency), `dispose_engine()`, `check_database()`.
- `docker-compose.yml` -- PostgreSQL 16 only.
- `alembic.ini`, `database/migrations/env.py`, `database/migrations/script.py.mako`,
  `database/migrations/versions/0001_pg_trgm.py`.
- `scripts/check_db.py` -- read-only connectivity check.

Tests:
- `backend/tests/conftest.py`, `test_config.py`, `test_logging.py`, `test_db_base.py`,
  `test_db_session.py`, `test_migrations.py`, `test_db_integration.py`.

### Files modified (1)
- `.env.example` -- trimmed to ONLY the 9 variables S0.2 actually introduces. The S0.1 version
  already advertised provider, AI, media, auth and job-queue variables that no code reads yet;
  those are removed and will return with the checkpoint that implements them. Added the
  `POSTGRES_*` block that docker compose consumes. `.env` itself was created locally (gitignored)
  with a random 28-character password.

NOT modified: `main.py`, `AGENTS.md`, `ARCHITECTURE.md`, `DATA_ACCESS.md`,
`IMPLEMENTATION_PLAN.md`, `REPOSITORY_RESEARCH.md`, `SETUP_WINDOWS.md`, `pyproject.toml`,
`uv.lock`, `.gitignore`, `.gitattributes`, `README.md`.

### Database setup
- Container `metaaudit-postgres-1`, image `postgres:16-alpine`, server **PostgreSQL 16.15**,
  status **healthy**. Named volume `brandset_pgdata`. Host port 5432.
- No bind mounts anywhere in the compose file, so the space in `C:\Users\DELL\Downloads\Meta Audit`
  is a non-issue for Docker. Compose derived the project name `metaaudit` from the spaced directory.
- `POSTGRES_PASSWORD` uses `${POSTGRES_PASSWORD:?...}` -- compose REFUSES to start without it
  rather than falling back to a guessable default. No password is hardcoded anywhere.

### Migration result
- Revision **`0001_pg_trgm`**, `down_revision = None`. Single head, no branches.
- `alembic current` -> `0001_pg_trgm (head)`; `alembic heads` -> `0001_pg_trgm (head)`.
- `pg_trgm` 1.6 verified installed via `pg_extension`.
- The migration creates NO tables. S0.2 forbids domain tables, so the whole database foundation is
  the extension: `ARCHITECTURE.md` puts ad search on `tsvector` + `pg_trgm`, and the extension must
  exist before the first GIN trigram index in S1.1. `downgrade()` exists and drops it.

### Validation results (all re-run on the final tree)
- `uv lock --check` -> exit 0, 52 packages, `uv.lock` unchanged.
- `uv run ruff check .` -> All checks passed, exit 0.
- `uv run ruff format --check .` -> 25 files already formatted, exit 0.
- `uv run mypy backend/app` -> Success, no issues in 12 source files, exit 0.
- `uv run pytest -q` -> **56 passed**, exit 0.
- `uv run pytest -q -m "not integration"` -> 50 passed, 6 deselected. Unit suite needs no Docker.
- `docker compose config -q` -> exit 0. `docker compose ps` -> healthy.
- `uv run python scripts/check_db.py` -> exit 0, emitted real JSON with a live `run_id`.
- `alembic upgrade head` -> exit 0, idempotent on re-run.
- `git diff --check` -> clean.

### Findings raised and fixed DURING S0.2 (worth remembering)
1. **Pydantic echoed the database password in validation errors.** `SecretStr` masked `repr()`
   and `str()`, but a rejected DSN still printed the raw input inside the `ValidationError`,
   which reaches startup logs and bug reports. Fixed with `hide_input_in_errors=True` in
   `model_config`; pinned by `test_rejection_message_does_not_echo_the_password`.
2. **pytest rebinds the streams of existing `StreamHandler`s via `setStream()`.** The original
   logging tests monkeypatched `sys.stdout`, which pytest silently discarded -- 10 tests failed
   for a reason that had nothing to do with the code. Fixed properly by giving
   `configure_logging()` an explicit `stream` parameter instead of global patching.
3. **`assert _session_factory is not None` with `# noqa: S101`** in `db/session.py` was a smell,
   and the noqa itself would have tripped RUF100 since S101 is ignored project-wide. Removed by
   dropping the second global entirely: the session factory is rebuilt from `get_engine()` per
   call, so the factory can never outlive its engine.
4. Removed the `_scheme_of()` module-level helper in favour of an inline `partition`, and removed
   the blanket `import sqlalchemy as sa` from `script.py.mako` (it made ruff flag F401 on every
   generated migration that did not use it).
5. `path_separator = os` added to `alembic.ini` to clear a `DeprecationWarning` about legacy
   path splitting.

### Security review (secure-code-guardian)
- `database_url` is a `SecretStr`; asserted absent from `repr(settings)` and `str(settings)`.
  `.env` is gitignored (verified with `git check-ignore`); `.env.example` holds placeholders only.
- No f-string, `%` or `.format()` SQL anywhere. Every statement is a literal passed to `text()`;
  the one parameterised query (`pg_terminate_backend`) uses a bound `:pid` parameter.
- `scripts/check_db.py` logs the exception TYPE only, never the message and never `exc_info`,
  because a connection error can carry the DSN.
- Prod safety guard refuses to start with `log_level=DEBUG` or `database_echo=true`.
- `alembic.ini` and every migration file are asserted to contain no database URL.
- Residual risk, not fixed: `docker compose config` prints the RESOLVED password to stdout. That
  is inherent to compose. Do not paste its output into a bug report or a ticket.
- Residual risk, not fixed: a SQLAlchemy driver-load failure could include the DSN in its own
  exception text. Not reachable with psycopg installed.

### Known limitations
- **NO S0.3 CODE EXISTS.** Verified by grep: `AdDataProvider`, `AIProvider`, `MediaStore`,
  `JobQueue`, `MockProvider`, `DataOrigin`, `EvidenceClass` and the typed provider errors have
  zero implementations. The only textual matches are pre-existing S0.1 `__init__.py` docstrings
  describing those boundaries.
- `alembic downgrade` is implemented but was NEVER EXECUTED. It issues a `DROP`, and the
  checkpoint rules forbid running a destructive command without explicit approval. Reversibility
  is asserted structurally (`test_every_revision_is_reversible`), not by execution.
- Integration tests are hard failures when PostgreSQL is down, never skips. A skip is
  indistinguishable from a pass, and this project does not report unverified work as green.
- `.env.example` deliberately carries no provider/AI/media/auth/queue variables yet.
- `mypy` covers `backend/app` only (scope set in S0.1). Running it over `backend/tests` and
  `scripts` surfaces 4 false positives from pydantic-settings' undocumented `_env_file` keyword
  and SQLAlchemy's untyped `CreateTable.compile`. Not a gate; revisit if the scope is widened.
- STILL OPEN from the S0.1 review: `backend/app/main.py` serves `/docs`, `/redoc` (via
  `docs_url`) and `/openapi.json` unauthenticated. It was flagged to be gated on `app_env` in
  S0.2 but was deliberately NOT changed, because S0.1 code was out of scope for this checkpoint.
  Three unauthenticated routes remain. Gating them is a 3-line change whenever approved.
- `.ruff_cache` writes still fail with os error 5 (ACL/AV interference); the directory is
  gitignored, so there is no repo impact. Expect it before wiring CI.
- `postgres:16-alpine` is pinned to the MAJOR version only. The patch is 16.15 today; a minor
  bump will pull a new server patch. Pin the digest if reproducibility ever matters.
- The repo-local git identity is STILL the placeholder `Brandset Dev <dev@brandset.local>`.
  Change it before ever pushing.
- No remote configured. Nothing pushed. Nothing merged.

### Next checkpoint: S0.3
`AdDataProvider` and `AIProvider` Protocols, `MediaStore`, `JobQueue`, the `DataOrigin` /
`EvidenceClass` enums, the typed provider errors (`RateLimited`, `Blocked`, `SchemaChanged`,
`Transient`), and the first-class `MockProvider` -- all with no external network access.
NOT started. Requires explicit human approval.

Also worth deciding at or before S0.3: whether to gate the FastAPI docs routes on `app_env`.

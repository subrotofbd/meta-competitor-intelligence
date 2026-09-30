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

---

## 2026-09-30, Checkpoint S0.3 -- Provider + AI + Media + JobQueue Interfaces (COMPLETE)

Started on explicit human approval. Fully offline: no Meta, Facebook, Instagram, Apify, OpenAI
or Gemini was contacted, and no HTTP client is installed or imported anywhere in `backend/app`.

### Files created (24)

**Application (12)**
- `backend/app/providers/__init__.py` -- package charter for the two provider seams.
- `backend/app/providers/data/__init__.py`
- `backend/app/providers/data/provenance.py` -- `DataOrigin`, `EvidenceClass`, `evidence_class_for()`.
- `backend/app/providers/data/errors.py` -- `ProviderError` + `RateLimited` / `Blocked` /
  `SchemaChanged` / `Transient`.
- `backend/app/providers/data/models.py` -- `RawPayload`, `HttpUrl`, `AdFormat`, `PageRef`,
  `MediaRef`, `RawAdRecord`, `ProviderCapabilities`, `RequestMeta`, `CostEstimate`,
  `ProviderResult`, `CanaryResult`.
- `backend/app/providers/data/base.py` -- the `AdDataProvider` Protocol.
- `backend/app/providers/data/mock.py` -- `MockBatch`, `MockPage`, `MockProvider`.
- `backend/app/providers/ai/__init__.py`
- `backend/app/providers/ai/models.py` -- `Confidence`, `CopyAnalysisRequest`, `CopyAnalysis`.
- `backend/app/providers/ai/base.py` -- the `AIProvider` Protocol.
- `backend/app/providers/ai/mock.py` -- `MockAIProvider`.
- `backend/app/services/media.py` -- `content_key`, `content_key_for`, `StoredAsset`,
  `MediaStore` Protocol, `LocalFsStore`.
- `backend/app/services/jobs.py` -- `JobRequest`, `ClaimedJob`, `JobQueue` Protocol,
  `JobQueueUnavailable`, `PostgresJobQueue`.
- `backend/app/composition.py` -- the composition root (`build_ad_provider`, `build_ai_provider`).

**Tests and fixtures (10)**
- `backend/tests/_ast_probe.py` -- shared AST/import probes for the boundary tests.
- `backend/tests/fixtures/ad_provider/corpus.json` -- the sanitized ad corpus.
- `backend/tests/fixtures/ai/analyses.json` -- English, Hindi/Hinglish and sparse analyses.
- `backend/tests/test_provenance.py`, `test_provider_contracts.py`, `test_provider_errors.py`,
  `test_mock_provider.py`, `test_ai_provider.py`, `test_media_store.py`, `test_job_queue.py`,
  `test_architecture_boundaries.py`, `test_offline_guard.py`, `test_fixture_safety.py`.

### Files modified (3)
- `backend/tests/conftest.py` -- **purely additive** (+97/-0). S0.3 fixtures: `fixed_clock`,
  `mock_pages`, `mock_analyses`, `ad_provider`, `ai_provider`, `no_network`.
- `backend/tests/test_config.py` -- one line. A `# noqa: S106` became redundant once the ruff
  per-file-ignore started working (see findings); replaced with a comment keeping its intent.
- `pyproject.toml` -- three fixes, each required by S0.3 (see findings).

### Database
**No migration. No schema change. No new table.** `alembic heads` is still `0001_pg_trgm` and
`database/migrations/versions/` still holds exactly one file. S0.3 is interface-only, and the
checkpoint brief forbade a migration unless an interface demanded one.

### Design decisions worth keeping
- **`retryable` is a class attribute on `ProviderError`, not an `isinstance` chain.** One flag
  tells orchestration whether a failure may be retried. Adding a fifth failure mode later
  cannot fall through as "unknown, ignore". `Blocked` and `SchemaChanged` are `False`, which
  the tests assert directly.
- **`RawPayload` is the only untyped value in the contract.** A provider's response is
  genuinely opaque; it is hashed and stored before parsing. Every field the product *uses* is a
  declared, validated, frozen model field.
- **A provider's own `ad_status` is kept, untranslated.** `provider_active` is a domain status
  decided later from our own complete runs, not a copy of the provider's wording. A test asserts
  `RawAdRecord` has no `current_status`, `first_seen_at`, `content_hash`, `copy_hash` or
  `creative_hash` field -- that is the AGENTS.md section 8 merge, made mechanically detectable.
- **URLs are validated at the boundary** (`http`/`https` only, on `PageRef.url`,
  `RawAdRecord.destination_url` and `MediaRef.source_url`). These URLs are fetched by a later
  checkpoint; a provider could otherwise hand back `file:///etc/passwd`. Tested with 5 hostile
  schemes.
- **`LocalFsStore.put` refuses bytes that do not hash to the given key.** Content addressing was
  previously only intended; a caller could have filed different bytes under an existing key and
  every later `creative_hash` comparison would have become a comparison of lies. The store takes
  bytes and never a URL, so it structurally cannot fetch.
- **`PostgresJobQueue` is a fail-closed boundary, not a working queue.** S0.3 adds no migration,
  so every operation raises `JobQueueUnavailable` naming S1.2. It is not a stub waiting to be
  filled in on spec: a queue designed before the consumer exists is designed against imagined
  requirements. Its one real behaviour is validating the table name, which matters because SQL
  cannot bind a table name as a parameter.
- **`MockProvider` and `MockAIProvider` take their corpus by constructor injection.** Neither
  reads a file, opens a socket, or consults a clock of its own. Fixtures live in
  `backend/tests/fixtures/` where they belong, and the mocks are usable unchanged from a script.
- **`MockProvider.origin` is `third_party`**, so mock data resolves to `PROVIDER_DATA` and can
  never be badged `VERIFIED_PUBLIC_DATA`. Tested.
- **`serves_commercial_ads` is a required field of `ProviderCapabilities`**, with no default.
  Meta's own API does not serve Indian commercial ads; a provider must declare that rather than
  return empty pages forever.
- **The composition root was added although the brief did not list it.** Without a single wiring
  point, "MockProvider is a first-class provider" and "concrete providers are imported only from
  the root" are both unfalsifiable. It is 2 functions, each annotated as returning the *Protocol*
  so a caller cannot reach through to the concrete type. A test reads the annotations.
- **`ad_status` naming kept from the brief; field renamed to `display_format`** to avoid
  shadowing the `format` builtin, since it is the ad's creative shape.

### MockProvider corpus (9 records, 3 pages, 6 batches, 100% synthetic)
| Page | Records | What it covers |
|---|---|---|
| `mock-page-0001` Aurora Kitchen Studio (IN) | 4 over 3 batches | 1 image ad, 2 video ad, 3 carousel ad (3 media), 5 varied dates, 6 `facebook`/`instagram`/`messenger`, 7 `IN`+`GB`, 8 distinct landing pages, 10 **same ad id re-served with changed copy** |
| `mock-page-0002` Northwind Fitness Club (GB) | 3 over 2 batches | 6 `audience_network`, 7 `GB`+`IE`, 8 second landing page, 9 **repeated creative** (`mock-media-shared-01` on two ads), plus a sparse record with an unmodelled `DYNAMIC` format |
| `mock-page-0003` Coastal Ayurveda (IN/US) | 2 over 1 batch | 7 `IN`+`US`, 4 copy variations, unmodelled `experiment_variant` preserved, one ad with no media and no `link_description` |

All ten required scenarios have a **named** test each (`test_scenario_01_image_ad` ...), so a
fixture edit that removes one fails loudly. Scenario 10 is deliberate: the same `external_ad_id`
served twice with different copy within one cursor walk is exactly the input the append-only
snapshot logic needs in S2.1, and the provider returns what it saw without judging it.
Every host is `example.invalid` (RFC 2606, cannot resolve). No real Page ID, Ad ID, or token.

### MockAIProvider summary
Keyed by `copy_hash` (the same key results are deduplicated on in storage), injected at
construction. Three stored analyses: English (`en`, 15/16 fields, `urgency` left `null`
because the copy claims no urgency), Hindi/Hinglish (`hi`, 14/16, analysed in Hindi with the
English summary alongside), and a sparse case (0/16). An unknown `copy_hash` returns
`CopyAnalysis()` -- fourteen nulls, not a generated sentence. A test asserts the field set
contains **no** performance field (`spend`, `revenue`, `roas`, `leads`, `conversions`,
`reach`, `impressions`, `clicks`, `ctr`, `performance`), so one cannot be added by accident.

### Validation results (all re-run on the final tree)
| Gate | Command | Result |
|---|---|---|
| Lock | `uv lock --check` | exit 0, 52 packages, `uv.lock` **unchanged** |
| Lint | `uv run ruff check .` | **All checks passed** |
| Format | `uv run ruff format --check .` | 50 files already formatted |
| Types | `uv run mypy backend/app` | Success, no issues, 26 source files |
| Tests | `uv run pytest -q` | **287 passed** (was 56 in S0.2) |
| Tests, no Docker | `uv run pytest -q -m "not integration"` | 281 passed, 6 deselected |
| Compose | `docker compose config -q` | exit 0 |
| Migrations | `uv run alembic heads` | `0001_pg_trgm (head)`, single head, no new file |

New S0.3 tests: **231** (287 total - 56 carried from S0.2). The 6 integration tests are the
unchanged S0.2 live-PostgreSQL tests; container `metaaudit-postgres-1` healthy, PostgreSQL 16.15.

### Offline / network guard
`backend/tests/test_offline_guard.py` -- 6 tests, all pass. The `no_network` fixture replaces
`socket.socket`, `socket.create_connection` and `socket.getaddrinfo` with functions that raise
`AssertionError`. `test_the_guard_actually_blocks_sockets` proves the guard bites before the
rest of the suite relies on it, then the ad provider, a full cursor walk, the AI provider and
`LocalFsStore` all run underneath it. A static half proves there is no code to call: no module
under `backend/app/providers/` imports `socket`, `ssl`, `http`, `httpx`, `requests`, `urllib`,
`urllib3` or `aiohttp`, and the mocks additionally import no database and no filesystem module.

### Security review (secure-code-guardian)
- No secrets in source. Swept `providers/`, `services/` and `composition.py` for
  `password|secret|api_key|access_token|Bearer|EAA` -- zero hits. Fixtures swept separately.
- Provider output is treated as untrusted at the boundary: `extra="forbid"` on every contract
  model, `http(s)`-only URLs, timezone-aware datetimes required, and an `AdFormat` a provider
  does not use becomes `null` with the original wording preserved.
- No shell execution anywhere: swept for `subprocess`, `os.system`, `popen`, `eval`, `exec` --
  zero hits.
- No string-built SQL: swept for `text(f`, `execute(f`, `.format(` -- zero hits.
- The only new SQL-adjacent surface is the queue's configurable table name, validated as a bare
  lowercase identifier before it can reach SQL. Tested against 9 hostile values including
  `jobs"; DROP TABLE ad_snapshots; --`.
- Filesystem writes go through exactly one choke point, `LocalFsStore._path_for`, which
  validates the key as 64 lowercase hex before building a path. Traversal, absolute paths,
  drive letters and URL-shaped keys are all refused; tested.
- Fixture scanner rejects long numeric identifiers, non-reserved hosts, email addresses and
  credential words, and requires every id to be namespaced `mock-*`. 26 checks across 2 files.
- `ruff` includes `S` (bandit) and runs clean.

### Findings raised and fixed DURING S0.3
1. **The ruff `per-file-ignores` patterns never matched anything.** `"tests/**"` is matched
   against the path from the project root, and the tests live at `backend/tests/**`, so the
   ignore has been dead since S0.1. Corrected to `**/tests/**`. This immediately exposed a
   now-redundant `# noqa: S106` in an S0.2 test (RUF100), which was converted to a comment
   keeping its intent. Only that one line of S0.2 code was touched.
2. **`N818` (exceptions should end in `Error`) conflicts with the agreed contract.** The names
   `RateLimited`, `Blocked`, `SchemaChanged` and `Transient` are fixed by ARCHITECTURE.md and
   appear in run records operators read. Added a scoped per-file-ignore for `errors.py` and
   `jobs.py` with the reasoning in a comment, rather than renaming the contract. A new exception
   anywhere else still needs an `Error` suffix.
3. **`pytest`'s `pythonpath` does not cover a helper module beside the tests.** The shared AST
   probe could not be imported. Added `backend/tests` to `pythonpath`.
4. **`copy_hash` is required on `CopyAnalysisRequest` with no default.** Without it an
   `AI_INTERPRETATION` value cannot be traced back to the snapshot it came from, which
   AGENTS.md section 7 requires.
5. **Self-review (thermo-nuclear) restructured `_normalise`**, which had grown to 62 lines with
   six branches, into `_require_ad_id`, `_require_body`, `_read_media` and `_unmodelled_fields`,
   leaving the main function as a readable field-mapping table. Two boundary tests that grepped
   source text were replaced with exact `__module__` and AST-import checks, so reformatting a
   class declaration can no longer make them pass for the wrong reason.

### Known limitations
- **`PostgresJobQueue` cannot enqueue, claim, complete or fail anything.** It is a declared,
  fail-closed seam. S1.2 creates the table and implements it. This is deliberate, not an
  oversight, and it is the single weakest part of the checkpoint.
- **No real provider exists.** `MockProvider` is the only registered `AdDataProvider`. The S4
  data-access question (Apify vs manual import vs nothing) is unchanged and still open.
- **No AI model is configured and no SDK is installed.** `MockAIProvider` is the only
  `AIProvider`. Real adapters land in S3.
- **No media bytes are ever fetched or persisted by the application.** `LocalFsStore` can store
  and read bytes a caller hands it; nothing in `backend/app` calls it yet.
- **The `no_network` guard is opt-in, not autouse.** It has to be: the `integration` tests
  genuinely open a socket to the local PostgreSQL container, and a guard that blocked them
  would be a guard nobody could trust. Any future test that should be offline must request the
  fixture explicitly.
- **The AST boundary tests cover imports, not behaviour.** A provider that reached the database
  through some non-import route would pass them. The realistic route is an import.
- STILL OPEN from the S0.1 review: `backend/app/main.py` serves `/docs`, `/docs/oauth2-redirect`
  and `/openapi.json` unauthenticated. Still deliberately unchanged -- S0.1 code, and out of
  scope for S0.3. Three unauthenticated routes remain. Gating them is a 3-line change whenever
  approved.
- `alembic downgrade` is still never executed. It issues a `DROP`; the checkpoint rules forbid
  running a destructive command without explicit approval.
- `mypy` still covers `backend/app` only, not `backend/tests`. The S0.3 tests are therefore
  untyped-checked. Widening the scope would surface pydantic-settings' `_env_file` and other
  false positives, as recorded in S0.2.
- `.ruff_cache` writes still fail with os error 5; gitignored, no repo impact.
- The repo-local git identity is STILL the placeholder `Brandset Dev <dev@brandset.local>`.
- No remote configured. Nothing pushed.

### Next checkpoint: S1
`IMPLEMENTATION_PLAN.md` still carries the superseded S0-S8 milestone table; S0-S3 is the
authoritative structure (AGENTS.md section 1). S1.1 is the schema for slice 1: `users`,
`settings`, `audit_logs`, `competitors`, `facebook_pages`, `collection_runs`, `provider_runs`,
`raw_responses`, `ads`, `ad_snapshots`, `ad_creatives`, `media_assets`, `ad_platforms`,
`ad_countries`, `landing_pages` -- with the first real Alembic migration beyond `pg_trgm`, and
the search indexes (`tsvector` + `pg_trgm` GIN) that the extension was migrated for.
S1.2 is collection orchestration, which is where `PostgresJobQueue` becomes real.

NOT started. Requires explicit human approval.

### Git
Committed as `feat: establish provider and service contracts`. No remote added, nothing pushed.

---

## 2026-09-30, Checkpoint S1.1 -- Domain Schema Foundation (COMPLETE)

Approved by the user with the scope decision: **5 tables only — no identity (users/settings/audit_logs)**.
The 15-table note in the S0.3 entry is superseded; `users`/`settings`/`audit_logs` are deferred to a
post-S3 auth checkpoint and recorded here as a deliberate deferral, not an omission.

### Files created (3)
- `backend/app/models/mixins.py` -- shared schema vocabulary: `UuidId`, `UtcDateTime`,
  `ISO_ALPHA_2_CHECK`, `UuidPrimaryKeyMixin`, `TimestampMixin`, `CountryCodeMixin`,
  `not_blank()`, `at_most()`. Documents the autogenerate inline-check trap explicitly.
- `backend/app/models/tracking.py` -- `Competitor`, `FacebookPage`.
- `backend/app/models/runs.py` -- `CollectionRunStatus`, `ProviderRunStatus`,
  `_stored_enum()`, `CollectionRun`, `ProviderRun`, `RawResponse`.

### Files modified (4)
- `backend/app/models/__init__.py` -- rewritten as the S0.1 charter with per-checkpoint table
  assignment and the identity-trio deferral note. Re-exports that register tables on `Base.metadata`.
- `database/migrations/env.py` -- adds `from app import models` so autogenerate sees the tables.
- `backend/tests/conftest.py` -- adds `db_session` fixture: a session bound to a connection wrapped
  in an outer transaction that is always rolled back. Nothing is ever committed, so there is no
  cleanup `DELETE` to get wrong and no path by which a failing test can leave rows in the
  development database.
- `database/migrations/versions/0002_collection_domain.py` -- the single S1.1 migration,
  extending `0001_pg_trgm`.

### Database migration
- Revision **`0002_collection_domain`**, `down_revision = "0001_pg_trgm"`. Single linear head,
  no branches.
- `alembic current` -> `0002_collection_domain (head)`; `alembic heads` -> `0002_collection_domain (head)`.
- `alembic check` -> "No new upgrade operations detected." (exit 0) -- zero drift.
- `pg_trgm` 1.6 still installed and intact.
- `downgrade` renders complete, correctly ordered SQL offline without executing it: trigger dropped
  before function, tables dropped deepest-first, `alembic_version` updated to `0001_pg_trgm`.
  **Never executed** (issues `DROP`s; checkpoint rules require consent).

### Tables (5, exactly the S1.1 assignment)
| Table | Purpose | Key decisions |
|---|---|---|
| `competitors` | The tracked brand | Name non-blank, UUID PK, `created_at`/`updated_at` from DB clock |
| `facebook_pages` | A page a competitor owns | `page_id` unique **globally** (not per competitor), `url` http(s) or NULL, country ISO alpha-2 upper case, `tracking_frequency` free text |
| `collection_runs` | One attempt to collect one page in one country from one provider | **Owner of `provider` and `data_origin`** (not repeated below), status enum `pending/running/complete/partial/failed`, `records_returned >= 0`, `finished_at >= started_at` |
| `provider_runs` | One HTTP call inside a run | Status enum `running/succeeded/failed/blocked`, `request_meta` JSONB, `next_cursor`, `http_status 100..599`, cost triple all-or-nothing with method, `cost_amount >= 0`, `finished_at >= started_at` |
| `raw_responses` | The raw provider payload, before parsing | `provider_run_id` UNIQUE, `payload` JSONB (untyped), `payload_hash` **computed by a `BEFORE INSERT OR UPDATE` trigger** (not application, not generated column) |

### Constraints and design rules enforced
- **Single-parented chain, no ambiguous FKs:** `competitors -> facebook_pages -> collection_runs -> provider_runs -> raw_responses`. Every row has exactly one parent; a page belongs to one competitor; an ad cannot belong to two.
- **All FKs `ON DELETE RESTRICT`, no CASCADE anywhere** -- collected data cannot be re-acquired; deletion must be deliberate. Verified live: all 4 FKs `confdeltype='r'`.
- **`data_origin` and `provider` stored once on `collection_runs` only**; `provider_runs`/`raw_responses` inherit via FK. Prevents three copies that can disagree. `evidence_class` appears in **no S1.1 table** (no displayable collected values until S2.1). Deviation from ARCHITECTURE's parenthetical, documented.
- **`page_id` stored once, `UNIQUE(page_id)` is global** -- the per-composite version would let one page belong to two competitors, making every ad's competitor ambiguous.
- **Enums as `VARCHAR` + named `CHECK`** via `sa.Enum(..., native_enum=False, create_constraint=True, values_callable=...)` -- values not names (`official_api`, not `OFFICIAL_API`); one source of truth = Python `StrEnum`; extensible by ordinary migration.
- **No `cursor` column on `collection_runs`** -- a per-page run's resume point is exactly its last `provider_runs.next_cursor`; a second copy would be two values to keep in step.
- **`tracking_frequency` free text** -- scheduling is S1.2's decision.
- **`records_returned` is the only count** -- derivable counts are duplication; new/changed ads are S2.
- **All `CheckConstraint`s in `__table_args__`, never inline** -- Alembic autogenerate silently omitted every inline check while reporting no drift. Discovered by inspecting the generated migration; locked in by `test_every_check_constraint_is_visible_to_alembic`.
- **Timestamps:** `UtcDateTime = DateTime(timezone=True)`, `server_default=func.now()`; `updated_at` moves on ORM writes only (documented limitation).
- **`UuidId = Uuid(as_uuid=True)` shared alias** for PK and all FK columns (bare `ForeignKey` gives SQLAlchemy no type to infer -> `NullType` DDL error).
- **Model classes subclass `Base` from `app.db.base`** -- omitting it silently registers nothing.
- **`error_message` bounded to 2000 chars** via `at_most()`.

### Trigger for `payload_hash`
A `GENERATED ALWAYS` column was the obvious choice and **does not work**: PostgreSQL requires a generated expression to be immutable, and `jsonb::text` is not. A column `DEFAULT` referencing another column also fails: `cannot use column reference in DEFAULT expression`.

The migration creates `raw_response_payload_hash()` and `raw_responses_payload_hash_trg` (`BEFORE INSERT OR UPDATE`). Verified live:
- Computes on insert.
- Recomputes on payload mutation.
- 64 hex chars, reproducible via `encode(sha256(convert_to(payload::text,'UTF8')),'hex')`.
- Hash covers the *stored* form (jsonb normalises key order, whitespace, duplicate keys).

### Indexes (3, one per named access pattern)
| Index | Serves |
|---|---|
| `ix_facebook_pages_competitor_id` | GET /competitors/{id}/pages |
| `ix_collection_runs_facebook_page_id` | Latest run for a page and country (`not_seen_since` rule) |
| `ix_provider_runs_collection_run_id` | The calls belonging to a run |

**No composite `(page, country, started_at)` index** -- S2 writes the query and measures before an index is built for it.

### Test suite (3 new test modules, 164 S1.1-specific tests)
| Module | Scope |
|---|---|
| `backend/tests/test_models.py` | Unit/metadata: exactly 5 tables registered; scope guards against early `ads`; no business logic; provenance on one table only; no `evidence_class`; every FK RESTRICT; every table has UUID PK + timestamps; enum checks contain values; no column-level checks; indexes are exactly the 3 declared; `payload_hash` is plain `String(64)`; `payload` is JSONB untyped. |
| `backend/tests/test_schema_integration.py` | Integration (live PG, rollback-per-test session): migration applies + single head; pg_trgm intact; 5 tables exist; `compare_metadata` no diff; live checks == metadata checks; FK rejects orphan; deleting a competitor with a page refused; duplicate `page_id` refused globally; declared indexes exist; payload hash DB-computed 64 hex + reproducible in SQL; hash changes on payload mutation; payload round-trips losslessly (non-ASCII, nesting, list, numbers); timestamps DB-clock and tz-aware; `updated_at` moves on ORM update; unknown status/origin refused; country upper-case alpha-2; `finished_at` cannot precede `started_at`; `records_returned >= 0`; cost all-or-nothing; `http_status 100..599`; one raw response per provider run; downgrade SQL rendered offline. |
| `backend/tests/test_migrations.py` (updated) | Linear history assertion updated; DSN search tightened to `postgresql://` patterns. |

### Validation gates (all pass)
| Gate | Command | Result |
|---|---|---|
| Lock | `uv lock --check` | exit 0 |
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 56 files already formatted |
| Types | `uv run mypy backend/app` | Success, no issues in 29 source files |
| Unit tests | `uv run pytest -m unit -q` | 97 passed |
| Integration tests | `uv run pytest -m integration -q` | 67 passed |
| Full suite | `uv run pytest -q` | 398 passed |
| Migrations | `uv run alembic current` / `heads` / `check` | `0002_collection_domain (head)`, single head, zero drift |
| Compose | `docker compose config -q` | exit 0 |
| Compose ps | `docker compose ps` | healthy, PostgreSQL 16.15 |

### Thermo-nuclear code quality review (self-applied)
No findings:
- **No duplicated schema**: CHECK text duplicated between model and migration is inherent to Alembic (frozen historical record); migration cannot import from models without mutability.
- **No unnecessary wrappers**: `mixins.py` is 4 utilities; `_stored_enum` is the one place the enum mapping lives.
- **No business logic in models**: `test_models_declare_no_methods_or_properties` asserts 0 routines on all 5 mapped classes.
- **No giant files**: models split into `mixins.py`, `tracking.py`, `runs.py`; migration is one file.
- **FK ownership correct**: chain is single-parented, all RESTRICT.
- **No speculative tables**: exactly the 5 tables assigned to S1.1.
- **No migration duplication**: one migration extending `0001_pg_trgm`.
- **No index overengineering**: exactly 3 indexes for 3 named access patterns.
- **No cross-layer imports**: models import only `db.base`, `mixins`, `provenance` (enum source), `tracking` (for FK).

### Secure-code-guardian review (self-applied)
No findings:
- No credentials in migration (docstrings mention "password-hash" as future context, not a value).
- No secrets in fixtures (fixtures scanned; only mock `media.key` strings like `mock-media-0001-a`).
- No unsafe dynamic SQL: the two parametrised `text()` calls use table/column names from test parametrisation (code, not input) and bound parameters for all values.
- No sensitive values logged: no logging of payloads, credentials, or DSNs.

### Known limitations
- **Identity tables deferred**: `users`/`settings`/`audit_logs` do not exist. The S0.3 entry's "all 15 tables" note is superseded here. The deferral is deliberate and recorded.
- **`jobs` table is S1.2's deliverable** -- creating it now would be speculative and invoke `PostgresJobQueue` before it exists.
- **`evidence_class` does not exist in S1.1** -- arrives with `ads` in S2.1 where there is a value to qualify.
- **No state machine implemented** -- status vocabularies exist, but transitions are S1.2.
- **ORM `updated_at` only moves on ORM writes** -- a bulk raw `UPDATE` would not bump it; no code path does this today.
- **`alembic downgrade` never executed** -- issues `DROP`s requiring explicit consent. Reversibility asserted structurally + rendered offline only.
- **`docker compose config` prints the resolved password** to stdout -- never paste its output anywhere.
- **`.ruff_cache` writes fail with os error 5** -- gitignored, no repo impact.
- **`postgres:16-alpine` pins major only** -- 16.15 today.

### Open decisions needing human input
- Gate `/docs`, `/docs/oauth2-redirect`, `/openapi.json` on `app_env` in `backend/app/main.py` (3 lines, currently unauthenticated).
- Replace placeholder git identity `Brandset Dev <dev@brandset.local>` before any push.
- S4 real-data path: under strict no-bypass rules, `meta-ads-collector`-style collection is out of bounds. India commercial ads likely narrow to Apify or manual import. Open: D1 (aggressiveness), D2 (wrapper vs own client), D3 (do India commercial ads actually appear in the public library), plus AI key choice and a sample Indian Page URL.

### Next checkpoint: S1.2
Collection orchestration: `jobs` table + `PostgresJobQueue` implementation + the scheduler that enqueues per-page/country runs. The `collection_runs` schema was designed so a run is exactly what a `SKIP LOCKED` lease means. **Not started without explicit human approval.**

### Git
`git status` clean. Only S1.1 files changed (see above). `git diff --check` clean. Commit message:
`feat: establish collection domain schema`. No remote, no push.

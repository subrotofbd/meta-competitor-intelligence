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
analysis fields written in Hindi), and a sparse case (0/16). **There are no English summary
fields** -- S3.1 has one set of fields, in the copy's own language, and `language` records which.
This corrects an earlier entry in this same section, which wrongly said the Hindi fixture carried
"the English summary alongside"; that contradicted the locked D-A decision and no such field has
ever existed. English summaries, if ever wanted, are deferred to a future explicit
schema/version decision. An unknown `copy_hash` returns
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

---

## 2026-09-30, Checkpoint S1.2 -- Collection Orchestration + Durable Job Queue (COMPLETE)

Approved by the user. Implements the `jobs` table, the real `PostgresJobQueue` behind the existing
`JobQueue` Protocol, and the per-page/per-country collection orchestrator.

### Files created (3)
- `backend/app/models/jobs.py` -- `Job` model + `JobStatus` constants. Columns: `kind`, `payload` (JSONB),
  `status`, `worker_id`, `attempt`, `lease_expires_at`, `started_at`, `finished_at`, `error_message`,
  `error_type`. 6 check constraints, 3 indexes.
- `backend/app/services/collection.py` -- `CollectionOrchestrator` with `schedule_collection`,
  `execute_collection_job`, `_handle_provider_error`, `_persist_provider_run`, `get_run_status`,
  `get_run_error`. The service boundary for "collect this page in this country".
- `database/migrations/versions/0003_jobs_table.py` -- the S1.2 migration, extending `0002_collection_domain`.

### Files modified (8)
- `backend/app/models/__init__.py` -- exports `Job`; S1.2 noted in docstring.
- `backend/app/services/jobs.py` -- rewritten from fail-closed to real `PostgresJobQueue` with
  `enqueue`, `claim` (SKIP LOCKED), `complete`, `fail` (with optional `error_type`), `extend_lease`.
- `backend/app/composition.py` -- adds `build_job_queue`, `build_mock_pages`,
  `build_collection_orchestrator`.
- `worker/__main__.py` -- rewritten from no-op to job consumer loop.
- `backend/tests/test_job_queue.py` -- rewritten from fail-closed tests to 28 real queue tests.
- `backend/tests/test_schema_integration.py` -- S1.2 revision constants, lineage, downgrade tests.
- `backend/tests/test_models.py` -- `S1_TABLES` cumulative scope (S1.1 + S1.2).
- `backend/tests/test_db_base.py` -- checks S1.1+S1.2 metadata.
- `backend/tests/test_migrations.py` -- 3-revision chain.

### Database migration
- Revision **`0003_jobs_table`**, `down_revision = "0002_collection_domain"`. Single linear head.
- `alembic current` -> `0003_jobs_table (head)`; `alembic heads` -> `0003_jobs_table (head)`.
- `alembic check` -> "No new upgrade operations detected." (exit 0) -- zero drift.
- `downgrade` renders complete SQL offline without executing it. **Never executed** (issues `DROP`s).

### Queue semantics
- **Enqueue**: client-side UUID, `json.dumps(payload)` + `CAST(:payload AS JSONB)` for safe JSONB insertion.
- **Claim**: `SELECT ... FOR UPDATE SKIP LOCKED` -- two workers never claim the same row.
  A job is available if `status = 'pending'` OR (`status = 'running'` AND `lease_expires_at < now`).
- **Complete**: sets `status = 'completed'`, clears `worker_id` and `lease_expires_at`.
- **Fail**: sets `status = 'pending'` (retry) or `'dead'` (max attempts exceeded), records `error_message`
  and optional `error_type`.
- **Extend lease**: `UPDATE ... WHERE id = :job_id AND worker_id = :worker_id AND status = 'running'`.
  Returns `True` if extended, `False` if the job is no longer held by this worker.
- **Lease duration**: default 5 minutes, configurable via constructor.
- **Max attempts**: default 5, configurable via constructor.

### Concurrency guarantees
- `SELECT ... FOR UPDATE SKIP LOCKED` ensures two workers never claim the same job.
- A worker that dies mid-job releases its lease when its connection closes (PostgreSQL semantics).
- Lease expiration allows another worker to reclaim the job after `lease_expires_at` passes.
- Test `test_concurrent_workers_dont_share_jobs` proves 3 workers claiming from 20 jobs get no overlap.

### Orchestration flow
1. `schedule_collection(page_id)` creates a `collection_runs` row (PENDING) and enqueues a job.
2. Idempotency: if a PENDING/RUNNING run exists for the same page/country/provider, returns existing
   or re-enqueues instead of creating a duplicate.
3. Worker claims the job, calls `execute_collection_job(run_id)`.
4. Orchestrator marks the run RUNNING, calls the provider (cursor walk), persists each provider call
   as a `provider_run` + `raw_response` pair.
5. On success: run status = COMPLETE. On typed provider error: run status = FAILED with error_type.
6. Worker marks the job complete or failed based on the run status.

### Raw persistence ordering
- `_persist_provider_run` creates the `provider_run` row first, then the `raw_response` row.
- The raw payload is stored **before** any parsing/normalization (AGENTS.md section 8).
- `payload_hash` is computed by the database trigger, not the application.

### Retry/recovery behavior
- `fail()` returns the job to PENDING (retry) or DEAD (max attempts exceeded).
- `fail()` accepts an optional `error_type` for typed provider errors.
- A crashed worker's lease expires after `lease_expires_at`, allowing another worker to reclaim.
- `extend_lease()` allows a long-running worker to extend its lease before it expires.

### Validation gates (all pass)
| Gate | Command | Result |
|---|---|---|
| Lock | `uv lock --check` | exit 0 |
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 59 files already formatted |
| Types | `uv run mypy backend/app` | Success, no issues in 31 source files |
| Unit tests | `uv run pytest -m unit -q` | 97 passed |
| Integration tests | `uv run pytest -m integration -q` | 96 passed |
| Full suite | `uv run pytest -q` | **409 passed** |
| Migrations | `uv run alembic current` / `heads` / `check` | `0003_jobs_table (head)`, single head, zero drift |
| Compose | `docker compose config -q` | exit 0 |
| Compose ps | `docker compose ps` | healthy, PostgreSQL 16.15 |

### Thermo-nuclear code quality review (self-applied)
Findings fixed:
1. **`worker/__main__.py`**: Moved imports to module level; replaced private `_session` access with
   public `get_run_status()` / `get_run_error()` methods on the orchestrator.
2. **`collection.py`**: Collapsed 5 nearly identical exception handlers into one
   `_handle_provider_error()` helper with a type map.
3. **`jobs.py`**: Merged `fail_with_type` into `fail` with an optional `error_type` parameter,
   eliminating ~40 lines of duplication.

No remaining findings:
- No file crosses 1k lines (largest is `jobs.py` at ~370 lines).
- No business logic in models.
- No unnecessary wrappers or pass-through helpers.
- No spaghetti branching.
- No speculative abstractions.

### Secure-code-guardian review (self-applied)
No findings:
- All SQL uses bound parameters (`:id`, `:kind`, `:payload`, etc.). The table name is hardcoded
  `"jobs"` -- no injection surface.
- `json.dumps(job.payload)` serializes the payload to a JSON string before binding, preventing
  psycopg type adaptation errors.
- No secrets in source. No credentials in migrations.
- No shell execution. No string-built SQL.
- The `CAST(:next_status AS VARCHAR)` prevents psycopg `AmbiguousParameter` errors when the same
  parameter is used in both `SET` and `CASE` clauses.

### Accidental-data-loss-prevention review (self-applied)
No findings:
- Jobs are never deleted -- `fail()` returns them to PENDING or marks them DEAD.
- The `downgrade()` renders DROP statements but is **never executed** (requires explicit consent).
- Test fixture uses `DELETE FROM jobs` for isolation -- test-only, doesn't affect production data.
- No `DROP`, `TRUNCATE`, or broad `DELETE` in any migration `upgrade()`.

### Known limitations
- **No real provider exists.** `MockProvider` is the only registered `AdDataProvider`.
- **No normalizer yet.** S1.3 owns parsing/normalization of raw responses.
- **No snapshot state machine.** S2 owns `ad_snapshots`, `not_seen_since`, `presumed_inactive`.
- **No API endpoints yet.** The orchestrator is a service boundary; routes arrive with the API layer.
- **No authentication.** Post-S3 seam.
- **`alembic downgrade` never executed** -- issues `DROP`s requiring explicit consent.
- **`docker compose config` prints the resolved password** to stdout -- never paste its output.
- **`.ruff_cache` writes fail with os error 5** -- gitignored, no repo impact.
- **Repo-local git identity is still the placeholder** `Brandset Dev <dev@brandset.local>`.
- No remote configured. Nothing pushed.

### Next checkpoint: S1.3
Normalizer: parse raw provider responses into `RawAdRecord` models, validate, and persist.
The `raw_responses` table already stores the payload; S1.3 builds the parsing layer on top.
**Not started without explicit human approval.**

---

## S1.3 -- Provider Response Normalizer (NORMALIZER-ONLY)

### Scope decision, as instructed
S1.3 is **normalizer-only**. It is a pure, deterministic transformation from a provider payload to
`RawAdRecord` values. It does not persist, does not write files, and does not touch the database.
**Normalized ad persistence is deferred to S2.1**, which `ARCHITECTURE.md` and
`backend/app/models/__init__.py` already assign the `ads` and `ad_snapshots` tables to. This
checkpoint resolved the earlier blocker by narrowing itself rather than by inventing a table.

### What was built
- **`backend/app/providers/data/normalize.py`** (new) -- the single place a provider payload becomes a
  `RawAdRecord`. Two entry points: `normalize_record` (raises) and `normalize_payload` (partial
  success). Structured errors via `NormalizationErrorKind`, `NormalizationError`,
  `RecordRejectedError`, `NormalizationResult`.
- **`RawAdRecord` is reused from S0.3 unchanged.** No second competing ad record model was created.
- **`MockProvider` now delegates to the normalizer.** The old inline adapter (`_normalise`,
  `_require_ad_id`, `_require_body`, `_read_media`, `_unmodelled_fields`, `_as_str_tuple`,
  `_parse_datetime`, `_MAPPED_KEYS`, `_MAPPED_BODY_KEYS`, `_CREATIVE_BODY_KEY`) was deleted, so the
  provider-to-record mapping exists exactly once in the product. `MockProvider` keeps its
  all-or-nothing policy by mapping the structured error onto its existing `SchemaChanged` contract.
- **New fixture** `backend/tests/fixtures/normalizer/payloads.json`. Kept deliberately apart from the
  `MockProvider` corpus: that corpus is a *valid* response the provider serves whole, so malformed
  records in it would break the provider's contract on load.
- **New conftest fixture** `normalizer_payloads`. No other S1.2 file was touched.

### Behaviour worth remembering
- Absence is never filled in. The three absences stay apart: key absent -> the field's own default
  (`None` or `()`), key present and null -> `None`/`()`, key present and `""` -> `""`.
- Text keeps `""` because `str | None` can represent it. A URL or a timestamp cannot, so an empty
  string there reads as "not reported" rather than as a malformed value.
- Timestamps keep the provider's offset. A naive timestamp is **refused**, never assumed to be UTC --
  a guessed offset shifts a delivery start, and duration is displayed from that field.
- URLs are kept verbatim or refused. No scheme folding, no trailing-slash repair. Refused for
  non-http(s), for a control character (request-splitting payload), and for a missing host.
- Copy is never rewritten, translated, transliterated or trimmed. Hindi/Hinglish survives verbatim.
- Unmodelled provider fields are kept in `provider_metadata`, including an unrecognised `format`
  (so a `None` never looks like "the provider reported nothing"). On a record/body key collision the
  **record-level key wins**, which is a decision now documented rather than accidental.
- Duplicate ad ids are **preserved, not merged** -- two readings of one ad are two observations.
- No hash was invented. `raw_responses.payload_hash` is untouched and is not any kind of ad hash.

### Validation completed
- `ruff check .` clean; `ruff format --check .` clean; `mypy backend/app` clean (32 files).
- Tests: **unit 129**, **contract 52**, **integration 96**, **full suite 450 passed**. All prior
  S0/S1 tests still pass; none was weakened or deleted.
- `alembic current` = `0003_jobs_table (head)`; `alembic heads` = `0003_jobs_table (head)`;
  `alembic check` = *No new upgrade operations detected*. PostgreSQL 16 healthy.
- **No migration, no table, no schema modification.** `git status` for `database/`,
  `backend/app/models/`, `alembic/env.py` and `backend/app/db/` is all empty.

### Reviews run
- **thermo-nuclear-code-quality-review** -- confirmed the mapping now exists exactly once and that no
  old helper was left orphaned. Findings fixed: dead/tautological immutability tests replaced with
  real properties; payload tests now driven by the fixture; `MALFORMED_PAYLOAD` docstring corrected
  (kind does not carry scope, `index` does, and that is now pinned by a test); the module docstring
  no longer claims a raw-persist order the live call path does not have.
- **secure-code-guardian** -- found four exploitable-today defects, all fixed: `str()` coercion of
  arbitrary list elements was turning a dict into an observed platform label; provider text could
  forge a log record through `detail` (now `_safe`: `repr`, control characters escaped, length
  bounded); `bool` was accepted as a pixel dimension; a CRLF-bearing URL was stored. Not adopted,
  correctly out of scope: an SSRF blocklist, which belongs at the fetch seam, and unbounded-list
  caps, which would mean inventing limits.
- **accidental-data-loss-prevention** -- PASS. No migration, model, or DB-config change. The
  pre-existing normalise-before-persist ordering was **preserved, not changed**.

### Known limitations
- **Normalization still runs inside the provider.** `MockProvider` calls the normalizer in
  `fetch_page_ads`, so a record it cannot read raises `SchemaChanged` *before*
  `CollectionOrchestrator` persists the raw response, and the payload is lost with the exception.
  This contradicts the intended collect -> keep raw -> normalize order and is a real data-loss path.
  **It belongs to S2.1**, which owns persistence order. The normalizer is deliberately a pure
  function so S2.1 can call it on an already-stored payload and get the same answer. Not fixed here
  because doing so would mean moving the call in the S1.2 orchestrator, which is out of scope. Note
  the exposure is slightly *higher* than before, because the reader is now stricter.
- **No normalized ad is persisted anywhere yet.** By design; S2.1.
- **No real provider exists.** `MockProvider` is still the only registered `AdDataProvider`.
- **No snapshot state machine.** S2.1 owns `ad_snapshots`, `not_seen_since`, `presumed_inactive`.
- **No API endpoints, no authentication, no frontend.** Later checkpoints.
- **URL acceptance is not fetch safety.** Loopback, link-local and cloud-metadata addresses are
  recorded; whether a URL may be *requested* is a decision for whoever requests it.
- **`alembic downgrade` never executed** -- issues `DROP`s requiring explicit consent.
- **`docker compose config` prints the resolved password** -- never paste its output.
- **Repo-local git identity is still the placeholder** `Brandset Dev <dev@brandset.local>`.
  No remote configured. Nothing pushed.

### Next checkpoint: S2.1
Normalized ad persistence plus the historical ad/snapshot domain: the `ads` and `ad_snapshots`
tables, append-only `ad_snapshots`, the `provider_active` / `not_seen_since` / `presumed_inactive`
state machine, and **reordering the collection flow so the raw response is persisted before
normalization**. Do not start without explicit human approval.
---

## Corrective note -- raw-before-normalize ordering (pre-S2.1, no new checkpoint)

A narrowly scoped architectural correction to S1.3, made before S2.1 rather than during it.
**Not a new checkpoint. No migration, no table, no schema change.**

### The defect
S1.3 left `MockProvider` normalizing the payload *inside* `fetch_page_ads`. A malformed record
therefore raised `SchemaChanged` **before** `CollectionOrchestrator` reached its raw-persist step,
so the payload was lost with the exception -- the one record we needed to look at was the one we
could no longer see. `ProviderResult.records` was the field that made this possible: a provider that
reads its own payload can refuse to return at all.

### The flow
- **Before:** provider fetch -> normalization (inside the provider) -> raw persistence.
  A reading failure destroyed the evidence.
- **After:** provider fetch -> persist `provider_run` + `raw_response` -> **commit** -> normalization.
  A reading failure costs one record; the payload is already durable.

### Transaction boundary
`self._session.commit()` sits immediately between `_persist_provider_run(...)` and
`normalize_payload(...)`, and is unconditional on every iteration of the cursor loop. No write
transaction is held across a provider call, and no ORM attribute is read during one: the run's
country and `PageRef` are read out of the session *before* the commit, because SQLAlchemy expires
attributes on commit and a lazy load would otherwise reopen a transaction inside the fetch. There is
no `rollback()` anywhere in the module, so nothing can undo a stored payload.

### What changed
- `ProviderResult.records` **removed**. No implementation populated it after the move, and a field
  that must always be empty is a lie in the type. `ARCHITECTURE.md` updated to match.
- `MockProvider` is provider-data-only: it serves the corpus verbatim and raises nothing.
- `CollectionOrchestrator` calls `normalize_payload` and returns
  `CollectionOutcome(records, errors, status)`. `status` is there because an empty record tuple means
  three different things -- already terminal, nothing to report, or blocked -- and the caller does
  not hold the row. A `PARTIAL` status is the existing vocabulary for "some of it arrived".
- `_describe` and `_excerpt` keep `run.error_message` inside the column's `CHECK`, `repr`-escaped so
  a provider cannot forge a log line through it.
- Deleted dead code: `run_failed` / `last_error` threaded to a `pass` block.

### Tests
- New `backend/tests/test_collection_ordering.py`: 20 tests. The ordering itself is proven with a
  recording session, because a sequence cannot be observed after the fact -- only a fake session can
  see one while it happens. Integration tests then confirm the row lands, keeps the whole payload
  including the unreadable record, survives the failed reading, and can be re-read afterwards.
- **Mutation-verified.** Three deliberate regressions were each caught: removing the protecting
  commit, moving normalization before the persist, and replacing partial success with
  all-or-nothing. An earlier version of the ordering assertion was found passing for the wrong
  reason (it accepted the unrelated RUNNING commit) and was fixed.
- Rewrote the malformed-record tests in `test_mock_provider.py` to assert the provider serves the
  payload untouched and the *reading* reports the error. Assertion strength was preserved or
  improved everywhere; no test was weakened or deleted.
- Full suite: **472 passed** (unit 129, contract 54, integration 101).

### Reviews
All three run; real findings fixed. Thermo-nuclear: dead code removed, one tautological test and a
no-op monkeypatch deleted, two competing queue fakes merged, `_describe` given tests. Security:
`run.error_message` was written unbounded and unescaped from a provider exception -- a 5000-character
message would have raised `IntegrityError` from the `finally` that saves the run's status, leaving
the row mutated but uncommitted. Accidental-data-loss: PASS, no migration or model-schema change;
independently traced the unexpected-exception path and confirmed the committed raw response survives.

### Known limitations (unchanged by this fix, or newly visible)
- **The cursor walk has no page cap and no cycle detection.** A provider that repeats a
  `next_cursor` would loop and grow `provider_runs`/`raw_responses` without bound. Unreachable with
  `MockProvider`; must be closed before the first real provider.
- **Records accumulate across a whole run** with no ceiling. Same reachability.
- **A malformed record is now quieter, not louder.** It used to fail the run and log a warning; it
  now yields `PARTIAL`, which the worker logs at info and marks the job complete. The signal lives
  in `collection_runs.error_message` and `raw_responses`. Worth revisiting with the worker.
- **`collection_runs` has no lease or heartbeat.** A crash after the raw commit but before the final
  commit leaves a run permanently `RUNNING` with payloads already stored. A worker/lease decision.
- **URL acceptance is not fetch safety.** Loopback, link-local and cloud-metadata addresses are
  recorded; whether a URL may be *requested* is a decision for whoever requests it.
- No real provider exists. No normalized ad is persisted yet. No API, no auth, no frontend.

### Next checkpoint: S2.1 (unchanged)
Normalized ad persistence plus the historical ad/snapshot domain: the `ads` and `ad_snapshots`
tables, append-only `ad_snapshots`, the `provider_active` / `not_seen_since` / `presumed_inactive`
state machine, and consuming `CollectionOutcome`. The raw-before-normalize ordering it needed is now
in place. Do not start without explicit human approval.

---

## S1.2 hardening -- cursor safety, record safety, run recovery

A small hardening checkpoint on the completed S1.2 orchestration. **No migration, no table, no
schema change.** The raw-before-normalize ordering from the previous commit is untouched and still
proven by the regression tests in `test_collection_ordering.py`.

### 1. Cursor cycle protection
A cursor already followed in one execution is not followed again. The guard sits at the **top** of
the walk, before the fetch, so the repeated page is never requested. A cursor is opaque: only
equality is compared, and no provider-specific cursor semantics are assumed or invented. The walk
ends `partial` with `error_type = cursor_cycle`, and the cursor is named in the message. A
20-cursor walk is followed to the end, so the guard cannot fire on a provider that is behaving.

### 2. Two explicit ceilings, not one
The first draft counted only *readable* records and a review proved the walk was still unbounded:
a provider serving well-formed **unreadable** records never grew that counter, and a provider
serving **empty** pages with a fresh cursor never grew it or repeated a cursor. Both holes are
closed by two independent guards, each a documented `Settings` field:

- `collection_max_records_per_run` (default 10,000) -- counts **attempts**, readable or not.
- `collection_max_pages_per_run` (default 200) -- the only guard a provider offering nothing can
  escape. Checked before the fetch.

Both stop the walk *before* the next fetch, so neither ever reports a limit the provider did not
cause, and neither truncates a page: a single page larger than the ceiling is stored and read
whole, because the raw response is the evidence. Neither is a product statement about any
competitor's ad volume -- the reasoning lives once, in `ARCHITECTURE.md` under "Collection safety".
The architecture defined **no** maximum record count, so these are a newly documented configuration
seam, not an existing contract implemented.

### 3. Stale collection-run recovery
`CollectionOrchestrator.recover_stale_runs()`, called from the worker's idle tick. A run is
recovered only when it is `running`, **no** job for it holds a live lease, **and** it has added no
provider call within `collection_stale_run_timeout` (default 30 min, validated at startup to
exceed the 5-minute job lease). The third signal is what makes it safe: a slow run keeps committing
`provider_runs` rows, and the lease alone cannot tell a slow run from a dead one because the worker
does not extend leases.

- It **never** marks a run `complete`. Elapsed time is not evidence that work was finished.
- It only moves `running` -> `failed`, which is what hands the page back -- `schedule_collection`
  refuses to start a run while one is `pending` or `running`, so an abandoned run otherwise makes
  its page permanently uncollectible.
- The status guard is repeated in the `WHERE` of the write, so a run a live worker finished
  in between is **not** overwritten; the rowcount says so and it is left out of the result.
- It touches no `provider_run` and no `raw_response`. A run that died at page nine still collected
  eight pages of evidence, and that is the only copy.

### 4. Two defects found by review, in code the previous checkpoint shipped
- **`_excerpt` could exceed the column limit.** It budgeted on the *input* length, but `repr`
  doubles a backslash and quadruples a control character, so a provider-supplied cursor could
  produce a string 3x over the `CHECK` -- raising `IntegrityError` from the `finally` that saves
  the run's status, exactly the failure `_excerpt` exists to prevent. The bound is now applied to
  the rendered string.
- **Internal exception text was persisted verbatim** to `error_message`, which
  `get_run_error()` hands to a caller. Real text carries the failed SQL, the database host and
  user, and an absolute filesystem path including the OS username. An unexpected internal failure
  now stores a fixed pointer; the detail goes to the worker log. A *typed provider* error still
  keeps its own message, because that text is the provider's and says what a reader needs.

Also fixed: `_excerpt` did not escape on the short path, so a provider `Blocked` message could
forge a log line; the `stale_run_timeout`-vs-lease invariant is now enforced at startup; ceilings
reject a non-positive value; recovery is batched and rolls back on error; `finished_at` is clamped
so clock skew cannot trip a CHECK; the `error_type` vocabulary is now one block of constants
instead of a dict plus two bare literals.

### Tests
New `backend/tests/test_collection_hardening.py` (36 tests). Every guard is **mutation-verified**:
disabling the cycle guard, the page ceiling, the record ceiling, the recovery `WHERE` guard, the
`_excerpt` bound, or the internal-error redaction each fails the suite. Two false passes were found
and fixed during that process -- an ordering assertion that accepted an unrelated commit, and a
race test that rebuilt the guarded `UPDATE` in the test body and therefore proved its own copy.
`test_config.py` gained 6 tests, including one that the `.env.example` value actually parses (it
did not: only ISO-8601 durations are accepted, so `1800` would have failed at startup).

Full suite: **519 passed** (unit 139, contract 54, integration 115). Baseline was 472.

### Reviews
All three run; genuine findings fixed. Accidental-data-loss: PASS, and it independently traced the
unchanged commit-before-normalize invariant. Thermo-nuclear: the two ceilings not composing was the
real finding, plus the unreachability of recovery (now wired into the worker). Security: the
`_excerpt` expansion and the information disclosure were both rated highest and are fixed.

### Known limitations
- **No per-call provider timeout exists.** A worker alive but blocked inside one
  `fetch_page_ads` for longer than the stale timeout has written no recent `provider_run`, so a
  live run can still be marked `failed`; the page is re-collected concurrently and the worker's
  own commit then overwrites the recovery. Closing this needs a provider-side timeout or a run
  heartbeat, both of which need a real provider.
- **The worker does not extend job leases**, so a legitimately long walk loses its lease while
  still running. The progress signal covers this, but it is a queue gap.
- **Recovery's job lookup has no reverse index** -- `jobs.payload ->> 'collection_run_id'` is a
  scan. The right fix is a nullable `collection_run_id` column on `jobs`, which is a migration and
  so out of scope. Batches are bounded to limit the cost.
- **Recovery does not fail the job** it declares abandoned; a re-claimed job wastes one attempt
  before being released.
- **A malformed record is quieter than before S1.3's reordering** -- `partial` logs at info.
- **URL acceptance is not fetch safety.** No real provider exists. No normalized ad is persisted
  yet. No API, no auth, no frontend.

### Next checkpoint: S2.1 (unchanged)
Normalized ad persistence plus the historical ad/snapshot domain: the `ads` and `ad_snapshots`
tables, append-only `ad_snapshots`, the `provider_active` / `not_seen_since` / `presumed_inactive`
state machine, and consuming `CollectionOutcome` -- whose `stopped_reason` now tells S2.1 why a
run was short. Do not start without explicit human approval.

---

## S2.1 -- IMPLEMENTATION PAUSED -- HANDOFF

**S2.1 IS NOT COMPLETE.** The work is paused mid-checkpoint, deliberately, with everything left on
disk. Nothing in this entry may be read as a pass. This is a documentation-only handoff: no
application code, schema, migration, test, or model was touched to produce it, and **nothing was
committed**.

### 1. Last committed checkpoint
```
6b09e5e -- fix: harden collection orchestration
```
`6b09e5e` remains HEAD and is intact. It was the clean state before this attempt and it was not
altered, reverted, or rebased. The stash list is empty.

### 2. Current uncommitted S2.1 state
All of the following exist on disk, are **uncommitted**, and are new work layered on `6b09e5e`:

| Item | Location |
|---|---|
| `ads` model/table created | `backend/app/models/ads.py` (`Ad`) |
| `ad_snapshots` model/table created | `backend/app/models/ads.py` (`AdSnapshot`) |
| `seen_in_run` model/table created | `backend/app/models/ads.py` (`SeenInRun`) |
| `content_hash` v1 implemented | `backend/app/services/content_hash.py` |
| ad persistence service created | `backend/app/services/ad_persistence.py` |
| `CollectionOrchestrator` modified for S2.1 persistence | `backend/app/services/collection.py` |
| migration created **and applied** | `database/migrations/versions/0004_ad_history.py` |

Working tree: **9 modified, 4 untracked, 0 staged.** The four untracked files are the ones above
that are new; the modified files are `models/__init__.py`, `services/collection.py`, and six test
files touched only to keep the existing fakes and cumulative table-count assertions compatible with
the new tables. `AGENTS.md`, `ARCHITECTURE.md`, `DATA_ACCESS.md`, `IMPLEMENTATION_PLAN.md` were **not**
modified.

### 3. Current database state
- **Alembic head: `0004_ad_history`. Single head, no branch, no gap** (`0001_pg_trgm` ->
  `0002_collection_domain` -> `0003_jobs_table` -> `0004_ad_history`).
- `alembic current` reports `0004_ad_history`; `alembic check` reported **"No new upgrade operations
  detected"** -- migration and models are in agreement.
- **No database reset was performed. No destructive downgrade was performed.** The existing data was
  not touched. `0004_ad_history.upgrade()` is purely additive (`CREATE TABLE`, `CREATE TRIGGER`,
  `CREATE OR REPLACE FUNCTION`, `ALTER TABLE ADD CONSTRAINT`); its `downgrade()` contains `DROP`
  statements but is documented as offline-render only and **was never executed**.
- Tables present: `ads`, `ad_snapshots`, `seen_in_run`, alongside the S1 set. All FKs on the three
  new tables are `RESTRICT`; no cascade anywhere. `trg_ad_snapshots_append_only` is installed.
- **The three new S2.1 tables are empty**: `ads` 0, `ad_snapshots` 0, `seen_in_run` 0.
  `raw_responses` 0 and `collection_runs` 0 as well. (`jobs` holds 2 rows, pre-existing from S1.2
  work.) So no S2.1 row has been written by the paused implementation.

### 4. Current verification status
What was observed and is therefore trustworthy:
- `ruff check backend` -- All checks passed. `ruff format --check` -- 59 files already formatted.
- `mypy` under the project config (`packages = ["app"]`, `strict = true`) -- **no issues in 35 source
  files**. The new code type-checks clean.
- `pytest -m unit` -- **139 passed**. `pytest -m "not integration"` -- **407 passed, 115 deselected**.
- `alembic check` -- no drift.
- All changed and new files parse.

What is **not** verified, and must not be described as verified:
- **S2.1-specific test coverage is NOT COMPLETE.** There is no `test_content_hash.py`, no
  `test_ads.py`, and no `test_ad_persistence.py`. A search for `persist_observations`,
  `content_hash_v1`, `AdSnapshot` and `SeenInRun` across `backend/tests/` returns **zero** matches.
- **Integration verification for the three new S2.1 tables is NOT COMPLETE.** The 115 integration
  tests were deselected and not run. The append-only trigger, the circular
  `ads` <-> `ad_snapshots` foreign key, the upsert path, and the uniqueness constraints have no
  integration coverage.
- The boundary pattern used by S1.1 was not mirrored. `test_models.py` gained `S21_TABLES` and
  `S2_TABLES` constants, but **no test consumes `S21_TABLES`**, so the S2.1 checkpoint boundary is
  currently unasserted.
- **S2.1 is therefore NOT COMPLETE** and must not be reported as complete.

### 5. Exact remaining work, in this order
- **a.** `backend/tests/test_content_hash.py` -- v1 digest stability, the frozen version token,
  absences staying distinct (`None` vs `""` vs `()`), byte-length framing, set-like fields sorted
  for hashing only, provider reordering not minting a false change.
- **b.** `backend/tests/test_ads.py` -- including the missing **S2.1 boundary test that consumes
  `S21_TABLES`**, mirroring `test_s11_defines_exactly_the_five_assigned_tables`, plus the rule that
  `ad_snapshots.updated_at` never moves.
- **c.** `backend/tests/test_ad_persistence.py` -- first sighting writes a snapshot; an unchanged
  re-sighting writes only a link and does not move `latest_snapshot_id`; changed content appends;
  duplicate sightings within a run collapse to one; reprocessing the same run is idempotent.
- **d.** Integration coverage in `backend/tests/test_schema_integration.py` for the three new tables:
  the append-only trigger refusing `UPDATE`/`DELETE`, the circular FK, `RESTRICT` behaviour, and the
  uniqueness constraints.
- **e.** Raw evidence preservation verification -- prove the raw response survives a failure in the
  normalised persistence step, i.e. that `_persist_ad_history`'s rollback cannot take a committed
  payload with it.
- **f.** Full validation -- lint, format, strict mypy, and the complete suite **including integration**
  against the applied `0004_ad_history`.
- **g.** Security / code-quality / data-loss review (the three reviews every checkpoint runs).
- **h.** The `PROJECT_MEMORY.md` completion entry for S2.1, following AGENTS.md section 4.
- **i.** The final S2.1 commit.

### 6. Architectural decisions already locked in the uncommitted work
These are settled. Do not relitigate them in the next session without an explicit human decision:
- The S2.1 tables are exactly `ads`, `ad_snapshots`, `seen_in_run`.
- `seen_in_run` carries `UNIQUE (ad_id, collection_run_id)`.
- `seen_in_run` is **upserted, not append-only** -- it is a link row, and a provider may legitimately
  serve one ad twice in one walk.
- `ad_snapshots` is **append-only**, enforced by the database (`trg_ad_snapshots_append_only`), not
  only by application discipline. A new observation is a new row.
- `content_hash` v1 is **frozen and versioned** (`CONTENT_HASH_VERSION = "s2.1-content-v1"`). A
  different input set is a new *version*; no v1 row is ever recomputed.
- `copy_hash` and `creative_hash` are **deferred to S2.2**, added later as new columns.
- `ads.current_status` and the `provider_active` / `not_seen_since` / `presumed_inactive` state
  machine are **deferred to S2.3**. Nothing in S2.1 derives an ad's status.
- `ad_snapshots.raw_ref` points at `raw_responses.id`, giving the chain
  snapshot -> response -> provider call -> run -> page -> competitor.
- `EvidenceClass` remains **derived** from `DataOrigin`, never physically stored. No table in the
  package carries the column.
- The raw response must remain **persisted and committed before normalization**, unconditionally, on
  every iteration of the cursor loop. The S2.1 normalised write is a separate transaction after it.
- `meta_delivery_start` (provider-reported) and `ads.first_seen_at` (our observation) are separate
  fields and are never merged.

### 7. Critical unfinished verification -- read this before claiming anything about S2.1
**The real S2.1 persistence implementation has no dedicated test coverage at all.** There is no
`test_content_hash.py`, no `test_ads.py`, no `test_ad_persistence.py`. The existing fake sessions in
`test_collection_hardening.py`, `test_collection_ordering.py` and `conftest.py` (`StubAd`,
`StubResult`, and the added `execute` methods) were adjusted **only for compatibility** -- they
accept the new upsert statements and **discard** them, returning fresh stand-ins. They prove that
the walk still decides what it decided; they prove nothing about what is stored.

Several docstrings in the new code promise tests that do not yet exist, notably
`backend/app/models/ads.py` ("A test asserts it does not [move `updated_at`]"),
`backend/app/services/ad_persistence.py` ("Idempotent: re-processing the same run leaves the same
rows"), and `database/migrations/versions/0004_ad_history.py` (append-only enforcement). Treat those
as declared intent, not as satisfied requirements, until item (b), (c) and (d) above are done and run.

**Do NOT describe the S2.1 implementation as fully verified.** It is uncommitted, unverified in
substance, and unfinished.

### 8. Next session instruction
**Resume S2.1 from the existing uncommitted state.**
- **Do NOT rebuild S2.1 from scratch.** The models, migration, `content_hash` v1, the persistence
  service and the orchestrator wiring are all present and coherent; the work that remains is the
  missing test coverage and the final review and commit.
- **Do NOT reset the database, run a downgrade, drop a table, or re-run the migration.** `0004_ad_history`
  is applied and is the one thing in this checkpoint that cannot be undone cleanly.
- **Do NOT start S2.2.** No `ad_creatives`, no `ad_platforms`, no `ad_countries`, no `landing_pages`,
  no `media_assets`.
- First write and run the missing focused tests (`a`, `b`, `c`), then the integration tests (`d`),
  then raw-evidence verification (`e`), then full validation (`f`), then the three reviews (`g`),
  then the `PROJECT_MEMORY.md` completion entry (`h`), then the S2.1 commit (`i`).
- Do not start any later checkpoint without explicit human approval.

---

## 2026-10-01, Checkpoint S2.1 -- Normalized Ad Persistence + Ad History Domain (COMPLETE)

Resumes the paused work recorded in the entry above, which is left in place as the record of
where the checkpoint stood when it was interrupted. **S2.1 is complete and READY TO COMMIT.**
**S2.2 has NOT started.**

### 1. What was built

Three tables, one digest, one write path, and the orchestrator wiring that orders them.

- **`ads`** (`backend/app/models/ads.py`) -- one ad, identified for ever as
  `(provider, meta_ad_id)`. Carries `first_seen_at` / `last_seen_at` (ours, server-clock),
  `data_origin`, and a nullable `latest_snapshot_id` pointer. **No `current_status`** (S2.3),
  no `copy_hash` / `creative_hash` (S2.2), and **no page or competitor column** -- lineage runs
  `seen_in_run` -> `collection_run` -> `facebook_page` -> `competitor`.
- **`ad_snapshots`** -- one immutable observation. `raw_ref` -> `raw_responses.id` is the whole
  audit trail. **Append-only, enforced by the database** (`trg_ad_snapshots_append_only`), not by
  application discipline, because a silent write here is irrecoverable.
- **`seen_in_run`** -- the fact that one run saw one ad. `UNIQUE (ad_id, collection_run_id)`.
  **Not append-only**: it is a link row, and a provider may legitimately serve one ad twice in
  one walk, so the second sighting corrects the link rather than adding a row.
- **`content_hash` v1** (`backend/app/services/content_hash.py`) -- frozen and versioned
  (`s2.1-content-v1`), eight inputs, length-prefixed framing, exclusions pinned, no Unicode
  normalisation, a frozen display-format token table so widening `AdFormat` cannot move a stored
  digest.
- **`ad_persistence`** (`backend/app/services/ad_persistence.py`) -- identity upsert, digest
  compare, snapshot only on change, pointer only on new snapshot, link upsert.
- **`CollectionOrchestrator`** -- the normalised write happens **after** every raw response is
  committed, in its own transaction, with its own rollback.

### 2. Migrations

- **`0004_ad_history`** -- creates the three tables, adds the circular
  `ads` -> `ad_snapshots` foreign key with `ALTER TABLE` after both exist, and installs the
  append-only trigger. All-RESTRICT throughout. Downgrade renders offline and is never run.
- **`0005_ads_data_origin_check`** -- an **additive repair** found by the final review, not new
  scope. `0004` created `ads.data_origin` with `create_constraint=False`, so the vocabulary check
  the model declares was never installed: `collection_runs.data_origin` rejected out-of-vocabulary
  values (S1.1) while `ads.data_origin` accepted anything. **`alembic check` reported no drift and
  still does** -- autogenerate does not detect `CHECK` constraints, which `app/models/mixins.py`
  documents at length. The only way to catch it is comparing metadata against `pg_constraint` by
  name, and the existing test looped over `S1_TABLES` only. One `CHECK`, same four values, no
  data touched. `0004` was not edited, because editing an applied migration would be a lie about
  what actually ran.

Head is `0005_ads_data_origin_check`, single head, no drift. The three S2.1 tables are **empty**;
no reset, no destructive downgrade, no data touched at any point.

### 3. Verification

| Check | Result |
|---|---|
| Targeted four files | **215 passed** |
| Full backend suite | **675 passed** |
| `ruff check backend` | All checks passed |
| `ruff format --check backend` | 62 files already formatted |
| `mypy` (project config, `packages = ["app"]`, strict) | Success, 35 source files |
| `mypy backend` (adds tests) | 61 errors in 15 files -- the exact pre-existing baseline; **zero** in any S2.1 file |

**Mutation-verified.** Three deliberate regressions were each caught: inverting the digest
comparison in `_persist_one` fails `test_reprocessing_a_run_with_changed_content_is_refused`;
removing the commit that protects the raw response fails
`test_a_failure_in_ad_history_leaves_the_committed_raw_response_intact`; removing `S21_TABLES` from
`test_the_database_matches_the_models_with_no_drift`'s reach fails the metadata assertions.
Six further test bugs of my own were found and fixed during this work (a wrong `_frame("")`
expectation, `local_remote_pairs` indexing, a blanket FK loop that contradicted the intentional
`latest_snapshot_id`, a colliding `page_id`, two orphan-FK tests that could pass for the wrong
constraint, and a `seen_in_run` test asserting a scenario the design forbids).

### 4. Idempotence -- corrected wording, and what is actually guaranteed

The docstring previously claimed flatly that reprocessing "leaves the same rows". That was
**overstated**. The corrected docstring states the guarantee conditionally:

- **Reprocessing the same run with *identical* input is idempotent.** Three separate mechanisms:
  identity is an upsert, an unchanged digest writes no snapshot and does not move
  `latest_snapshot_id`, and the `seen_in_run` link is an upsert.
- **Reprocessing the same run with *changed* content is NOT idempotent, and the database refuses
  it.** `uq_ad_snapshots_ad_run` rejects the second snapshot with an `IntegrityError`.

**That rejection is intentional and is now a tested invariant.** One collection run is one
observation of an ad, so `(ad, run)` *is* the identity of that observation and admits exactly one
row. A run yielding two different readings is two observations wearing one run's identity, and the
honest record is a new run. Allowing it would let per-run history become a record of a *reading*
rather than of a *walk*, and would break S2.3's `not_seen_since` reasoning, which counts
*consecutive complete runs* and is only meaningful if one run contributes one observation per ad.

Re-processing exists to fix a parser bug, and a fixed parser reads the same stored bytes to the
same digest -- so the refused path is not reached by the use case idempotence was introduced for.
It is reached when the *reader* changed, which is exactly the case worth refusing loudly rather
than silently recording as history. **No behaviour changed; only the claim was corrected.**

### 5. Known limitations

- **Changed-input reprocessing raises `IntegrityError`** rather than being absorbed. Correct, and
  now pinned by a test, but a caller must treat it as "a new run is required", not as a retryable
  error.
- **The `seen_in_run` `on_conflict_do_update` `SET` clause is never exercised**, because the
  per-run sighting collapse happens before the write. It is unreachable through the public API, so
  it is effectively dead code today. Noted rather than tested, because contorting a test to reach
  it would assert behaviour the design prevents.
- **`seen_in_run.updated_at` is the only signal that a link was corrected**, and nothing consumes
  it yet.
- **Windows `TEMP`/`TMP`: 11 pre-existing `PermissionError` errors** in
  `backend/tests/test_media_store.py` and `backend/tests/test_offline_guard.py` under the default
  `C:\Users\DELL\AppData\Local\Temp\pytest-of-DELL`. **This is an environment issue in `tmp_path`
  resolution, not an S2.1 defect**, and the affected tests are S0.3 work that must not be modified
  to hide it. The suite is green with `TEMP`/`TMP` pointed at
  `C:\Users\DELL\AppData\Local\Temp\opencode`. **Anyone running the suite on this machine must set
  those two variables or expect those 11 errors** -- they are not test failures.
- **Integration tests require the PostgreSQL container.** They are not skipped when it is down.
- **No real provider exists.** Every collection has run against `MockProvider` and the committed
  corpus. Nothing here has met Meta or a third party.
- **No API, no auth, no frontend.** S2.1 is storage and the write path only.

### 6. Next checkpoint: S2.2 -- NOT STARTED

No `ad_creatives`, no `ad_platforms`, no `ad_countries`, no `landing_pages`, no `media_assets`, no
copy/creative hash split, no URL canonicalisation, no search index. The `pg_trgm` extension is
installed and deliberately unused; the S2.1 tables declare no indexes beyond their constraints,
and `test_no_trigram_or_text_index_exists_yet` was **re-run and extended** in this checkpoint
precisely so a later one cannot add one without noticing. `copy_hash` and `creative_hash` arrive
as new columns, and the stored v1 `content_hash` values keep meaning exactly what they meant.
Do not start without explicit human approval.

---

## 2026-10-01, Checkpoint S2.2 -- Copy/Creative Digests + Duplicate Detection (COMPLETE)

**S2.2 is complete and READY TO COMMIT. S2.3 and S2.4 have NOT started.** Nothing in this entry
may be read as covering either of them.

### 1. What was built

S2.2 added **no tables at all**. It extended `ad_snapshots` with two nullable columns and built
the write path and the query that make them useful.

- **`copy_hash` v1** (`backend/app/services/copy_hash.py`, `s2.2-copy-v1`) -- the ad's *words*
  only: `primary_text`, `headline`, `description`, `cta`, `destination_url`, in that order, each
  length-prefix framed. Excluded, each with a stated reason: `external_ad_id` (identity),
  `ad_status` and `meta_delivery_start` (a status flip or a corrected date must not rewrite
  history), `page_id`/`page_name` (attribution), `countries` (targeting), `display_format` and
  `media` (the creative, hashed separately), `platforms` (delivery), `provider_metadata`.
- **`creative_hash` v1** (`backend/app/services/creative_hash.py`, `s2.2-creative-v1`) --
  `media[].provider_key` only, **sorted for the hash representation and nowhere else**. The
  stored `normalized` JSON keeps provider order and the record is never mutated.
- **Shared framing** (`backend/app/services/hashing.py`) -- `frame`, `frame_collection`, `digest`
  and the `\x1f` separator, now defined **once** for all three hashes rather than three times.
  `content_hash.py` was refactored to import from it.
- **Duplicate detection** (`backend/app/services/duplicate_detection.py`) -- groups snapshots by
  `copy_hash` and by `creative_hash` through two symmetric query helpers.
- **Two plain indexes** on `ad_snapshots (copy_hash)` and `(creative_hash)`, each for one named
  access pattern.

### 2. The value this actually adds

`content_hash` v1 already detects identical ads, because it hashes words and assets together.
The split exists so a match can be **attributed**: "these two ads say the same thing" and "these
two ads use the same assets" are different findings with different implications, and one digest
cannot answer both. The commonest real duplicate -- identical words over different images -- is
invisible to v1 alone.

### 3. Migration

**`0006_s2_2_hashes`**, extending `0005_ads_data_origin_check`. Single linear head, six
operations, **all additive**: two `add_column` (`nullable=True`, no default, no backfill), two
`create_check_constraint`, two `create_index`. No `UPDATE`, no `TRUNCATE`, no `DROP`, no reset, no
downgrade executed. The `CHECK` expression is **byte-identical to S2.1's**, and accepts `NULL`
without an `IS NULL OR` guard because a `CHECK` is satisfied unless it evaluates to `FALSE` and a
regex yields `NULL` for `NULL`.

`NULL` therefore carries a meaning: **this observation predates S2.2**. It is never a default and
never a computed placeholder, and it is permanent -- `ad_snapshots` is append-only, so a pre-S2.2
row can never be backfilled, and an `UPDATE` is refused by the trigger. That is the same trade
S2.1 made for `content_hash`, and it is the price of never rewriting history.

`downgrade()` drops indexes, then checks, then columns -- the only order in which each object
still exists -- and is rendered offline only, never run.

**Before the migration was authored, `ads`, `ad_snapshots` and `seen_in_run` were each verified
to hold 0 rows.** They still hold 0 rows. The nullable design is what would keep the migration
non-destructive if that were not true, which is why it is the design rather than a convenience.

### 4. S2.1 `content_hash` v1 -- unchanged

**Byte-for-byte unchanged, and no stored digest was recomputed.** The only functional line that
moved across the whole checkpoint is
`hashlib.sha256(_SEPARATOR.join(parts).encode("utf-8")).hexdigest()` becoming `_digest(parts)`,
and `hashing.digest()` is that exact expression with the same `SEPARATOR = "\x1f"`. Field order,
`CONTENT_HASH_VERSION = "s2.1-content-v1"`, exclusions, sorting, display-format token behaviour,
`None`/empty semantics and Unicode behaviour are all untouched. `test_content_hash.py`'s 51 tests
pass unchanged and are the proof.

An earlier `ARCHITECTURE.md` line claimed `content_hash = sha256(copy_hash + creative_hash +
display_format + platforms)`. That was **never built and was corrected, not implemented**: the two
new hashes are *siblings* of `content_hash`, not inputs to it, and making it a composition would
either rewrite history or force a v2 of a contract S2.1 froze deliberately. `ARCHITECTURE.md`
lines 79-118 and the Creative archive section now match what shipped.

### 5. Persistence

Both hashes are written **only** inside the `AdSnapshot(...)` construction, so only when a new
snapshot is inserted. No existing snapshot is ever enriched. The change decision still compares
`content_hash` alone -- deliberately, because it already covers words *and* assets, so a
creative-only change is caught by the existing S2.1 rule and no second comparison exists that
could disagree with it. The two columns exist to be *queried*, not to decide when to write.

S2.1 semantics re-proven through the new split: unchanged content writes no snapshot and no
digests; a copy-only change and a creative-only change each append exactly one snapshot and move
`latest_snapshot_id`; the raw-before-normalize transaction boundary is untouched.

### 6. Duplicate detection semantics

Identity is **the digest, never a `UNIQUE` constraint** -- two competitors running identical
copy is a finding, not a violation, and a uniqueness constraint would forbid the observation
worth having. Three rules the queries must not get wrong, each with a test:

- **`IS NOT NULL` is mandatory.** Every pre-S2.2 row carries `NULL` in both columns. Without the
  filter they would land in one NULL bucket and every pre-S2.2 ad would be reported as a
  duplicate of every other pre-S2.2 ad -- a spectacularly wrong answer shaped like a result.
- **`DISTINCT` on the ad, never a row count.** One ad accumulates snapshots over time, which is
  what the history model is *for*; counting rows would report it as a duplicate of itself, on
  every collection, for ever.
- **No competitor or page attribution.** That needs the
  `seen_in_run` -> `collection_run` -> `facebook_page` -> `competitor` join and is an API
  concern. Deferred: a group that cannot yet say *whose* ad it is is still a correct answer to
  the question this module asks, whereas a guessed attribution would not be.

### 7. Validation

| Check | Result |
|---|---|
| Targeted S2.2 tests (7 files) | **283 passed** |
| Full backend suite | **798 passed** |
| `ruff check backend` | All checks passed |
| `ruff format --check backend` | 70 files already formatted |
| `mypy` (project config, `packages = ["app"]`, strict) | Success, 39 source files |
| `mypy backend` (adds tests) | **61 pre-existing errors in 15 files, zero in any S2.2 file** |
| `alembic current` / `heads` | `0006_s2_2_hashes`, single head |
| `alembic check` | No new upgrade operations detected |

**Mutation-verified.** Two deliberate regressions were each caught and the implementation
restored: inverting the content-change comparison fails
`test_a_changed_creative_with_unchanged_copy_appends_a_snapshot`; removing the duplicate query's
`IS NOT NULL` filter fails `test_a_group_cannot_be_composed_of_nulls`. Worth recording that the
*single*-row NULL test passes either way -- one NULL row cannot form a group -- so only the
two-row test detects that mutation. Both exist for that reason.

Six test-authoring bugs of my own were found and fixed during this checkpoint, all in test code:
a wrong `_frame("")` expectation, `local_remote_pairs` indexing, a blanket FK loop contradicting
the intentional `latest_snapshot_id`, a colliding `page_id`, two orphan-FK tests that could pass
for the wrong constraint, and a duplicate-detection test whose two ads shared a media key.

### 8. Known limitations

- **Pre-S2.2 snapshots keep `NULL` for ever.** Append-only means they can never be enriched. Same
  shape as v1 `content_hash` values retaining their original meaning.
- **`creative_hash` v1 is a provider-key *identity*, not a content digest.** `AGENTS.md` section
  12 forbids media byte downloads in S0-S3, so two ads re-served under a rotated key look
  different to it. **A creative duplicate is a hint, not proof.** S2.4's byte hashing becomes
  **v2** and reinterprets no stored `s2.2-creative-v1` value.
- **`ad_creatives` and card-level modelling are deferred.** The normalized contract exposes no
  card-level structure: `_read_body` reads only `bodies[0]` and flattens it, and the committed
  corpus holds nine ads, every one single-bodied. A per-card table built now would fabricate rows
  rather than record observations. Building it needs a **normalizer change first**, which is its
  own checkpoint. `ad_platforms`, `ad_countries` and `landing_pages` are also deferred; `media_assets`
  is S2.4. `backend/app/models/__init__.py` now states the real S2.2 scope in its checkpoint list
  and carries the old five-table claim only as an explicitly labelled SUPERSEDED note.
- **URL canonicalisation is deferred.** `copy_hash` v1 hashes `destination_url` exactly as
  validated and stored -- no canonicalisation, rewriting, case folding or query reordering.
  `landing_pages` does not exist, so there is nowhere to hold a canonical form, and a digest that
  moved because *we* tidied the URL would claim the provider had changed something it had not.
- **No competitor or page attribution for duplicate groups.** Deferred to a later checkpoint.
- **`mypy backend` has 61 pre-existing errors** in S0.3/S1.x test files. This is the recorded
  baseline, not a regression: S2.2 contributes **zero**. The project gate is the `mypy` project
  config, which is clean. Cleaning the test-file baseline is separate work.
- **Windows `TEMP`/`TMP`: 11 pre-existing `PermissionError` errors** in
  `backend/tests/test_media_store.py` and `backend/tests/test_offline_guard.py` under the default
  `C:\Users\DELL\AppData\Local\Temp\pytest-of-DELL`. **An environment issue in `tmp_path`
  resolution, not an S2.2 defect**, and those S0.3 tests must not be modified to hide it. The
  suite is green with `TEMP`/`TMP` pointed at `C:\Users\DELL\AppData\Local\Temp\opencode`. Anyone
  counting the suite on this machine must set those two variables or expect those 11 errors.
- **Integration tests require the PostgreSQL container** and are not skipped when it is down.
- **No real provider exists.** Every run has been against `MockProvider` and the committed corpus.
  Nothing has met Meta or a third party. No API, no auth, no frontend.

### 9. Future note, not a defect and not changed in this checkpoint

`DuplicateGroup.content_hash` is the field name for the group key, and on `axis="creative"` it
holds a *creative* digest. That is functionally correct and its docstring says "digest", but the
field name is a legacy of the copy-first framing. Recorded here for a future checkpoint to decide;
**no change was made**, because renaming a public field mid-checkpoint for a naming preference is
not justified by any failing test.

### 10. Next checkpoint: S2.3 -- NOT STARTED

`ads.current_status` and the `provider_active` / `not_seen_since` / `presumed_inactive` state
machine, which counts N **consecutive complete** runs and must never fire after a failed or
partial one. Nothing in S2.3 is started. `S2.4` (media bytes, `media_assets`) is likewise not
started. Do not begin either without explicit human approval.

---

## 2026-10-01, Checkpoint S2.3 -- Ad Status State Machine (COMPLETE)

**S2.3 is complete and READY FOR REVIEW. S2.4 has NOT started.** Nothing in this entry covers
media bytes, S3, or the frontend.

### 1. The decision that shaped the checkpoint

`ARCHITECTURE.md` specified `ads.current_status`. **That is not buildable**, and the reason is
structural rather than a matter of taste.

An ad is served on several pages. `ads` deliberately carries **no page and no country foreign
key** -- S2.1 made that call and `test_ads.py` enforces it. But status is a fact *about a
context*: an ad can be present on page A and absent from page B, and both are true at once. One
row on `ads` cannot hold two answers to "did we see it?", and adding a page foreign key to `ads`
would undo the S2.1 decision.

So status lives in **`ad_status_by_context`**, keyed on
`UNIQUE (ad_id, facebook_page_id, country)`. `ads` gained **nothing** -- asserted in both
`test_status_evaluator.py` and `test_schema_integration.py`, against the live database.

### 2. Files created (5)

- `backend/app/models/ad_status.py` -- `AdStatusByContext`, the frozen status vocabulary.
- `backend/app/services/status_evaluator.py` -- the streak walk, the provider token table,
  `record_observation`, `evaluate_run_status`.
- `backend/app/services/ad_duration.py` -- bucket boundaries and the long-running signal. Pure
  functions taking `now` explicitly, so a report is reproducible and the boundaries are testable.
- `backend/tests/test_status_rules.py` -- 56 unit tests (provider tokens, buckets, the signal).
- `backend/tests/test_status_evaluator.py` -- 26 integration tests (every transition and edge).
- `database/migrations/versions/0007_status_by_context.py`.

### 3. Files modified (11)

`models/__init__.py` (charter + registration), `models/ads.py` (one index), `models/runs.py`
(one partial index), `services/ad_persistence.py` (writes the `seen` status per sighting),
`services/collection.py` (evaluates after the run status is known), `conftest.py` (fake result
grew `scalars()`), and tests `test_ad_persistence.py`, `test_ads.py`, `test_models.py`,
`test_migrations.py`, `test_schema_integration.py`, `test_duplicate_detection.py`,
`test_collection_ordering.py`, `test_collection_hardening.py`.

### 4. Schema and migration

`0007_status_by_context`, extending `0006_s2_2_hashes`. Single linear head, no drift.
`ad_status_by_context`: `id`, `created_at`, `updated_at`, `ad_id`, `facebook_page_id`, `country`,
`current_status`, `provider_active`, `not_seen_since_at`, `last_status_run_id`.

- `current_status VARCHAR(32) NOT NULL`, CHECK frozen to `seen | not_seen_since | presumed_inactive`.
- `provider_active BOOLEAN NULL` -- tri-state. `False` only from a recognised "inactive".
- `not_seen_since_at TIMESTAMPTZ NULL` -- the last COMPLETE run's `finished_at` that actually
  observed this ad in this context. CHECKed against `now()`.
- Three FKs, all **RESTRICT**. All three parents nullable as documented.
- **Four indexes, each for a named query**: `collection_runs (facebook_page_id, country,
  finished_at DESC) WHERE status = 'complete'`; `seen_in_run (collection_run_id)`;
  `ad_status_by_context (facebook_page_id, country)`; `ad_status_by_context (last_status_run_id)`.

**Nothing was backfilled and no row was written by the migration.** The new indexes on
`collection_runs` and `seen_in_run` close the deferral `PROJECT_MEMORY.md:553` recorded ("S2
writes the query and measures before an index is built for it") -- this is that S2, and the two
S1.1 tests that pinned its absence were updated to record the decision rather than removed.
The complete-run index is **partial** because failed and partial runs are invisible to the walk.

### 5. Transition matrix

| From | Event | To | `not_seen_since_at` | `provider_active` |
|---|---|---|---|---|
| -- | first qualifying COMPLETE observation | `seen` | NULL | mapped, else NULL |
| `seen` | present in a later COMPLETE run | `seen` | NULL | this run's, else NULL |
| `seen` | absent, streak 1 | `not_seen_since` | last observing run's `finished_at` | **NULL** |
| `not_seen_since` | present again | `seen` | NULL | refreshed |
| `not_seen_since` | absent, streak 2 | `presumed_inactive` | unchanged | **NULL** |
| `presumed_inactive` | present again | `seen` | NULL | refreshed |
| any | FAILED or PARTIAL run | **unchanged** | unchanged | unchanged |

### 6. The N=2 rule

Only COMPLETE runs count. A FAILED or PARTIAL run is **invisible** to the walk -- filtered out by
`WHERE status = 'complete'` *and* refused by an early return -- so it can neither advance nor
reset a streak. Two complete absences either side of an outage are still consecutive complete
absences; the alternative would let a provider being down keep every ad alive for ever.

A COMPLETE run serving **zero ads counts** as evidence of absence for its context: an empty but
clean walk is a complete observation of nothing.

Streaks never cross a Page or country boundary. "Consecutive" means consecutive among complete
runs **for the same context**, ordered by `finished_at DESC`, stopping at the most recent run that
observed the ad. N is a module constant, not a `Settings` field.

### 7. Provider evidence and derived status never merge

`provider_active` is the provider's assertion, read from a **frozen token table** matched
case-insensitively after stripping: `active` -> True, `inactive` -> False, **everything else ->
None**. No fuzzy or substring matching, so `inactive_pending_review` is not read as inactive.

**An absent run clears `provider_active` to None.** Carrying a previous `True` forward would
assert provider evidence that no longer exists. Two facts, two columns; neither overwrites the
other.

### 8. S2.1 and S2.2 invariants preserved

- `content_hash` v1 (`s2.1-content-v1`) untouched. `copy_hash` / `creative_hash` untouched.
- **Status changes create no `ad_snapshots` rows.** `ad_status` is excluded from `content_hash`,
  so a status flip cannot move the digest or `latest_snapshot_id`. Asserted in
  `test_status_evaluation_creates_no_snapshots`.
- The append-only trigger is still armed, asserted by writing to a real snapshot row.
- Raw-before-normalize ordering and the S2.1 transaction boundary untouched: raw responses are
  still committed page by page, and `_persist_ad_history` still rolls back only the normalised
  layer.

### 9. Validation

| Check | Result |
|---|---|
| Targeted S2.3 tests | **339 passed** |
| Full backend suite | **896 passed** |
| `ruff check backend` | All checks passed |
| `ruff format --check backend` | 75 files already formatted |
| `mypy` (project config) | Success, 42 source files |
| `mypy backend` | **61 pre-existing errors in 15 files, zero in any S2.3 file** |
| `alembic current` / `heads` | `0007_status_by_context`, single head |
| `alembic check` | No new upgrade operations detected |

**Mutation-verified -- and two of the five initially did NOT fail, which is the useful part.**

1. Removing the `WHERE status = 'complete'` filter: **no failure**. The early return in
   `evaluate_run_status` is the primary guard and the SQL filter is a second line of defence.
   Disabling the *early return* then **failed** `test_a_non_complete_run_changes_nothing_at_all`.
2. **N=2 -> N=1: failed 5 tests.**
3. **Carrying stale `provider_active`: failed** `test_an_absent_run_clears_a_stale_provider_active_to_null`.
4. Disabling the idempotence guard: **failed** `test_a_replayed_older_run_cannot_rewind_a_newer_conclusion`.
5. Crossing Page/country boundaries in the streak walk: **no failure at first**. The two existing
   context tests shared an observation at the same depth in both walks, so they reached the same
   conclusion either way -- a genuine hole. `test_another_pages_sighting_does_not_end_this_pages
   _absence_streak` was added with interleaved pages so leaking a context changes the answer, and
   it now **fails** under that mutation.

Every mutation was reverted and the file verified byte-intact.

### 10. Known limitations

- **A status row exists only for a context where the ad has been observed.** An ad never seen in
  a context has no row, so there is nothing to mark absent. That is the honest reading -- absence
  of observation is not an observation of absence -- but it means a newly monitored page has no
  status history until its first sighting.
- **The absence walk looks back at most 10 complete runs.** Beyond that it stops counting, so an
  ad absent for longer than 10 runs is judged on those 10 rather than the whole history. The
  conclusion is the same (>= 2), but the boundary is not exact for very long absences.
- **`not_seen_since_at` is NULL until the ad has been observed in a complete run**, and renders as
  `—` per `AGENTS.md` section 7.
- **`provider_active` reflects only recognised tokens.** Real provider vocabularies beyond
  `active` / `inactive` are unverified; the committed corpus contains only `"active"`. Unknown
  wording is NULL rather than false, and the raw string is preserved on `ad_snapshots.ad_status`.
- **`mypy backend` has 61 pre-existing errors** in S0.3/S1.x test files. Recorded baseline, not a
  regression; S2.3 contributes zero. The project gate is the `mypy` project config, which is clean.
- **Windows `TEMP`/`TMP`: 11 pre-existing `PermissionError` errors** in
  `test_media_store.py` / `test_offline_guard.py` under the default temp path. Environmental, in
  S0.3 tests that must not be modified to hide it. Set `TEMP`/`TMP` to
  `C:\Users\DELL\AppData\Local\Temp\opencode` before counting the suite on this machine.
- **Integration tests require the PostgreSQL container** and are not skipped when it is down.
- **No real provider exists.** Everything has run against `MockProvider`. No API, no auth, no
  frontend, no reporting.

### 11. S2.4 -- MEDIA REFERENCES: COMPLETE

Migration `0008_media_assets`, applied and at head. Two tables, **references only**.

**Checkpoint commit:** `ff7ba7d` "feat: complete S2.4 media references" (14 files). It could not
contain its own hash, so it is recorded here in this follow-up commit, as at S0.1.

**Git state correction:** an earlier section records "no remote". That is no longer true -- an
`origin` remote (`subrotofbd/meta-competitor-intelligence`) is now configured, and S2.3 already sits
on `origin/main`. **S2.4 is complete and pushed** -- `ff7ba7d` and its three follow-ups
(`0fa5736`, `47ec45e`, `40af781`) are all on `origin/main`, whose head is `40af781`.
**S3.1 is complete and pushed.** Correcting the note that stood here, which said S3.1 was unpushed:
`bb7eb9b`, `9adc1bc` and `df3160d` are all on `origin/main`, whose head was `df3160d` when S3.2 began.

**`media_assets`** -- `(provider, provider_key)` unique, `source_url`, `mime`, `width`, `height`,
`duration_seconds NUMERIC`, `storage_key`, `byte_size`, `first_seen_at`, `last_seen_at`.
**No foreign key out of it**: an asset is shared identity, and the committed corpus proves it
(`mock-media-shared-01` is on two different ads). **No `sha256`, no `bytes`, no `downloaded_at`** --
`ARCHITECTURE.md` once listed all three and none can be built, because `AGENTS.md` section 12
forbids media byte downloads in S0-S3.

- **`storage_key` is NULL on every row S2.4 creates, and that NULL means exactly one thing:**
  *a reference is held, the bytes have not been acquired*. Not "unknown", not "pending", not zero.
  A `CHECK` accepts a valid 64-lowercase-hex key for a future byte-acquisition checkpoint and
  refuses every other shape while letting NULL through.
- **`provider_key` is an identity hint, not cryptographic proof.** No real provider has been run
  against this product, so key stability is unverified. A changed key creates a **distinct** asset
  row; the two are deliberately not merged, because without the bytes there is no way to know they
  are the same and guessing would be a fabricated finding.
- **`creative_hash` v1 (`s2.2-creative-v1`) is unchanged and NOT byte-based.** It hashes sorted
  provider keys. Byte hashing would be a `creative_hash` **v2** in a later, separately approved
  checkpoint. Nothing was reinterpreted, recomputed or backfilled.

**`ad_snapshot_media`** -- `ad_snapshot_id` FK RESTRICT, `media_asset_id` FK RESTRICT, nullable
`position SMALLINT`, `UNIQUE(ad_snapshot_id, media_asset_id)`,
`CHECK(position IS NULL OR position >= 0)`. The many-to-many observation link, the same shape as
`seen_in_run`. Both FKs are RESTRICT, never CASCADE.

**Indexes:** exactly two -- `ix_media_assets_first_seen_at` and `ix_ad_snapshot_media_media_asset_id`.
Deliberately **no** second index on `ad_snapshot_id`: the unique constraint already leads with it.

**Write path:** `ad_persistence._persist_one` calls `services/media_references.link_snapshot_media`
after the snapshot flush, in the **same transaction**, so a media failure rolls the snapshot back
with it. It runs on **every** observation, not only when a snapshot was created -- an unchanged ad
seen again is a fresh observation of its assets and `last_seen_at` must move. `first_seen_at` is
never rewritten; `last_seen_at` moves forward only (`greatest(last_seen_at, now())`). Both writes
are upserts on their unique constraints, so reprocessing is idempotent. Zero media writes nothing.
`position` is the provider-order index and **never feeds a digest** -- `content_hash` v1 and
`creative_hash` v1 both *sort* media keys.

- `position` is **immutable once the link exists** (see the S2.4 fix pass below). It is captured
  from the observation that created the snapshot, and no later observation rewrites it. This is
  forced by `content_hash` v1 sorting media keys: a provider reshuffle yields an identical digest
  and therefore **the same snapshot**, so re-deriving `position` would make
  `ad_snapshot_media` contradict the append-only `ad_snapshots.normalized` for one immutable
  snapshot.

**No download guarantee:** nothing calls a `MediaStore`, no upload, no fetch, no hash of bytes, no
remote request. `source_url` is stored verbatim and never requested (`DATA_ACCESS.md` records these
URLs expire, so it is a note of where an asset *was*, not a promise it can be retrieved).

**Security (`source_url`):** a media URL carrying a `user:password@` userinfo component is **refused**
by `_read_media`, with a **fixed** error message that never quotes the value -- `detail` is
documented safe to log and reaches `_describe` and `collection_runs.error_message`, so echoing it
would write the token into the database. The raw response still holds the payload, so the cost is
one record, never the evidence. The check is bounded to the authority component, so
`/asset@v2.png` and `?email=user@host` are still accepted. **`destination_url` is deliberately
NOT refused** -- S1.3 settled that a destination carrying userinfo is stored verbatim and
`test_a_url_with_a_port_or_credentials_is_stored_verbatim` pins it; S2.4 does not own that field.

**No backfill.** Snapshots written before `0008` gain no links and are not touched; their media
stays in `ad_snapshots.normalized`, which remains authoritative for them. `ads` and `ad_snapshots`
were not altered at all -- the migration only creates.

**Tests (corrected -- see the fix pass below):** 59 targeted S2.4 tests were written --
40 in `test_media_references.py` and 19 in `test_media_url_security.py`. Four schema tests are
genuinely new (`test_the_s24_downgrade_renders_complete_sql_without_executing_it`,
`test_the_s24_tables_exist_with_their_expected_columns`,
`test_the_s24_indexes_exist_in_the_database`, `test_media_assets_carries_no_foreign_key`).
Two further schema/migration tests were **modified or renamed**, not created:
`test_the_migration_applies_and_leaves_one_head` only had its expected revision changed, and
`test_the_revision_history_is_one_unbranched_chain` replaced the S2.3
`test_s23_extends_the_s22_revision_rather_than_branching`. Counting those as new was the error
corrected here. Full suite at S2.4 was **957 passed** (was 896); the +61 delta is the real
measurement and is not decomposed here because part of it is unverified. `ruff check`/`format`
clean. Project-gate `mypy` clean; `mypy backend` back at its **61-error** pre-existing baseline
with zero from S2.4.

**Mutations verified as at the original S2.4 commit:**

| Mutation | Caught by |
|---|---|
| `position` never written | `test_provider_order_is_preserved_in_position` |
| provider order discarded (position from sorted keys) | position/order tests |
| `first_seen_at` refreshed on upsert | `test_first_seen_at_survives_a_deliberately_wrong_value` |
| userinfo guard disabled | 11 failures in `test_media_url_security.py` |

Three of these **initially did not fail**, and the reasons are worth keeping:

1. Comparing two `now()` values cannot detect an upsert that refreshes `first_seen_at` -- both
   writes land in the same clock second. The test now plants a sentinel from the past.
2. Nothing exercised a provider *reorder*.
3. `_assets`/`_links` returned identity-mapped ORM objects without refreshing them, so a read after
   a write returned pre-write values. Both helpers now `expire_all()`.

**Known limitations, unchanged by this checkpoint:**

- **`provider_key` stability is unverified.** No real provider has been run. If a provider rotates a
  key for an asset it is still serving, that is a second row and `creative_hash` v1 reports a
  difference that may not be one. Accepted for S2.4; no cross-key identity logic was invented.
- **No bytes, so no byte identity.** Nothing here can detect that two differently-keyed assets are
  the same file, or that a re-keyed asset is the same one.
- **`source_url` will expire.** It is a historical note, not a retrieval handle.
- **`mypy backend` has 61 pre-existing errors** in S0.3/S1.x test files. Recorded baseline, not a
  regression; S2.4 contributes zero. The project gate is the `mypy` project config, which is clean.
- **Windows `TEMP`/`TMP`: 11 pre-existing `PermissionError` errors** in `test_media_store.py` /
  `test_offline_guard.py` under the default temp path. Set `TEMP`/`TMP` to
  `C:\Users\DELL\AppData\Local\Temp\opencode` before counting the suite on this machine.
- **Integration tests require the PostgreSQL container** and are not skipped when it is down.
- **No real provider exists.** Everything has run against `MockProvider`. No API, no auth, no
  frontend, no reporting.

**Deferred deliberately:** `ad_creatives` (needs a normalizer change first -- only `bodies[0]` is
read), `ad_platforms`, `ad_countries`, `landing_pages`, media byte acquisition, thumbnails, ffmpeg,
`S3Store`, `creative_hash` v2.

### 11a. S2.4 review findings and the fix pass

A read-only review of `ff7ba7d` returned **NEEDS FIX** with five findings. All five are resolved.
Nothing about the schema, the migration, the hashes, or S2.3 changed.

**D1 -- `position` is now immutable (the substantive fix).** The rule is locked:

> `ad_snapshot_media.position` is the provider-order position captured when that
> `ad_snapshot` was created. Once the link exists, `position` MUST NOT be rewritten.

Two independent defences, because the rule is stronger than "the caller behaves":

1. `link_snapshot_media` takes `snapshot_created` and writes **links only when a snapshot was
   created**. Asset recency (`media_assets.last_seen_at`) still advances on every observation.
2. `_link`'s conflict arm updates `updated_at` only -- `position` and `created_at` are absent.

The reason the rule is *forced* rather than preferred: `content_hash` v1 hashes media keys
**sorted**, so a provider reshuffle yields an identical digest and therefore the same snapshot. An
earlier version re-derived `position` on that path, which left `ad_snapshot_media` contradicting
the append-only `ad_snapshots.normalized` for one immutable snapshot. `normalized` is authoritative
and the link now agrees with it.

A genuinely different *key set* still moves `content_hash`, so S2.1 writes a new snapshot and that
snapshot's links capture the new positions.

- **Mutation-verified, four mutations, all detected.** Two of them initially **survived** and the
  reason matters: the gate and the conflict arm were redundant, so breaking either one alone was
  invisible. They are now pinned separately.

| Mutation | Caught by |
|---|---|
| `position` back in the conflict update set | `test_position_is_written_once_and_never_rewritten` |
| links written on every observation | `test_an_unchanged_observation_manufactures_no_link_for_a_pre_s24_snapshot` |
| `position` derived from sorted keys | `test_position_agrees_with_the_normalized_json_of_its_own_snapshot` + `..._new_snapshot_which_takes_new_positions` |
| caller always claims a new snapshot | both of the above |

**D2 -- the vacuous hash test is gone.** `test_media_writes_touch_no_hash` recomputed three digests
from the same frozen `RawAdRecord` before and after the writes; since the hash functions are pure
and the record is immutable, it could not fail under any mutation. It is replaced by
`test_media_writes_leave_the_persisted_hashes_byte_for_byte_unchanged`, which reads
`content_hash`/`copy_hash`/`creative_hash` **back out of the `ad_snapshots` row** after the media
writes and a re-observation. That is the claim actually worth making, and a writer that recomputed a
digest from a current observation would now be caught.

**D3/D5 -- docstrings corrected.** `media_references.py`'s module docstring no longer claims the
service runs "immediately after a new snapshot is flushed"; it documents the two schedules (asset
recency every observation, links only on snapshot creation) and why `position` cannot be
re-derived. `_link`'s docstring now separates the three lifetimes instead of contradicting itself.

**D4 -- test attribution corrected** in the entry above. The previously recorded "61 new (36 + 19 +
6 schema)" double-counted two modified tests as new; the honest figures are 40 + 19 targeted and 4
genuinely new schema tests. The earlier checkpoint history is preserved, not rewritten.

**Fix-pass validation (targeted only; the full suite was deliberately not re-run):**
`test_media_references.py` 40 passed, `test_media_url_security.py` 19 passed, normalizer +
provider contracts 75 passed, ad persistence + all three hash suites + status evaluator 190 passed,
collection ordering/hardening + schema/models/migrations 200 passed. `ruff check` and
`ruff format --check` clean. Project-gate `mypy` clean; `mypy backend` at its **61-error**
pre-existing baseline with zero from this pass.

### 12. Future S3 AI Campaign Advisor and reporting -- RECORDED, NOT IMPLEMENTED

Recorded here because the product direction is settled even though the work is not S2.3's.

**The product is commercial competitor intelligence.** Political and social-issue advertising are
explicitly not the product focus.

A future S3 AI Campaign Advisor would need to: ask the client questions *before* recommending;
take campaign objective, target customer, offer, geography, desired format, brand style and CTA
as inputs; recommend ad concepts, banner concepts, and short-video / Reel concepts; and explain
**why** each recommendation was produced, from observed patterns in the collected data.

Constraints that travel with it: AI output stays explicitly labelled as **AI interpretation /
recommendation**; competitor spend, leads, sales, conversions and ROAS are **never fabricated**
(`AGENTS.md` section 5); any performance metric must carry legitimate provenance or be explicitly
unavailable.

Future reporting must support **downloadable competitor-intelligence reports**, and must
distinguish observed, calculated, provider-reported, client-provided and unavailable metrics.
**CSV export is future S3 scope.** None of this is implemented in S2.3.

### 13a. S3.1 fix pass -- AI JOB ATTEMPT ACCOUNTING

**The defect.** `run_analysis_job` restarted `attempt_no` at 1 on every invocation, and `_record_attempt`
wrote with `ON CONFLICT DO NOTHING` on `UNIQUE(job_id, attempt_no)`. A **retryable** provider failure
(`Transient`, `RateLimited` -- both `retryable = True`) sends the job back to `pending`, the worker
claims the *same* `job_id` again, and its real second provider call collided with attempt 1 and was
**silently discarded**. The retry's tokens and cost were lost, and if that retry *succeeded*,
`ad_analysis` existed while the ledger still read `status = 'failed'`.

Proven against the live database before the fix (transaction rolled back):

    rows after 1st job attempt          : 1
    rows after a 2nd job-level attempt  : 1
    => the job-level retry's provider call was SILENTLY DROPPED

**The fix.** `next_attempt_no(session, job_id)` reads `MAX(attempt_no)` for the job and continues the
sequence, so one job's attempts run 1 (initial), 2 (corrective retry), 3 (first outer retry), 4, ...
The corrective retry takes `first_attempt_no + 1` rather than a literal 2.

**Safe under the lease model** because only one worker holds a job lease at a time
(`SELECT ... FOR UPDATE SKIP LOCKED`), so two workers cannot allocate against the same `job_id`
concurrently, and the read happens inside the claiming worker's own transaction.

**`_record_attempt` no longer swallows a collision.** `ON CONFLICT DO NOTHING` is gone; a numbering
bug now raises `IntegrityError` and fails the transaction loudly, which is the correct trade for the
one table whose only job is to say what the product spent.

**Nothing else changed:** `UNIQUE(job_id, attempt_no)`, `call_kind`, provider/model, usage, cost,
status, errors and timing are all preserved; the corrective retry is still exactly one; `jobs` is
still the only queue; no Redis, no second retry framework.

**Tests added (7).** First execution records attempt 1; an invalid first response takes attempts 1
and 2; **an outer job retry continues the sequence** and preserves the retry's usage; a corrective
retry followed by an outer retry yields 1, 2, 3 with no collision; `provider call count == ai_jobs row
count` across three worker invocations; a failed call followed by a successful retry leaves both rows
in order with exactly one `ad_analysis`; and an attempt collision raises rather than dropping the row.

- **Mutation-verified:** resetting the counter to 1 on outer retry fails **4** of them.
- `_requeue_via_jobs` reproduces the queue's own `fail`/`claim` SQL on the same session rather than
  calling `PostgresJobQueue`, because that opens its own connection and the `db_session` fixture's
  outer transaction is always rolled back -- a second connection can never see test rows.

**Documentation corrected.** `ARCHITECTURE.md`'s Layout listed `providers/ai/{base.py, openai.py,
gemini.py}`; the latter two have never existed, and the list now shows what is real. `PROJECT_MEMORY.md`
no longer claims the Hindi fixture carries "the English summary alongside" (see the correction note
there), which contradicted D-A.

**Constraint renamed.** `0009` created one constraint with a literal, already-prefixed name, so the
convention prefixed it twice and the database held `ck_ai_jobs_ck_ai_jobs_cost_all_or_nothing` while
`models/analysis.py` declared `cost_all_or_nothing`. `alembic check` does not compare CHECK
constraint *names*, only expressions, which is why it reported no drift. Migration
**`0010_ai_jobs_cost_name`** drops and re-adds the **identical expression** under the conventional
name: DDL only, no row read or written, semantics unchanged, reversible.

Two things worth knowing about that migration: `op.drop_constraint`/`op.create_check_constraint`
apply the naming convention too, so both names are wrapped in `op.f()`; and the revision id is 22
characters because `alembic_version.version_num` is `VARCHAR(32)`, and an over-long id fails at insert
rather than at revision load.

### 13. S3.1 -- AI COPY ANALYSIS: COMPLETE

Migration `0009_ai_analysis`, applied and at head. **References and interpretation only -- no media, no
external call, no SDK.**

**Scope delivered:** prompt v1, the Pydantic-validated 16-field output contract, language and confidence,
dedupe by `(copy_hash, analysis_version)`, token tracking, cost tracking, `ai_jobs`, `ad_analysis`, the
`AIProvider` result wrapper, one retry on invalid output, a per-run analysis cap, null-safe semantics, and
Hindi/Hinglish original-language analysis.

**`ad_analysis`** -- `UNIQUE(copy_hash, analysis_version)`, `source_ad_id` + `source_ad_snapshot_id` FK
RESTRICT as **provenance, not identity**, fourteen typed nullable analysis columns plus `language`,
`confidence`, `provider`, `model`, `prompt_version`. Typed columns rather than the `result JSONB` that
`ARCHITECTURE.md` once sketched: a blob makes it impossible to check that no performance field exists,
that each field is length-bounded, or that `confidence` is one of three values. There is **no** `spend`,
`roas`, `leads`, `conversions`, `reach`, `impressions`, `clicks`, `ctr` or `cpc` column.

**Keyed on copy, not on `ad_id`.** Two advertisers running identical words is a finding -- it is the
reason `copy_hash` exists. Keying on an ad would force one paid call per advertiser and hide the duplicate.
Any snapshot with that `copy_hash` resolves to the same analysis, so **a creative, platform or
`display_format` change costs nothing** (`copy_hash` v1 excludes media and delivery). This is correct
behaviour and must not be "fixed".

**`ai_jobs` is an AI provider-CALL attempt record, not a second queue.** `job_id -> jobs.id`,
`UNIQUE(job_id, attempt_no)`. It has **no** `worker_id`, no `lease_expires_at` and no retry counter:
duplicating those would be a second queue, which `AGENTS.md` section 12 forbids. `jobs` remains the
queue (`FOR UPDATE SKIP LOCKED`), unchanged.

- **Retry separation is what makes the guarantee structural.** The corrective retry is a second `ai_jobs`
  row against the same job, never an overwrite, and `ad_analysis` is written on exactly one path -- a
  validated response. "A retry cannot create duplicate analysis" is therefore a property of the schema,
  not of care.
- Two retry layers, deliberately distinct: one corrective retry inside the handler (in `ai_analysis.py`),
  and the pre-existing `jobs` retry (up to `MAX_ATTEMPTS = 5`) afterwards. Worst case **10 provider calls
  per analysis**, accepted and recorded rather than optimised away.

**Token and cost.** Provider-reported usage is stored verbatim. A partial report is kept as given rather
than completed from the parts we have. The cost triple is **all-or-nothing**, mirroring `provider_runs`, and
is **NULL in S3.1** because no documented pricing method exists -- which is the honest answer, not a gap.
**Zero is never written in place of unavailable.** Usage is recorded even on a call that failed: the model
was billed for those tokens whether or not we could use the reply.

**Per-run cap -- exact semantics, and what is NOT enforced.** `ai_max_analyses_per_run`, `gt=0` so
`0` is a startup error rather than a silent disabling. Counts **analyses scheduled by one call to
`schedule_for_run`**, not provider calls. **A duplicate consumes no budget** -- without that, a
re-run over unchanged copy would spend the whole cap finding nothing. Reaching the cap stops
scheduling and is **not a run failure**: no exception, no error recorded.

Two limitations, stated plainly rather than papered over:

1. **There is no `collection_run_id` on `ad_analysis` or `ai_jobs`, and `schedule_for_run` does not
   take a `run_id`.** "Per collection run" is therefore a *caller convention* -- one call per run --
   and not something the database can enforce or an auditor can verify afterwards.
2. **The cap is a soft guard, not a hard one.** Two concurrent schedulers for the same run could each
   apply the full budget, so the effective ceiling is a multiple of `ai_max_analyses_per_run` rather
   than exactly it.

**What still bounds real spend**, which is why this was not treated as a blocker: the
`UNIQUE(copy_hash, analysis_version)` dedupe is enforced by the database, and the handler re-checks
it before calling the provider. A duplicate job makes **zero** provider calls. So the number of paid
calls is bounded by the number of *distinct* copy hashes, not by the cap. A hard,
database-enforced cap would need a reservation or locking scheme -- deliberately **not** built
speculatively in this fix pass, and recorded here as a future decision if the project ever needs one.

**Provider interface.** `analyze_copy` now returns `AIResult(analysis, provider, model, usage)` rather
than a bare `CopyAnalysis`, which had nowhere to put a token count, a model name, or a provider name, and
so could not satisfy `AGENTS.md` section 10. `AIUsage` is nullable throughout. Typed errors mirror
`providers/data/errors.py`: `RateLimited` / `Transient` retryable, `Blocked` / `InvalidResponse` /
`ResponseTooLarge` terminal, decided by a `retryable` flag and **never by matching an error string**.

**Security.** Ad copy is fenced in the prompt and declared untrusted data; an ad instructing the model to
report a ROAS or reveal its prompt is a finding for `copy_structure`, not an instruction. `destination_url`
and media URLs are **never sent** -- untrusted strings with no analytical value, though `copy_hash` still
covers the URL. The API key is a `SecretStr`, never persisted to `ai_jobs`, `jobs.payload`, or a log, and
`jobs.payload` carries ids and versions only. `error_message` is truncated to 2000 chars, matching `jobs`.
No raw prompt and no raw provider response is persisted. `MockAIProvider` reports `usage=None`, because a
fabricated token count in `ai_jobs` -- the one table whose purpose is to record what the product spent --
would be the worst possible place to invent a number.

**Concurrency.** `UNIQUE(copy_hash, analysis_version)` absorbs a lost race with `ON CONFLICT DO NOTHING`;
the loser is handed the winner's id rather than raising. The dedupe check and the enqueue are **not**
atomic -- `PostgresJobQueue` opens its own session and commits -- and that race is accepted rather than
closed, because making it atomic would mean bypassing the `JobQueue` Protocol.

**No backfill.** An analysis needs a provider call, and nothing in S2.1-S2.4 recorded that one was made.
`ads`, `ad_snapshots` and `jobs` are untouched; migration `0009` only creates.

**Documentation corrected** (the contradictions found in the S3.1 PLAN review, and nothing else):
`AGENTS.md` section 10 and `ARCHITECTURE.md` both promised "English summary fields produced alongside",
which no version of the schema ever had -- **D-A resolved by correcting the documents, not by adding
fourteen `*_en` columns**. `ARCHITECTURE.md:13` named `OpenAIProvider` and `GeminiProvider`; neither has
ever existed. Its `confidence (low/med/high)` was wrong -- the shipped enum is `low`/`medium`/`high`. Its
"all cards' text joined with markers" input description described a capability that does not exist. Its
`ad_analysis`/`ai_jobs` sketch was corrected to typed, copy-scoped columns and to call-attempt records.

**Tests:** 51 new in `test_ai_analysis.py`, plus the existing `test_ai_provider.py` updated for the new
return type (the protocol change is mandated by the contract, so its assertions now read `.analysis`).
Focused S3.1 suite **51 passed**; AI provider + data provider contracts + errors + mock + job queue
**120 passed**; S2 media/status/hash/ad-persistence regression **305 passed**; schema/models/migrations +
collection ordering **passed after updating the revision-chain assertions for `0009`**.

**Six mutations verified, all detected:**

| Mutation | Caught by |
|---|---|
| per-run cap never enforced | `test_the_cap_stops_scheduling_without_failing` |
| dedupe check removed at scheduling | 4 tests, incl. `test_duplicates_do_not_consume_the_budget` |
| more than one corrective retry | `test_exactly_one_corrective_retry` |
| retry loop never terminates | `test_a_second_invalid_response_produces_no_analysis` |
| duplicate analysis clobbers the winner | `test_a_lost_race_keeps_the_winners_row` |
| `CopyAnalysis` accepts unknown fields | `test_an_unknown_field_is_refused` + `test_ai_provider` |

**Three findings during the build, all real and all fixed:**
1. A provider that **raised** left no `ai_jobs` row at all -- the failure was invisible in the accounting
   table. Now every call is recorded, including one that raised, before the error propagates.
2. Usage reported on a call whose answer was **unusable** was discarded. The model was billed for it, and
   dropping the figure would make `ai_jobs` understate what S3.1 actually spent.
3. The post-conflict lookup reused the same function as the pre-insert optimisation, so a test that stubbed
   the optimisation also broke correctness. Split into `_already_analysed` (optimisation) and
   `find_existing` (correctness).

**Known limitations:**
- **No real provider exists.** Everything ran against `MockAIProvider`, which reads stored analyses keyed by
  `copy_hash`. No prompt has ever been sent to a model. **The prompt is unvalidated against a real model.**
- **No cost has ever been recorded.** `cost_*` is NULL on every row and no pricing method exists.
- **No worker exists.** `AGENTS.md` section 3 documents `python -m worker`; there is no such package. S3.1
  delivers the analysis service, job submission, and a handler callable by a future worker (D-E). Nothing
  consumes `ai.copy_analysis` jobs yet.
- **`provider_key` and `copy_hash` stability are unverified** against any real provider.
- **No English summary fields** -- a deliberate D-A decision, documented in `AGENTS.md` section 10.
- **`mypy backend` is now at 59 errors**, down from the recorded **61** baseline. S3.1 added **zero**:
  the two that went away were stale `type: ignore` comments in `test_ai_provider.py`, a file S3.1 had
  to edit anyway for the `AIResult` return change, and they are now correct. The remaining 59 are
  pre-existing in S0.3/S1.x test files. The project gate is the `mypy` project config, which is clean.
- **Windows `TEMP`/`TMP`: 11 pre-existing `PermissionError` errors** in `test_media_store.py` /
  `test_offline_guard.py` under the default temp path. Set `TEMP`/`TMP` to
  `C:\Users\DELL\AppData\Local\Temp\opencode` before counting the suite on this machine.
- **Integration tests require the PostgreSQL container** and are not skipped when it is down.

**Deferred deliberately:** a real AI provider and SDK (needs an `AGENTS.md` section 12 amendment), the
worker consumer loop, an API surface for triggering analysis, English summary fields, media byte
acquisition, `S3Store`, and `creative_hash` v2.

---

## 2026-10-02, Checkpoint S3.2 -- ad read API, search, CSV export

Approved on the explicit go-ahead given at the start of this session. Resumed once after a Plan-mode
interruption; no work from before the interruption was discarded.

**Scope shipped.** `GET /ads`, `GET /ads/{id}`, `GET /ads/{id}/snapshots`, `GET /exports/ads.csv`. Four
routes, all reads. No route calls `AIProvider`, enqueues a job, fetches media, or writes anything --
analysis is *surfaced* here, never *caused*, so a page view cannot spend money or start a collection.

**Files added**
- `backend/app/schemas/ads.py` -- hand-written response models, `extra="forbid"`. Not
  `from_attributes` wrappers: adding a table column must never silently publish it.
- `backend/app/services/ad_query.py` -- filters, allowlisted sort, paging, batched assembly.
- `backend/app/services/ad_search.py` -- the copy projection, `tsvector` and trigram matching.
- `backend/app/services/ad_csv.py` -- formula-injection defence, NULL rendering, the row cap.
- `backend/app/api/ads.py`, `backend/app/api/errors.py` -- routing and serialisation, no SQL.
- `backend/app/main.py` (rewritten) -- router inclusion, exception handlers, docs gating.
- `backend/tests/asgi_client.py`, `backend/tests/test_api_ads.py` -- 98 tests.
- `database/migrations/versions/0011_api_search_indexes.py` -- two GIN expression indexes.

**Decisions locked**
- **One row per ad, with `contexts[]`. There is no ad-level `current_status` anywhere.** S2.3 gives each
  `(ad, Page, country)` its own conclusion; a scalar would assert one as the whole truth. Pinned by
  `test_there_is_never_an_ad_level_status`.
- **Analysis joined on `latest_snapshot.copy_hash -> ad_analysis.copy_hash`,** never on
  `source_ad_snapshot_id`, so copy-scoped reuse actually reaches every ad running the same words.
- **`AI_INTERPRETATION` travels in the payload,** in JSON and in the CSV. Joining to `ads.data_origin`
  would otherwise let a client present model output as `PROVIDER_DATA`.
- **Media exposes references only,** with `bytes_available: false` hard-coded. No `storage_key`.
- **CSV is one row per ad per context**, header always, ISO-8601 UTC, NULL as an empty cell, formula
  prefixes neutralised, and **413 rather than truncation** above `MAX_EXPORT_ROWS`.
- **Filter errors are 400, not 422.** 422 is reserved for a request FastAPI could not parse; a client
  that sees 422 retries the same broken request forever. Page beyond the end is empty items plus the
  true total, not a 404.
- **`/docs` and `/openapi.json` are gated on `app_env`.** This closes the S0.1 review item, which could
  not be closed before any route existed.

**Four bugs found and fixed while building, all verified by mutation**

1. **The search query could never match its own index.** `normalized[name].astext` renders the JSON key
   as a *bind parameter*. Verified against the live schema with `EXPLAIN`: on a **custom plan**
   PostgreSQL substitutes the value and the index is used, so search looks healthy at first; under a
   **generic plan** -- which PostgreSQL switches to after five executions, the normal steady state for a
   hot query -- the key is a `Param`, the expressions do not match, and the query falls back to a
   sequential scan. Correct results, no error, no signal. Fixed with `literal_column` for the keys, the
   `' '` separator, the `coalesce` default and the `'simple'` config, so the query is byte-for-byte the
   index expression. **The fix was verified with `EXPLAIN EXECUTE` under `plan_cache_mode =
   force_generic_plan`**, not assumed; the parameterised form was confirmed not to match.
2. **`_apply_filters` implemented none of the context filters.** `country`, `facebook_page_id`,
   `current_status`, `provider_active` and `competitor_id` were accepted by the route, validated, and
   then silently ignored. Found because two tests failed; restoring the original `list_ads` behaviour did
   not make them pass, which is what identified it as a real defect rather than a bad test.
3. **`with_media` defaulted to off in the service,** so the list endpoint and the CSV always reported
   zero media. The router and the exporter now ask for it explicitly.
4. **`literal_column` for `'simple'`** -- part of fix 1; a bound REGCONFIG is a `Param` too.

**Migration `0011_api_search_indexes`.** Additive only: two GIN expression indexes, no column, no table,
no row. `op.create_index` could not build either of them -- it quotes a plain string as an *identifier*
("column does not exist"), and `sa.text()` then makes `postgresql_ops` render the opclass inside the
concatenation ("syntax error at `||`"). An opclass on an expression index needs its own parentheses in
PostgreSQL, which no helper expresses, so both are written as explicit SQL.

**Three copies of the projection, deliberately.** `services/ad_search.py` (query), `models/ads.py`
(index declaration), migration `0011` (DDL). `models` must not import from `services`, and a migration
should record what the rule *is*. Drift between them is silent and expensive, so
`test_every_copy_of_the_search_projection_agrees` compares all three, and
`test_the_search_query_matches_the_index_expression_exactly` pins every literal so none can quietly
become a bind parameter again.

**`alembic check` needed an `include_object` hook.** PostgreSQL deparses a stored expression with
`::text` and `::regconfig` casts that SQLAlchemy never emits, so autogenerate reported both indexes as
*remove and add*. `migrations/env.py` now excludes those two by name. Excluding them is the honest fix:
a permanently red gate stops being read, and a real change to any table, column, constraint or ordinary
index is still caught.

**Test infrastructure: no new dependency.** `fastapi.testclient.TestClient` requires `httpx`, which this
project does not install. Adding a package is a decision for a human, so `tests/asgi_client.py` drives
the ASGI application directly -- roughly 60 lines, in-process, no network. The tests therefore exercise
the *real* application: routing, dependency overrides, exception handlers, status codes and all. Two
harness facts worth recording:
- the driver advertises ASGI `spec_version` **2.4**. Below 2.4 Starlette races `stream_response` against
  a task waiting for `http.disconnect`, and a `receive()` that returns promptly cancels the stream before
  a single body chunk is sent -- the CSV endpoint came back **200 with an empty body**. That was a
  harness artefact, not an application defect.
- Starlette's `ServerErrorMiddleware` sends a 500 and *then* re-raises, so the driver reads the response
  from whatever was sent and only re-raises if nothing was sent. This is what
  `TestClient(raise_server_exceptions=False)` does.

**Tests.** `test_api_ads.py`, **98 tests, all passing**. Two mutations were applied, confirmed to have
changed the code, run, and reverted: reverting the JSON key to a bind parameter failed 3 tests, and
disabling the context filters failed 2. Regression on `test_migrations.py`, `test_models.py`,
`test_db_integration.py`, `test_architecture_boundaries.py`, `test_media_url_security.py`,
`test_config.py`, `test_fixture_safety.py`: **221 passing**. `test_migrations.py` needed its expected
revision list updated to include `0011_api_search_indexes`.

**Gate status.** `ruff check backend` clean; `ruff format --check` clean; project-gate `mypy` clean
(54 files); `alembic check` reports no drift; `alembic current` = `0011_api_search_indexes (head)`, single
head. `mypy backend` is at **59**, unchanged from the S3.1 baseline -- S3.2 added zero.

**Documentation corrected.** `ARCHITECTURE.md`'s API section claimed filters and routes that do not exist
(`platform`, `media_type`, `funnel_stage`, min/max duration, `/ads/{id}/analyze`, `/healthz`); it now
separates what shipped from what is planned, and records the search, CSV and provenance rules. The
`PROJECT_MEMORY.md` line calling S3.1 unpushed is corrected.

**Not corrected, deliberately.** `0001_pg_trgm`'s docstring says the first GIN trigram index comes in
"S1.1". It came in S3.2. The file is an applied migration and a historical record, so its prose was left
alone rather than rewritten; noted here instead.

**Known limitations**
- **Every table is still 0 rows**, so no query plan, index choice or paging behaviour has been
  validated against real data. The `EXPLAIN` results above prove the index *matches*; they cannot prove
  it is chosen once there are rows to choose between.
- **`_assemble` issues 5 queries per page** (4 + the count). The count is asserted fixed across page
  sizes 1 and 5, which catches an N+1, but the number itself is not a tuned figure.
- **`provider_active` filtering is `IS true/false`.** An ad with no context row is therefore excluded by
  any context filter, which is correct but untested against a corpus where that is common.
- **No `/healthz`**, so compose cannot yet depend on this service.
- **No authentication.** Every endpoint is unauthenticated; this is a post-S3 seam and the docs gating
  is the only production hardening in place.
- **Timezone inputs are naive-parsed.** `first_seen_from` without an offset is interpreted by FastAPI as
  UTC, which is right for this product but is FastAPI's default rather than an explicit decision here.
- **`MediaReferenceOut.bytes_available` is a hard-coded `false`**, correct until a byte-acquisition
  checkpoint exists. Nothing verifies it against `storage_key` being NULL.
- **Search covers four copy fields only.** `destination_url` is excluded deliberately; a user searching
  for a URL will not find it.

**Next checkpoint: not started, and not to be started without explicit approval.** The remaining S3
scope is the frontend Ad Library UI plus the operator surface (`/competitors`, `/collections`), `/healthz`,
and the worker consumer loop. Any of those needs a separate go-ahead.

### Three pre-existing red tests found while running the full suite

S3.2 ran the whole suite rather than only its own tests, which surfaced defects that
earlier checkpoints had shipped. **All three were confirmed against `origin/main`**
(`df3160d`, via a detached `git worktree`) before being touched, so none is an S3.2
regression, and none involved changing a shipped contract.

1. **`test_db_base.py::test_the_metadata_holds_exactly_the_s2_tables`** asserted
   `set(Base.metadata.tables) == S2_TABLES`. S3.1 added `ad_analysis` and `ai_jobs` and
   did not update it, so it has been **red since S3.1 was pushed**. `test_models.py` now
   has `S31_TABLES`, `S32_TABLES` (empty, and named anyway: "this checkpoint added
   nothing structural" is an assertion worth making) and `ALL_TABLES`, and the test
   asserts `ALL_TABLES`. Its name no longer says "s2".
2. **`test_offline_guard.py::test_the_ai_provider_works_with_sockets_blocked`** read
   `.language` off `analyze_copy`'s return value. S3.1 changed that return type to
   `AIResult(analysis, provider, model, usage)`, so the test raised `AttributeError` --
   **the no-network guard was not running at all**.
3. **`test_media_references.py::_positions`** read *every* `ad_snapshot_media` row into
   a dict keyed by `provider_key` with **no `ORDER BY`**. Once two snapshots held the
   same keys -- exactly the "a new key was added" case -- the dict kept whichever row
   PostgreSQL returned last, so `test_a_changed_key_set_makes_a_new_snapshot_which_takes_new_positions`
   flipped between the first snapshot's ordinals and the second's. It failed roughly
   **one full-suite run in three** and passed whenever the file ran on its own. Now
   scoped to a named snapshot with an explicit `ORDER BY`.

**A permanently red gate is worse than no gate**, which is the through-line: all three
were assertions that would have caught a real problem and had been failing silently
since they were written. S3.2 fixed them rather than reporting a green suite it knew
was not true. The lesson recorded for future checkpoints: **run the full suite before
claiming a checkpoint is green.** A green assertion nobody re-ran is not a guarantee.

**Suite state after the fixes: 1130 passed, 0 failed, four consecutive full runs.**

### Two stale doc references left uncorrected

`test_ads.py` and `test_models.py` both refer to a `test_schema_integration` that does
not exist under that name. Pre-existing, outside S3.2, left alone.

---

## 2026-10-02, S3.2 fix pass -- export 413 and platform visibility

Follows a read-only pre-push review of `574daaa`. `574daaa` was **not** amended; this is a new commit.

### The blocker: the CSV 413 could not happen

**Root cause.** `stream_ads_csv` is a **generator function** (`yield` at its body). Calling it executes no code and
returns an iterator. Starlette's `StreamingResponse.stream_response` sends `http.response.start` -- status line and
headers -- and only *then* iterates the body (verified in the installed
`.venv/Lib/site-packages/starlette/responses.py`). So `CsvExportTooLarge`, raised inside `iter_export_rows`, could only
be raised **after** the client already held a 200 and `Content-Disposition: attachment`.

The route's `try/except CsvExportTooLarge` around `stream_ads_csv(...)` was therefore **dead code**. The export was
answered with **200 and a truncated body** -- exactly the outcome the module exists to prevent.

**The test had certified the bug.** `test_a_413_is_returned_for_an_oversized_export` replaced `stream_ads_csv` with a
*plain function* that raised eagerly, so it proved only that the route could translate an exception into a 413. It
never touched the generator, so it passed while the product truncated.

**Fix.** `count_export_rows(session, filters, max_rows)` -- a plain function, no `yield` -- now decides the cap, and
the route calls it **before** constructing the `StreamingResponse`. Two or three count queries; nothing is buffered.
It counts **rows**, not ads: rows = context rows + context-free ads. `ads + context rows` was tried first and is
wrong -- it double-counts every ad that *has* a context, which made a 2-row export report 4 and refused a legal export
(caught by `test_an_export_exactly_at_the_cap_is_allowed`). Counting ads alone would be worse: a many-context ad would
clear the preflight and overrun mid-stream, the same truncation by a different road.

The generator still re-checks, now explicitly labelled a backstop rather than the gate. The one uncovered edge: rows
written *between* the preflight and the stream can still trip it, and closing that would mean buffering the whole
file -- the thing streaming exists to avoid. Documented rather than hidden.

**New tests, all over real HTTP.** Only the cap *constant* is patched (configuration, not behaviour); the route,
preflight, count query, generator and HTTP framing are all the shipped ones.
`test_an_oversized_export_is_a_413_over_real_http`, `test_a_413_carries_no_csv_body_and_no_attachment_header`,
`test_a_413_detail_is_stable_and_leaks_nothing`, `test_an_export_exactly_at_the_cap_is_allowed` (inclusive boundary),
`test_one_row_over_the_cap_is_refused` (cap+1), `test_the_cap_counts_rows_not_ads`,
`test_a_normal_export_is_still_streamed_as_200`.

**Mutation-verified.** Removing the preflight -- restoring the original broken shape -- fails **5** of them. The old
mocked test would still have passed.

### Platform visibility

Platform **visibility** was product-required and was stored all along; only the deferred **filter** was ever meant to
wait. `normalized` is the full `RawAdRecord.model_dump()`, so platforms were already there.

`snapshot_platforms(snapshot)` in `services/ad_query.py` reads them out. **No column, no index, no hash moved, and
`normalized` is not modified** -- pinned by `test_platform_visibility_added_no_column_and_no_index`. Exposed as
`platforms` on `/ads` (latest snapshot), `/ads/{id}` (latest snapshot), `/ads/{id}/snapshots` (**each snapshot's
own** -- a snapshot is an observation, and platforms can differ between two observations of one ad), and a `platforms`
column in CSV.

Semantics: provider order preserved, never sorted or de-duplicated; non-`str` members skipped rather than coerced
(`str(7)` would invent a platform named "7"); `[]` / empty cell means *the stored record lists none*, never "this ad
ran nowhere". Serialised as a JSON array (a `tuple` in the model, consistent with `contexts` and `media`).

Two tests were first written to mutate a stored snapshot's `normalized` and were refused by the **append-only
trigger** (`RestrictViolation: ad_snapshots is append-only`). That refusal is the design working, so both were rewritten
as pure-function tests over a stub instead of being worked around.

### CSV filter parity

The route docstring claimed "the same filters as `/ads`" while omitting `first_seen_from/to` and `last_seen_from/to`.
Chose the code fix, not the weaker sentence. All four now feed the same `AdFilters`. Proven by
`test_the_csv_accepts_every_filter_ads_does`, which compares the two **live routes'** OpenAPI parameters rather than a
restated list, plus two narrowing tests and one widening test so the narrowing test cannot pass by filtering
everything.

### Incidental test-helper fix

`_page()` is now idempotent. `facebook_pages.page_id` is globally unique, so a second call raised `UniqueViolation`
instead of returning the row it had already made -- making helpers awkward to compose and turning "call `_page` again"
into a test bug.

### Not touched, deliberately

The search implementation, the two GIN indexes, migration `0011`, the three pre-existing test repairs, and every S2 /
S3.1 contract. `/ads` page-size semantics and the export cap value are unchanged.

### Validation

`test_api_ads.py` **118 passed** (was 98; +20). Targeted regressions: `test_ads`, `test_models`, `test_db_base`,
`test_architecture_boundaries`, `test_offline_guard`, `test_media_url_security`, `test_fixture_safety`,
`test_ai_analysis` -- **428 passed** with the S3.2 file. Then `test_media_references`, `test_migrations`,
`test_config` -- **74 passed**. No full suite, no xdist, no parallel runs.

`ruff check backend` clean. `ruff format --check backend` clean. Project-gate `mypy` clean (54 files). `mypy backend`
back at **59**, unchanged. `alembic check` reports no drift and `alembic current` is `0011_api_search_indexes (head)`;
run only as a read-only confirmation that this pass did not disturb model metadata, since no migration or model file
changed.

### Known limitations carried forward

Unchanged from the S3.2 entry, and still true: every table holds 0 rows, so no query plan or index *selection* has been
exercised -- only index *matching*; no relevance ranking, only deterministic `last_seen_at DESC, id DESC` ordering;
combined context filters are independent `EXISTS` clauses, so `competitor_id` + `country` + `current_status` can be
satisfied by different contexts of one ad; `direction` invalid yields 422 while `sort` invalid yields 400;
`MediaReferenceOut.bytes_available` is a hard-coded `false`; no `/healthz`; no authentication, by design.

---

## 2026-10-02, S3.3 step 1 -- competitors directory API

First step of S3.3. **Backend only**: one read-only endpoint, added because S3.3
discovery found the frontend had no way to name a competitor. Everything else S3.3
needs -- the seed script, the AI fixture re-keying, the frontend itself, and the
full documentation reconciliation -- is **not started**.

**Decision applied.** Option (a) from the discovery: a nested competitor directory,
rather than denormalising names into `/ads`. No denormalisation, so `/ads` keeps the
lean, non-joining shape S3.2 shipped, and one endpoint answers "which brands, which
Pages" instead of three lookups.

**`GET /competitors`** -- `CompetitorListOut { items }`, `CompetitorOut { id, name,
created_at, pages }`, `FacebookPageOut { id, page_id, name|null, url|null, country,
is_tracked, tracking_frequency, created_at }`. All three `extra="forbid"`.

- **No migration.** `competitors` and `facebook_pages` exist since S1.1, and
  `ix_facebook_pages_competitor_id` already exists with a comment saying it serves
  `/competitors/{id}/pages` -- the index was built for an endpoint that was never
  written. `alembic check` still reports no drift and a single head.
- **No provenance fields.** `models/tracking.py` is explicit that neither a
  competitor nor a Page is collected data, so neither carries `data_origin` or
  `evidence_class`. Stamping `PROVIDER_DATA` on a Page would also imply the
  operator's own tracking list is third-party data. Pinned by
  `test_no_provenance_field_is_exposed`.
- **Untracked Pages are returned**, with `is_tracked: false`. `ad_snapshots` is
  append-only with `RESTRICT` FKs, so hiding a Page would hide real history behind a
  soft delete the schema does not have.
- **No ad or run counts.** A count beside a competitor name invites reading it as
  performance, and this product cannot measure performance at all.
- **No `updated_at`.** It is on both tables and trivially available, but nothing
  acts on it and shipping it implies a freshness guarantee nobody has defined.
- Read-only by construction: two `SELECT`s, no collection, AI, media or queue work.

**One shared schema base.** `schemas/base.py` now holds `_Response`, and
`schemas/ads.py` imports it instead of defining its own. S3.3 schemas adopt the same
rule rather than copying four lines -- two definitions of "closed and frozen" would
eventually disagree about whether an unexpected field is an error.

### Two findings, both from mutation testing, both mine

1. **I wrote a false statement about PostgreSQL.** A docstring claimed the default
   ordering was `NULLS FIRST` for `ASC`. It is the opposite: PostgreSQL defaults to
   `NULLS LAST` for `ASC` and `NULLS FIRST` for `DESC`. The mutation (deleting the
   explicit `.nulls_last()`) passed, which is how the error surfaced. The clause is
   kept -- it states intent and guards a future direction change, since `DESC`
   really does default to the other behaviour, which is why
   `services/ad_query.resolve_sort` overrides it explicitly -- but the comment and
   `test_pages_with_no_name_sort_last` now describe what it protects rather than
   claiming a difference that does not exist.

2. **My determinism test proved nothing.** It called the endpoint three times and
   compared the results, which passed even with the `id` tie-break deleted: one
   connection and one plan returns the same rows in the same order regardless.
   Rewritten as `test_equal_competitor_names_are_broken_by_id`, which asserts the
   expected order (ties broken by ascending id). It now fails when the tie-break is
   removed. **Repeating a request is not a test of determinism; asserting the order
   is.**

Also mutation-verified: returning a fresh UUID instead of the row's real id fails
both round-trip tests.

### The tests that matter

`test_a_competitor_id_from_here_filters_ads` and `test_a_page_id_from_here_filters_ads`
are the point of the endpoint. Without them it would be decorative: a directory
whose ids do not actually filter `/ads` leaves the frontend exactly where it
started. The ads are persisted through `persist_observations`, because `/ads`
filters resolve through `ad_status_by_context` and a hand-inserted `Ad` would not
exercise that path at all. `test_the_context_reports_the_same_page_id_the_directory_lists`
pins that one id space serves both, so a client never has to translate.

**`test_api_competitors.py`: 19 tests, all passing.** Targeted regression with
`test_api_ads.py`, `test_architecture_boundaries.py`, `test_media_url_security.py`,
`test_offline_guard.py`: **264 passing**. No full suite, no xdist, no parallel runs.

One pre-existing test updated rather than weakened:
`test_exactly_the_four_s32_routes_are_registered` asserted exactly four paths and is
necessarily five now. Renamed `test_the_s32_ad_routes_are_registered` and extended
with `/competitors`; it still pins the whole set.

**Gates.** `ruff check` clean on every changed file. `ruff format --check` clean.
Project-gate `mypy` clean (58 files). `mypy backend` **59**, unchanged. `alembic
check` no drift, single head `0011_api_search_indexes`.

**Documentation.** Only `ARCHITECTURE.md`'s API surface, because it claimed four
shipped routes and "nothing else exists yet", which this step made false. The wider
S3.3 reconciliation -- `README.md`, `SETUP_WINDOWS.md`, the `IMPLEMENTATION_PLAN.md`
S7-versus-S3.3 naming, and the PROJECT_MEMORY S3.3 entry -- is **deliberately
deferred** to the end of S3.3 so the docs describe what shipped rather than what was
planned.

**Known limitations, unchanged**

- Every table still holds **0 rows**, so no plan, index selection or query cost has
  been exercised on real data. Index *matching* is proven; index *selection* is not.
- No ad count per competitor. If the frontend wants "N ads for this competitor", it
  is a separate aggregate endpoint, not a field invented here.
- `/ads` carries no AI-interpretation availability field, so a grid cannot show
  "analysed" without fetching each row. Open from S3.3 discovery.
- `page_id` is exposed because it is the provider's own identity, different from the
  internal key. A client must use `id` for filtering and treat `page_id` as display
  or reconciliation data.

**Next step (not started, needs approval):** the safe seed path --
`scripts/seed_demo.py` driving `build_mock_pages` ->
`build_collection_orchestrator` -> `schedule_collection` -> `execute_collection_job`,
so the frontend is developed against real API-shaped rows produced by the real
collection path. That step also has to re-key `tests/fixtures/ai/analyses.json` by
the **real computed** `copy_hash`, because the three placeholder keys cannot satisfy
`ad_analysis.copy_hash`'s 64-hex `CHECK` and would otherwise yield all-null
interpretations.

---

## 2026-10-02, S3.3 step 2 -- safe demo seed path

Backend/scripting only. **The frontend is not started.** The AI fixture re-keying is
also not started, and `analyses.json` was not touched.

**`scripts/seed_demo.py`.** Creates only a `Competitor` and three `FacebookPage` rows
itself -- both operator configuration rather than collected data -- and then drives
`build_mock_pages()` -> `build_collection_orchestrator()` -> `schedule_collection` ->
`queue.claim()` -> `execute_collection_job`, which is the same entry point
`python -m worker` calls. No persistence logic is duplicated: the job-to-run linkage
is read out of the claimed job's payload exactly as `worker/__main__.py` does, because
re-deriving it from a query would be a second implementation of the same rule.

**Verified by hand, end to end**: 9 ad records across 3 pages produced 8 `ads`, 8
`ad_snapshots`, 8 `ad_status_by_context`, 8 `media_assets`, 9 `ad_snapshot_media` and
33 `provider_runs` / `raw_responses`. The corpus deliberately repeats `mock-ad-000101`
across two batches of one page, and the repeat collapsed to one ad -- the content-hash
dedupe working, observed rather than assumed.

### A pre-existing production bug, found because the seed had to work

`composition.build_mock_pages()` passed the corpus's raw JSON `batches` straight into
`MockPage`, so `MockPage.batches` held `dict` objects. Every `MockProvider.fetch_page_ads`
call then died on `batch.raw` with `AttributeError: 'dict' object has no attribute 'raw'`,
and `CollectionOrchestrator.execute_collection_job` swallowed it into
`INTERNAL_ERROR_MESSAGE`. **The only code path that calls this function --
`python -m worker` -- had therefore never run successfully against the mock provider.**
It survived because `json.loads` returns `Any`, so mypy could not see the mismatch,
and the tests never call it: they build their own corpus in `conftest.py`, which wraps
the batches correctly. Fixed by constructing `MockBatch(...)`, as `conftest.py` does.

### Two findings from getting the seed to work

- **`schedule_collection` returns a marker, not a job id, when it short-circuits.**
  If a PENDING or RUNNING run already exists for the page it returns
  `"run-<id>"` and enqueues nothing. So the seed cannot rely on its return value to
  identify its own job -- it drains the queue and matches on the payload instead.
  Draining also surfaced terminal runs: executing an already-finished run is a no-op
  reporting zero records, which reads exactly like a provider that served nothing.
  Terminal runs are now skipped explicitly.
- **`INTERNAL_ERROR_MESSAGE` promises "the worker log has the detail", and nothing
  logs it.** `execute_collection_job` catches bare `Exception` and writes only the
  generic pointer. The worker cannot help either, because the exception never escapes
  the orchestrator. Every internal collection failure is currently undiagnosable from
  the row and absent from the log. **Not fixed here** -- it is production behaviour in
  S1.x code and outside this step's scope.

### No `--with-ai`, and why

The stored mock analyses are keyed `mock-copy-hash-en-001` and friends, while
`ad_analysis.copy_hash` carries `CHECK (copy_hash ~ '^[0-9a-f]{64}$')`. Those keys can
never be stored, so `MockAIProvider` would miss on every real digest and return its
all-null analysis -- writing `ad_analysis` rows that read as "analysed" and say
nothing, which is worse than no analysis. Re-keying the fixture by the real computed
digest is a separate change and was not smuggled in. Asserted by
`test_the_analysis_fixture_keys_could_never_be_stored` and
`test_there_is_no_with_ai_flag_and_no_ai_import`.

### The end-to-end test was written, run, and then removed

It ran the real seed twice and compared counts. It worked, and it could **never be
run again**: `ad_snapshots` is append-only and its trigger refuses `DELETE` as well as
`UPDATE`, so a committed seed is permanent short of dropping the table or disabling
the trigger. The demo rows are also visible to other suites -- `test_ad_persistence`
counts `ads` inside its own transaction and sees committed ones. So the properties it
covered are pinned hermetically instead: the two reuse tests cover duplicate
competitor/Page creation, and snapshot idempotence is
`test_ad_persistence.py`'s own "an unchanged observation in a later run writes no
second snapshot". The `seed_live` marker was removed rather than left as a trap.

### Safety

Refuses `APP_ENV=prod` **before opening a connection** (asserted by replacing
`get_engine` with a raiser). Everything is inside function bodies behind
`if __name__ == "__main__"`, and an `ast` walk asserts no module-level statement can
execute on import. No flags are registered. Logged through `app.core.logging` rather
than `print`, matching `scripts/check_db.py`. No invented performance metric is
possible: there is no column to write one, asserted against `information_schema`.

**Idempotence.** Rerunning creates a new collection run -- real history -- and
adds `seen_in_run` links, while `content_hash` dedupe means **no second snapshot** for
any ad. Competitor reuse matches on name (the column is deliberately not unique);
Page reuse matches on `page_id` (globally unique). Nothing is deleted or reset.

### **Outstanding problem: the development database now holds unremovable demo rows**

Diagnosing the `MockBatch` bug required running the seed for real. That committed
**1 competitor, 3 pages, 8 ads, 8 ad_snapshots, 8 ad_status_by_context, 45 seen_in_run,
8 media_assets, 9 ad_snapshot_media, 33 provider_runs, 33 raw_responses and 31
collection_runs** to the development database.

They **cannot be deleted.** `ad_snapshots` refuses `DELETE` via its append-only
trigger, and `ads` is therefore blocked by the foreign key. Two narrowly-scoped
cleanup attempts were made, both inside a transaction, both rolled back cleanly on the
trigger's refusal; the database is intact and no destructive command was run.

Consequence: **48 count-based tests are now red** -- 21 in `test_ad_persistence`,
18 in `test_api_ads`, 5 in `test_api_competitors`, 3 in `test_collection_ordering`,
1 in `test_collection_hardening`. They fail because they count rows and the
committed demo rows are visible to them. `test_mock_provider`, `test_job_queue` and
`test_db_session` are green, which independently confirms the `MockBatch` fix did not
break those layers.

**This needs a human decision.** The fix is to reset the development database
(`docker compose down -v`, `up -d`, `alembic upgrade head`), which is a destructive
action this session will not take unasked. Until then the suite is red for
environmental reasons, not because of any code change in this step.

**Known limitations**
- No end-to-end automated test, by the reasoning above. The flow was verified by hand.
- The corpus spans `IN`, `GB`, `IE` and `US`; only 6 of 9 ads include `IN`, and
  `MockProvider` ignores the requested country. So `ad_status_by_context.country` is
  the **run's** scope, not the ad's `targeted_countries`, which stays in `normalized`.
  An earlier docstring claimed every ad targeted `IN` -- false, and corrected.
- A foreign job is leased and skipped, never executed, completed or failed. Its lease
  expires on its own, so this is recoverable rather than destructive, but this script
  will re-lease such a job on every run.
- The development database carries two pre-existing `pending` jobs whose payload is
  the literal string `'same-run'` -- not a UUID, so they cannot resolve to a run.
  They predate this step and were left alone.

**Next step (not started, needs approval):** re-key `tests/fixtures/ai/analyses.json`
by the real computed `copy_hash`, so the AI panel can be developed against real
interpretations rather than an all-null one.

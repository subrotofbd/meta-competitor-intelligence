"""Typed application settings, loaded from the environment or a local `.env`.

Single source of truth for runtime configuration. Nothing else in the codebase
should read `os.environ` for these values, and no secret is ever written here.

`database_url` is a `SecretStr`, so it cannot reach a log line or a traceback by
accident. Code that genuinely needs the plaintext DSN asks for it explicitly via
`Settings.dsn`, which makes every leak point greppable.

This module sits at the bottom of the dependency graph: it imports no project
layer and no framework.
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# psycopg 3 only. A bare `postgresql://` URL resolves to psycopg2 under
# SQLAlchemy, which this project does not use, so it is rejected rather than
# silently producing a confusing driver error at first connect.
_REQUIRED_DSN_SCHEME = "postgresql+psycopg://"

#: How long a worker holds a job lease. Mirrored from
#: `app.services.jobs.DEFAULT_LEASE_DURATION` rather than imported, because
#: `core` sits at the bottom of the dependency graph and must not import a
#: service to read one number. The staleness check below compares against it, so
#: a divergence would be caught at startup rather than at 3am.
_DEFAULT_LEASE_DURATION = timedelta(minutes=5)

#: Bounds on one collection run. See the fields on `Settings` for what each is
#: for and why neither is a product statement. Defined here so the service layer
#: and the settings share one number rather than two that can drift.
DEFAULT_COLLECTION_MAX_RECORDS_PER_RUN = 10_000
DEFAULT_COLLECTION_MAX_PAGES_PER_RUN = 200
DEFAULT_COLLECTION_STALE_RUN_TIMEOUT = timedelta(minutes=30)

#: Bounds on one AI analysis run. Same reasoning as the collection bounds: an
#: operation budget, not a product claim. There is no number of ads a competitor
#: "should" have analysed, and putting one in a config file would be a business
#: judgement dressed as a setting.
DEFAULT_AI_MAX_ANALYSES_PER_RUN = 50
DEFAULT_AI_ANALYSIS_TIMEOUT_SECONDS = 60
DEFAULT_AI_MAX_RESPONSE_CHARS = 64_000


class AppEnv(StrEnum):
    """Deployment environment. Selects defaults and turns on safety checks."""

    LOCAL = "local"
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(StrEnum):
    JSON = "json"
    TEXT = "text"


class Settings(BaseSettings):
    """Runtime configuration. Every value comes from the environment.

    `extra="ignore"` is deliberate: `.env` also holds the `POSTGRES_*` values
    that docker compose consumes, and those are not application settings.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Redact the offending input from validation errors. Without this,
        # Pydantic appends the raw value to the message, so a rejected DSN would
        # carry the database password into logs, startup output and bug reports
        # even though the field itself is a SecretStr.
        hide_input_in_errors=True,
    )

    app_env: AppEnv = AppEnv.LOCAL

    log_level: LogLevel = LogLevel.INFO
    log_format: LogFormat = LogFormat.JSON

    # Required, with no default: a guessed database password must never be
    # possible. Absence fails loudly at startup instead.
    database_url: SecretStr

    # Logs every statement *and its bound parameters*. Safe locally, a
    # credential leak in production -- blocked by the validator below.
    database_echo: bool = False

    # ---- Collection safety settings -------------------------------------
    #
    # Operational bounds, not product policy. None of these says anything about
    # how many ads a competitor "should" be running: there is no such number in
    # the product, and putting one in a config file would be a business claim
    # dressed as a setting. They exist because an unbounded collection run has
    # failure modes that end with data we cannot get back. The reasoning lives
    # once, in ARCHITECTURE.md under "Collection safety".

    #: How many records one run reads across all its pages before it stops
    #: walking. Counts records *attempted*, readable or not, because a provider
    #: serving only unreadable records would otherwise never move this number.
    #:
    #: Bounds accumulation across pages. It does **not** bound what one page may
    #: contain: a single page larger than this is still stored and still read
    #: whole, because the raw response is the evidence and dropping readable
    #: records to satisfy a memory bound would be the wrong trade. Use
    #: `collection_max_pages_per_run` to bound page count, not this.
    collection_max_records_per_run: int = Field(
        default=DEFAULT_COLLECTION_MAX_RECORDS_PER_RUN, gt=0
    )

    #: How many provider pages one run may fetch before it stops walking.
    #:
    #: The third independent guard, and the only one that survives a provider
    #: offering nothing: a provider that returns an empty or wholly unreadable
    #: page with a fresh cursor each time never repeats a cursor (so the cycle
    #: guard never fires) and never grows the record count (so the record
    #: ceiling never fires), and would otherwise be called for ever, committing
    #: a row each time. Two hundred pages is far above any real page and far
    #: below anything that troubles a database.
    collection_max_pages_per_run: int = Field(default=DEFAULT_COLLECTION_MAX_PAGES_PER_RUN, gt=0)

    #: How long a collection run may show no sign of progress before it is
    #: treated as abandoned. A run is only eligible when it is `running`, no job
    #: for it holds a live lease, **and** it has added no provider call in this
    #: long -- so all three must agree, and a slow run that is still making
    #: progress is never taken from a live worker.
    #:
    #: Validated below against the job lease. A value at or under the lease
    #: would make every legitimately long run look abandoned, which is a
    #: config typo that silently fails runs, so it is a startup error.
    collection_stale_run_timeout: timedelta = DEFAULT_COLLECTION_STALE_RUN_TIMEOUT

    # ---- AI copy analysis settings --------------------------------------
    #
    # S3.1 ships no SDK and no real provider (`AGENTS.md` section 12 forbids one
    # in S0-S3), so the only provider that can be configured here is the mock.
    # The settings exist now so that adding a real provider later is a
    # configuration change rather than a code change, and so that the *bounds*
    # -- which matter regardless of provider -- are settled and visible.

    #: Which copy-analysis provider to build. `AGENTS.md` section 49 keeps model
    #: names out of business logic, and this is where the choice is made.
    ai_provider: str = "mock"

    #: The model identifier handed to the provider. NULL means "whatever the
    #: provider reports", which is the honest answer when it reports nothing.
    #: Never a production model name written into a service.
    ai_model: str | None = None

    #: The provider credential. `SecretStr` for the same reason `database_url`
    #: is: a key that cannot be interpolated into a log line cannot leak into one
    #: by accident. It is never persisted -- not in `ai_jobs`, not in
    #: `jobs.payload`, not anywhere -- and `AGENTS.md` section 6 forbids pointing
    #: a provider at a plaintext `http://` endpoint while holding one.
    ai_api_key: SecretStr | None = None

    #: How many ads one collection run may have analysed.
    #:
    #: Counts analyses **scheduled by this run**, not provider calls, and a
    #: duplicate `(copy_hash, analysis_version)` costs nothing and consumes
    #: nothing -- a re-run over unchanged copy schedules nothing at all. Reaching
    #: the cap is a budget decision, not a run failure: no error is raised and no
    #: run is marked failed, because the ads simply have not been analysed yet.
    ai_max_analyses_per_run: int = Field(default=DEFAULT_AI_MAX_ANALYSES_PER_RUN, gt=0)

    #: How long one provider call may take before it is treated as transient.
    #: A model that has not answered in a minute is not going to answer the same
    #: question usefully on the next attempt either.
    ai_analysis_timeout_seconds: int = Field(default=DEFAULT_AI_ANALYSIS_TIMEOUT_SECONDS, gt=0)

    #: The largest answer accepted, checked **before** any JSON parsing, so a
    #: pathological response costs a length comparison rather than a parse.
    ai_max_response_chars: int = Field(default=DEFAULT_AI_MAX_RESPONSE_CHARS, gt=0)

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_dsn(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw.startswith(_REQUIRED_DSN_SCHEME):
            # Report only what precedes "://". Echoing the whole URL would put
            # the database password into a validation error, and those errors
            # reach startup logs and bug reports.
            scheme = raw.partition("://")[0] + "://"
            raise ValueError(
                f"database_url must use psycopg 3 and start with "
                f"{_REQUIRED_DSN_SCHEME!r}; got {scheme!r}"
            )
        return value

    @model_validator(mode="after")
    def _refuse_unsafe_prod_settings(self) -> Self:
        """Fail at startup rather than ship a production host that leaks its logs.

        Both rejected combinations are credential-exposure risks, not style
        preferences, which is why they are hard errors rather than warnings.
        """
        if self.app_env is not AppEnv.PROD:
            return self
        if self.log_level is LogLevel.DEBUG:
            raise ValueError("log_level=DEBUG is not allowed when app_env=prod")
        if self.database_echo:
            raise ValueError(
                "database_echo=true logs SQL and bound parameters; "
                "it is not allowed when app_env=prod"
            )
        return self

    @model_validator(mode="after")
    def _refuse_a_stale_timeout_below_the_job_lease(self) -> Self:
        """A run is declared abandoned after `collection_stale_run_timeout`.

        The signal that has to agree is a *live* job lease, and a lease lasts
        five minutes. A staleness timeout at or under that would mean a worker
        doing a perfectly ordinary job had its run marked `failed` underneath
        it -- the page re-collected concurrently, and the worker's own commit
        then overwrites the recovery. That is a config typo silently losing runs,
        so it is refused at startup rather than discovered in production.
        """
        if self.collection_stale_run_timeout <= _DEFAULT_LEASE_DURATION:
            raise ValueError(
                "collection_stale_run_timeout must exceed the job lease "
                f"({int(_DEFAULT_LEASE_DURATION.total_seconds())}s), or a worker "
                "mid-run will have its run marked failed; got "
                f"{int(self.collection_stale_run_timeout.total_seconds())}s"
            )
        return self

    @property
    def dsn(self) -> str:
        """The plaintext DSN, for handing to a driver. Never log the result."""
        return self.database_url.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, built once and reused.

    Cached because the environment does not change mid-process. Tests that
    change environment variables must call `get_settings.cache_clear()`.
    """
    # `database_url` is deliberately required, but pydantic-settings supplies it
    # from the environment at runtime. Mypy only sees the Python signature and
    # cannot know that, so the "missing argument" it reports is a false positive
    # -- the call still raises ValidationError at startup if the variable is
    # genuinely absent.
    return Settings()  # type: ignore[call-arg]

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

from enum import StrEnum
from functools import lru_cache
from typing import Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# psycopg 3 only. A bare `postgresql://` URL resolves to psycopg2 under
# SQLAlchemy, which this project does not use, so it is rejected rather than
# silently producing a confusing driver error at first connect.
_REQUIRED_DSN_SCHEME = "postgresql+psycopg://"


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

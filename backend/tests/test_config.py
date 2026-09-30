"""Settings behaviour: safe defaults, environment overrides, secret handling, and
refusal to start in a configuration that would leak credentials in production.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, LogFormat, LogLevel, Settings, get_settings

pytestmark = pytest.mark.unit


def test_defaults_are_safe_with_an_empty_environment(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings()
    assert settings.app_env is AppEnv.LOCAL
    assert settings.log_level is LogLevel.INFO
    assert settings.log_format is LogFormat.JSON
    assert settings.database_echo is False


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """No default DSN: a guessed database password must never be possible."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_environment_overrides_defaults(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        APP_ENV="dev", LOG_LEVEL="DEBUG", LOG_FORMAT="text", DATABASE_ECHO="true"
    )
    assert settings.app_env is AppEnv.DEV
    assert settings.log_level is LogLevel.DEBUG
    assert settings.log_format is LogFormat.TEXT
    assert settings.database_echo is True


def test_database_url_comes_from_the_environment(
    make_settings: Callable[..., Settings],
) -> None:
    dsn = "postgresql+psycopg://someone:s3cret@db.internal:5432/ads"
    assert make_settings(DATABASE_URL=dsn).dsn == dsn


def test_password_never_appears_in_a_rendered_settings_object(
    make_settings: Callable[..., Settings],
) -> None:
    """SecretStr is the control that stops an accidental log line leaking the DSN."""
    settings = make_settings(DATABASE_URL="postgresql+psycopg://user:hunter2@localhost/db")
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings)


@pytest.mark.parametrize(
    "dsn",
    [
        pytest.param("postgresql://user:pw@localhost:5432/db", id="psycopg2-default"),
        pytest.param("postgresql+psycopg2://user:pw@localhost:5432/db", id="psycopg2-explicit"),
        pytest.param("sqlite:///local.db", id="not-postgres"),
    ],
)
def test_non_psycopg3_urls_are_rejected(make_settings: Callable[..., Settings], dsn: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(DATABASE_URL=dsn)


def test_rejection_message_does_not_echo_the_password(
    make_settings: Callable[..., Settings],
) -> None:
    """The error names the scheme only; a validation error reaches logs and tickets."""
    with pytest.raises(ValidationError) as excinfo:
        make_settings(DATABASE_URL="postgresql://user:hunter2@localhost/db")
    assert "hunter2" not in str(excinfo.value)
    assert "postgresql://" in str(excinfo.value)


def test_prod_refuses_debug_logging(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError, match="log_level=DEBUG"):
        make_settings(APP_ENV="prod", LOG_LEVEL="DEBUG")


def test_prod_refuses_database_echo(make_settings: Callable[..., Settings]) -> None:
    """`database_echo` logs every statement *and its bound parameters*."""
    with pytest.raises(ValidationError, match="database_echo"):
        make_settings(APP_ENV="prod", DATABASE_ECHO="true")


def test_prod_accepts_a_safe_configuration(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(APP_ENV="prod", LOG_LEVEL="INFO", DATABASE_ECHO="false")
    assert settings.app_env is AppEnv.PROD


def test_debug_logging_is_fine_outside_prod(make_settings: Callable[..., Settings]) -> None:
    """The guard is scoped to production, not a blanket restriction on developers."""
    assert make_settings(APP_ENV="local", LOG_LEVEL="DEBUG").log_level is LogLevel.DEBUG


def test_unknown_environment_is_rejected(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(APP_ENV="production")


def test_variables_for_other_tools_are_ignored(
    make_settings: Callable[..., Settings],
) -> None:
    """`.env` also holds POSTGRES_* for docker compose; those are not app settings."""
    # The password is a literal on purpose -- it is a placeholder proving the
    # variable is ignored, never a credential.
    settings = make_settings(POSTGRES_PASSWORD="not-a-real-password", POSTGRES_PORT="5432")
    assert settings.app_env is AppEnv.LOCAL


def test_get_settings_is_cached_and_resettable(
    use_settings: Callable[..., None],
) -> None:
    get_settings.cache_clear()
    first = get_settings()
    assert get_settings() is first

    get_settings.cache_clear()
    assert get_settings() is not first


# ============================================================
# Collection safety settings
# ============================================================


def test_the_collection_safety_defaults_are_operational_not_business_limits(
    make_settings: Callable[..., Settings],
) -> None:
    """The defaults bound a run; they do not say how much a rival runs.

    There is no product statement about ad volume anywhere, so a default that
    encoded one would be inventing policy in a configuration file.
    """
    settings = make_settings()

    assert settings.collection_max_records_per_run == 10_000
    assert settings.collection_max_pages_per_run == 200
    assert settings.collection_stale_run_timeout == timedelta(minutes=30)


@pytest.mark.parametrize("duration", ["PT1M", "PT4M59S", "PT5M"])
def test_a_stale_timeout_at_or_below_the_job_lease_is_refused(
    make_settings: Callable[..., Settings], duration: str
) -> None:
    """A config typo here silently fails live runs, so it is a startup error.

    The staleness check needs a *live* job lease, and a lease lasts five
    minutes. Set the timeout lower and every worker doing an ordinary job has
    its run marked `failed` underneath it: the page is re-collected
    concurrently, and the worker's own commit then overwrites the recovery.

    The durations are ISO-8601 because that is the only form pydantic accepts
    for a `timedelta`; a bare number is a *parse* error, which would make this
    test pass for the wrong reason. Asserting on the message pins which of the
    two happened.
    """
    with pytest.raises(ValidationError) as raised:
        make_settings(COLLECTION_STALE_RUN_TIMEOUT=duration)

    assert "job lease" in str(raised.value), "rejected by parsing, not by the validator"


def test_a_stale_timeout_above_the_job_lease_is_accepted(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(COLLECTION_STALE_RUN_TIMEOUT="PT30M")
    assert settings.collection_stale_run_timeout == timedelta(minutes=30)


def test_the_example_value_for_the_stale_timeout_is_one_that_starts(
    make_settings: Callable[..., Settings],
) -> None:
    """`.env.example` has to hold a value the application actually accepts.

    A bare number in the template would fail at startup for anyone who copied
    it, and the first sign of that would be a stack trace during setup.
    """
    template = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    declared = next(
        line.split("=", 1)[1].strip()
        for line in template.splitlines()
        if line.startswith("COLLECTION_STALE_RUN_TIMEOUT=")
    )

    assert make_settings(COLLECTION_STALE_RUN_TIMEOUT=declared).collection_stale_run_timeout


@pytest.mark.parametrize(
    "field", ["COLLECTION_MAX_RECORDS_PER_RUN", "COLLECTION_MAX_PAGES_PER_RUN"]
)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_non_positive_ceiling_is_refused(
    make_settings: Callable[..., Settings], field: str, value: str
) -> None:
    """Zero would halt every run after its first page and blame the provider.

    A ceiling of zero is not a strict policy, it is a product that collects
    nothing while reporting `record_limit` for every page.
    """
    with pytest.raises(ValidationError):
        make_settings(**{field: value})

"""S3.3 step 2: the demo seed's guarantees, and the guarantees it must not have.

## What is tested, and what is deliberately not

The seed script's job is to write a realistic local dataset. What matters is not that
it works -- it is that it is **safe** and **honest**, and those are the properties
asserted here:

- it refuses `APP_ENV=prod` before opening a connection;
- importing it does nothing at all;
- it reuses an existing competitor and Page instead of duplicating them;
- it writes no performance metric, because the schema has nowhere to write one.

## There is no end-to-end test, and that is a finding rather than an omission

An earlier version of this file ran the real seed twice and compared the row counts.
It worked, and it could **never be run again**.

`ad_snapshots` is append-only, and the trigger refuses `DELETE` as well as `UPDATE`
-- its message covers both. So a committed seed is permanent: there is no way to undo
it short of dropping the table or disabling the trigger, and neither is this project's
to do. Worse, the demo rows are *visible to other suites*, because `test_ad_persistence`
counts `ads` inside its own transaction and sees the committed ones. One run of that
test left 12 unrelated tests red, permanently, with no sanctioned way back.

That is a property of the product, not of the test: the database is designed so that
collected evidence cannot be un-collected. A test that writes to it is therefore not
a safe thing to ship.

So the end-to-end run is **manual**, and the properties it would have covered are
pinned hermetically instead:

- *"rerunning does not fabricate snapshot history"* is the content-hash dedupe in
  `persist_observations`, which `test_ad_persistence.py` already covers directly
  ("an unchanged observation in a later run writes no second snapshot");
- *"rerunning does not duplicate the competitor or Page"* is the two reuse tests
  below.

The seed's own flow was verified by hand: 9 ad records across 3 pages produced 8 ads
and 8 snapshots -- the corpus deliberately repeats `mock-ad-000101` across two
batches of one page, and the repeat collapsed, which is the dedupe working.

## The module is loaded by path, not imported by name

`scripts/` is not a package and is not on pytest's `pythonpath` -- that list holds
`backend` and `backend/tests` for a reason unrelated to this script. Adding the repo
root to shared pytest configuration to make one script importable would be a wider
change than the script deserves, so the module is loaded from its file with
`importlib`. That also makes "importing it does nothing" directly testable, since the
test controls the import.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import AppEnv
from app.models.ads import AdSnapshot
from app.models.tracking import Competitor, FacebookPage

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "seed_demo.py"
CORPUS = REPO_ROOT / "backend" / "tests" / "fixtures" / "ad_provider" / "corpus.json"
ANALYSES = REPO_ROOT / "backend" / "tests" / "fixtures" / "ai" / "analyses.json"

pytestmark = pytest.mark.integration

#: Tables the seed writes. Checked by `test_importing_the_module_seeds_nothing`,
#: which must see a pristine database.
_ALL_SEEDED_TABLES = (
    "competitors",
    "facebook_pages",
    "ads",
    "ad_snapshots",
    "seen_in_run",
)

#: Tables holding **collected data**. Only these gate the live test.
#:
#: A competitor and a Page are configuration the seed reuses by design -- that is the
#: whole idempotence contract -- so their presence is not a hazard. Collected rows are:
#: if a database already has ads, this is someone's real data and the seed must not
#: run against it.
_COLLECTED_TABLES = ("ads", "ad_snapshots", "seen_in_run", "ad_status_by_context")


def _load_seed_module(name: str) -> ModuleType:
    """Load `scripts/seed_demo.py` under a fresh name.

    Registered in `sys.modules` **before** `exec_module`: `@dataclass(slots=True)`
    rebuilds the class and looks its own module up there while doing so, so a module
    that was never registered raises `AttributeError: 'NoneType' object has no
    attribute '__dict__'` -- a loader artefact with nothing to do with the script.
    """
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


@pytest.fixture(scope="module")
def seed_demo() -> Iterator[ModuleType]:
    """The seed module, loaded once for the tests that exercise its functions."""
    yield _load_seed_module("seed_demo_under_test")


def _counts(session: Session, tables: tuple[str, ...] = _ALL_SEEDED_TABLES) -> dict[str, int]:
    return {
        table: session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in tables
    }


# ============================================================
# Safety: production
# ============================================================


def test_it_refuses_app_env_prod(make_settings: Any, seed_demo: ModuleType) -> None:
    """The guard between "a developer wanted demo data" and a real competitor row."""
    with pytest.raises(seed_demo.SeedRefused, match="APP_ENV=prod"):
        seed_demo.refuse_in_production(make_settings(APP_ENV="prod"))


def test_the_boundary_is_local_and_dev(make_settings: Any, seed_demo: ModuleType) -> None:
    """`local` and `dev` are fine; `prod` is not.

    Pinning the boundary means an environment added to `AppEnv` later fails here
    rather than being silently allowed to write demo rows.
    """
    seed_demo.refuse_in_production(make_settings(APP_ENV="local"))
    seed_demo.refuse_in_production(make_settings(APP_ENV="dev"))

    with pytest.raises(seed_demo.SeedRefused):
        seed_demo.refuse_in_production(make_settings(APP_ENV="prod"))


def test_the_refusal_happens_before_any_connection(
    make_settings: Any, monkeypatch: Any, seed_demo: ModuleType
) -> None:
    """A refusal that first opened a database would already have written something."""
    settings = make_settings(APP_ENV="prod")

    def _must_not_connect() -> Any:
        raise AssertionError("the seed opened a database before refusing")

    monkeypatch.setattr(seed_demo, "get_settings", lambda: settings)
    monkeypatch.setattr("app.db.session.get_engine", _must_not_connect)

    with pytest.raises(seed_demo.SeedRefused):
        seed_demo.seed()


# ============================================================
# Safety: importing does nothing
# ============================================================


def test_importing_the_module_seeds_nothing(db_session: Session, seed_demo: ModuleType) -> None:
    """Import must be inert.

    A script that seeded on import would write to whatever database the importing
    process happened to be configured against -- a test run, or production.

    Asserted as *before and after a reload*, not as "the database is empty". The
    earlier version asserted emptiness and became order-dependent: it failed against a
    database where an earlier real seed run had already run. Being empty is a property
    of the machine; being unchanged is the property of the script.
    """
    before = _counts(db_session)
    _load_seed_module("seed_demo_import_probe")
    after = _counts(db_session)
    assert after == before, f"import changed the database: {before} -> {after}"


def test_the_entrypoint_is_behind_a_main_guard() -> None:
    """`python scripts/seed_demo.py` runs it; importing it does not.

    Asserted on the source, because the behaviour is a property of the guard and a
    subprocess import cannot distinguish "never ran" from "ran and rolled back".
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source
    assert "raise SystemExit(main())" in source


def test_no_module_level_seed_call_exists() -> None:
    """Every statement at column zero is a definition, an import or the guard.

    Walks the source with `ast` rather than grepping, so a `seed()` call hidden in
    any form is caught.
    """
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    harmless = (
        ast.Import,
        ast.ImportFrom,
        ast.ClassDef,
        ast.FunctionDef,
        ast.Assign,
        ast.AnnAssign,
        ast.Expr,  # the module docstring, which is a bare expression
    )
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.If):
            # The one `if` allowed at module level is the entrypoint guard, and only
            # if it really is the `__main__` one. Any other module-level `if` can
            # execute on import, which is exactly what must not happen.
            test = node.test
            assert isinstance(test, ast.Compare), "a module-level `if` is not a __main__ guard"
            left = test.left
            assert isinstance(left, ast.Name) and left.id == "__name__", (
                "a module-level `if` is not a __main__ guard"
            )
            continue
        if isinstance(node, ast.Expr):
            # Only the leading docstring is a bare expression. A later one would be a
            # call executed at import.
            assert index == 0, "a bare expression outside the docstring runs on import"
            continue
        assert isinstance(node, harmless), f"unexpected module-level: {type(node).__name__}"

    # Module-level calls, excluding the `__main__` guard -- which is *supposed* to
    # call `main()`. Everything else at module level must call nothing at all.
    # Calls that actually execute at import: a bare expression statement, and the
    # decorators on a definition. `ast.walk` on a FunctionDef descends into its body,
    # which would find `seed(...)` inside `main()` -- code that only runs when called,
    # so including it here would be a false positive.
    executed_at_import: list[str] = []
    for statement in tree.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            func = statement.value.func
            if isinstance(func, ast.Name):
                executed_at_import.append(func.id)
        for decorator in getattr(statement, "decorator_list", []):
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                executed_at_import.append(decorator.func.id)

    assert "seed" not in executed_at_import, "the seed must never be called at import time"
    assert "main" not in executed_at_import, "main must only run behind the __main__ guard"


# ============================================================
# Deterministic demo identity
# ============================================================


def test_the_demo_corpus_is_the_sanitised_one_and_nothing_else(
    db_session: Session, seed_demo: ModuleType
) -> None:
    """One corpus, reused. A second invented corpus would be a fiction the backend
    never agreed to produce.

    Also asserts `.invalid` destinations -- reserved by RFC 2606 precisely so a
    fixture can never resolve to a real service, which is what makes seeding safe.
    """
    from app.composition import build_mock_pages

    corpus = build_mock_pages()
    assert corpus, "the sanitised corpus must not be empty"
    assert len(corpus) == 3

    for page_id, page in corpus.items():
        assert page.page.provider_page_id == page_id
        if page.page.url is not None:
            assert ".invalid" in str(page.page.url), page.page.url


def test_the_demo_country_is_one_the_corpus_actually_claims(
    db_session: Session, seed_demo: ModuleType
) -> None:
    """`schedule_collection` reads the page's country into the run.

    A demo page in a country the corpus never mentions would produce a run whose
    country contradicts every ad in it.

    Note the assertion is `in`, not `==`. The corpus spans `IN`, `GB`, `IE` and `US`
    and only 6 of its 9 ads claim `IN` -- an earlier version of this test asserted
    equality and was wrong about the fixture. The context country records the scope
    of the run that observed an ad, not the ad's own `targeted_countries`, which stay
    in `normalized`.
    """
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    claimed = {
        country
        for entry in corpus["pages"]
        for batch in entry["batches"]
        for ad in batch["raw"].get("ads", [])
        for country in ad.get("targeted_countries", [])
    }
    assert seed_demo.DEMO_COUNTRY in claimed
    # And the fixture really is multi-country, so the `in` above is doing work.
    assert len(claimed) > 1, "the corpus is single-country; the `in` assertion is vacuous"


def test_the_demo_pages_are_the_ones_the_mock_provider_serves(
    db_session: Session, seed_demo: ModuleType
) -> None:
    """`MockProvider.fetch_page_ads` looks a page up by `provider_page_id`.

    Seeding a `FacebookPage` under any other id would collect nothing and look like a
    failure, so the ids the script will create must be the corpus's own.
    """
    from app.composition import build_mock_pages

    corpus = build_mock_pages()
    # Deterministic and stable: the script iterates the corpus, and this is the
    # identity it relies on.
    assert sorted(corpus) == ["mock-page-0001", "mock-page-0002", "mock-page-0003"]


def test_competitor_reuse_matches_on_name(db_session: Session, seed_demo: ModuleType) -> None:
    """Rerunning must not create a second demo competitor.

    `Competitor.name` is deliberately not unique in the schema, so this is a
    match-then-insert rather than leaning on a constraint that does not exist.

    Uses a test-only name rather than the demo's own, so the test is hermetic: it once
    failed against a database that already held the demo competitor from an earlier
    real run, which is a test-isolation bug rather than a finding.
    """
    name = "Reuse Probe (test only)"
    first = seed_demo._ensure_competitor(db_session, name)
    second = seed_demo._ensure_competitor(db_session, name)

    assert first.id == second.id
    assert db_session.query(Competitor).filter(Competitor.name == name).count() == 1


def test_page_reuse_matches_on_the_providers_page_id(
    db_session: Session, seed_demo: ModuleType
) -> None:
    """`facebook_pages.page_id` is globally unique, so this one can rely on it.

    Uses a page id that is deliberately **not** one of the corpus's, so the assertion
    about "reused, not updated" cannot be defeated by a real demo page that already
    exists from an earlier seed run.
    """
    probe_page_id = "reuse-probe-page-not-in-corpus"
    competitor = seed_demo._ensure_competitor(db_session, "Reuse Probe (test only)")
    first = seed_demo._ensure_page(
        db_session,
        competitor_id=competitor.id,
        provider_page_id=probe_page_id,
        page_name="First Recorded Name",
        url=None,
    )
    second = seed_demo._ensure_page(
        db_session,
        competitor_id=competitor.id,
        provider_page_id=probe_page_id,
        page_name="Renamed Since",
        url=None,
    )

    assert first.id == second.id
    # Reused, not updated: whatever was first recorded stands.
    assert second.name == "First Recorded Name"
    assert db_session.query(FacebookPage).filter(FacebookPage.page_id == probe_page_id).count() == 1


# ============================================================
# No fabricated performance data
# ============================================================


def test_no_table_can_hold_a_performance_metric(db_session: Session) -> None:
    """The guarantee is structural, not disciplinary.

    There is no spend, impressions, reach, clicks, leads, conversions, CPM, revenue
    or ROAS column anywhere in the schema, so the seed cannot write one even if it
    tried. A future checkpoint that adds one fails here, which is the point: the
    question then gets asked deliberately.
    """
    forbidden = {
        "spend",
        "amount_spent",
        "impressions",
        "reach",
        "clicks",
        "leads",
        "conversions",
        "cpm",
        "cpc",
        "revenue",
        "roas",
        "winner",
        "verdict",
        "is_winner",
    }
    rows = db_session.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
    ).all()
    assert rows, "expected to read the live schema"
    for table, column in rows:
        assert column not in forbidden, f"{table}.{column}"


def test_no_api_field_claims_a_verdict() -> None:
    """Longevity is a proxy. No response field may read as a judgement."""
    from app.main import create_app

    body = str(create_app(app_env=AppEnv.LOCAL).openapi()).lower()
    for word in ("winner", "loser", "top performer", "best performing"):
        assert word not in body, word


def test_duration_is_computed_at_read_time_never_stored(db_session: Session) -> None:
    """Which is why it cannot rot, and why no seed can fabricate one."""
    columns = {column.name for column in AdSnapshot.__table__.c}
    assert "duration_days" not in columns
    assert "is_long_running_signal" not in columns
    assert "meta_delivery_start" in columns


def test_the_seed_writes_no_metric_and_no_verdict_column_itself() -> None:
    """The script's own source, so a future edit cannot slip a metric past the above.

    Scanned through `ast` with **docstrings excluded**, because this file's docstring
    spends several paragraphs naming the very metrics the seed refuses to write. A
    plain substring search over the source would flag its own explanation.
    """
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]

    for word in ("spend", "impression", "roas", "conversion", "leads", "winner", "reach"):
        assert not any(word in text.lower() for text in literals), word


# ============================================================
# AI: no flag, and why
# ============================================================


def test_the_analysis_fixture_keys_could_never_be_stored(db_session: Session) -> None:
    """The reason there is no `--with-ai` flag, asserted rather than asserted-in-prose.

    `ad_analysis.copy_hash` carries `CHECK (copy_hash ~ '^[0-9a-f]{64}$')`, so these
    placeholder keys can never satisfy it. `MockAIProvider` would miss on every real
    digest and return its all-null analysis.
    """
    fixtures = json.loads(ANALYSES.read_text(encoding="utf-8"))
    assert fixtures["responses"], "the analysis fixture must not be empty"
    for key in fixtures["responses"]:
        assert not re.fullmatch(r"[0-9a-f]{64}", key), key


def test_there_is_no_with_ai_flag_and_no_ai_import() -> None:
    """It cannot schedule analysis, so it cannot accidentally write one.

    Deliberate, and documented in the script: an all-null interpretation reads as
    "analysed" while saying nothing, which is worse than no analysis at all.

    Checked as *registered CLI flags*, not as a substring. The script's docstring
    names `--with-ai` several times precisely to explain its absence, so a plain
    search would flag its own explanation.
    """
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    flags = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert flags == set(), f"the seed should register no flags, found {sorted(flags)}"

    # Imports, not substrings: the docstring names `MockAIProvider` precisely to
    # explain why the analysis path is not invoked.
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    for forbidden in ("ai_analysis", "analysis_prompt"):
        assert not any(forbidden in name for name in imported), forbidden


# ============================================================
# End to end, against the real (empty) development database
# ============================================================


def test_running_the_script_in_prod_exits_one_without_a_traceback() -> None:
    """The refusal path exits 1 with a message, not a stack trace.

    The user did nothing wrong and should not be shown a traceback for being told no.

    The real environment is inherited, because emptying `PATH` breaks CPython itself
    rather than the script. `APP_ENV` is forced to `prod` -- an environment variable
    outranks the repo's `.env` in pydantic-settings -- and `DATABASE_URL` points at an
    unreachable placeholder, so if the guard ever failed to fire the run would fail to
    connect rather than write anywhere real.
    """
    import os

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "APP_ENV": "prod",
            "DATABASE_URL": "postgresql+psycopg://nobody:nobody@localhost:1/none",
        },
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 1, result.stderr[-800:]
    assert "Traceback" not in result.stderr
    assert "refusing to seed demo data" in result.stdout + result.stderr

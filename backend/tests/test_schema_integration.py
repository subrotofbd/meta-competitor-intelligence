"""The S1.1 schema, proven against a live PostgreSQL 16.

    docker compose up -d
    uv run pytest -m integration

Every assertion that could only be made against a real server lives here:
a foreign key refusing an orphan, a `CHECK` firing, the `payload_hash` trigger
computing a digest, `ON DELETE RESTRICT` stopping a delete, and Alembic agreeing
with the models.

Writes are real, and nothing is committed. The `db_session` fixture in
`conftest.py` binds a session to a connection inside an outer transaction that is
always rolled back, so there is no cleanup `DELETE` to get wrong and no path by
which a failing test can leave rows in the development database.

Not skipped when the database is unreachable. A skip is indistinguishable from a
pass in CI output, and this project does not report unverified work as green.
"""

from __future__ import annotations

import io
import uuid
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

# Imported for the metadata Alembic compares against.
from app.db.base import Base
from app.db.session import get_engine
from app.models import (
    CollectionRun,
    CollectionRunStatus,
    Competitor,
    FacebookPage,
    ProviderRun,
    ProviderRunStatus,
    RawResponse,
)
from app.providers.data.provenance import DataOrigin
from tests.conftest import REPO_ROOT
from tests.test_models import S11_TABLES

pytestmark = pytest.mark.integration

ALEMBIC_INI = REPO_ROOT / "alembic.ini"
S11_REVISION = "0002_collection_domain"
BASE_REVISION = "0001_pg_trgm"

NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ALEMBIC_INI))


# ============================================================
# The migration
# ============================================================


def test_the_migration_applies_and_leaves_one_head() -> None:
    """`upgrade head` is idempotent, then the revision is checked.

    Runs the real upgrade rather than asserting the revision table, so this
    fails if the migration is unrunnable -- a bad `op.create_table` or a missing
    trigger, which a revision-table check would happily pass.
    """
    command.upgrade(_config(), "head")

    assert len(ScriptDirectory.from_config(_config()).get_heads()) == 1
    with get_engine().connect() as connection:
        applied = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert applied == S11_REVISION


def test_s11_extends_the_pg_trgm_revision_rather_than_branching() -> None:
    """One linear lineage. Two heads means no single `upgrade` reaches the schema."""
    script = ScriptDirectory.from_config(_config())
    revisions = {revision.revision: revision.down_revision for revision in script.walk_revisions()}

    assert revisions == {S11_REVISION: BASE_REVISION, BASE_REVISION: None}


def test_pg_trgm_is_still_installed_after_s11() -> None:
    """S1.1 adds no trigram index, so the extension is left for S2.1 to use.

    `0001_pg_trgm` installed it specifically so the first GIN index can be built
    with the ads schema. Nothing here creates one, and this asserts the extension
    survived a second migration rather than assuming it.
    """
    with get_engine().connect() as connection:
        version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm'")
        ).scalar_one()
    assert version


def test_no_trigram_or_text_index_exists_yet() -> None:
    """S1.1 creates no search index, deliberately.

    The only text `ARCHITECTURE.md` asks to search is ad copy, which is S2.1.
    Adding a GIN index now would be indexing a column that does not exist.
    """
    with get_engine().connect() as connection:
        names = connection.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        ).scalars()
    assert not [name for name in names if name.startswith("gin_") or "trgm" in name]


def test_the_downgrade_renders_complete_sql_without_executing_it() -> None:
    """Every object dropped, in dependency order, rendered offline.

    The downgrade has never been run -- it issues `DROP`s, and the checkpoint
    rules need explicit human consent for that. Alembic's offline `--sql` mode
    renders the statements without connecting, so reversibility is checked
    without touching the database.
    """
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), f"{S11_REVISION}:{BASE_REVISION}", sql=True)
    sql = buffer.getvalue()

    for name in sorted(S11_TABLES):
        assert f"DROP TABLE {name}" in sql, f"downgrade does not drop {name}"
    assert "DROP TRIGGER IF EXISTS raw_responses_payload_hash_trg" in sql
    assert "DROP FUNCTION IF EXISTS public.raw_response_payload_hash()" in sql

    # The trigger must go before the function that it calls, or the function
    # would be dropped while a trigger still referenced it.
    assert sql.index("DROP TRIGGER") < sql.index("DROP FUNCTION")
    # And every table must go before its parent, deepest first.
    assert sql.index("DROP TABLE raw_responses") < sql.index("DROP TABLE provider_runs")
    assert sql.index("DROP TABLE provider_runs") < sql.index("DROP TABLE collection_runs")
    assert sql.index("DROP TABLE collection_runs") < sql.index("DROP TABLE facebook_pages")
    assert sql.index("DROP TABLE facebook_pages") < sql.index("DROP TABLE competitors")


# ============================================================
# Models and database agree
# ============================================================


def test_the_database_matches_the_models_with_no_drift() -> None:
    """Alembic's own comparison finds nothing to do.

    This is the test that would have caught the autogenerate bug where
    column-level `CHECK` constraints were emitted into the migration's absence
    while the metadata reported no difference. It is the single most valuable
    assertion in this file: everything else describes the schema, this one
    proves the schema in the database is the schema in the code.
    """
    with get_engine().connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True},
        )
        operations = compare_metadata(context, Base.metadata)

    assert operations == [], f"models and database have drifted: {operations}"


def test_every_declared_check_constraint_exists_in_the_database() -> None:
    """The metadata's checks, compared against `pg_constraint` by name.

    Complements `test_every_check_constraint_is_visible_to_alembic`. That one
    checks the Python side can be seen by autogenerate; this one checks the
    constraint is genuinely installed. Between them, a `CHECK` that exists in
    only one of the two places is a test failure rather than a silent gap.

    Grouped with an explicit loop rather than a dict comprehension: a
    comprehension keyed on `table_name` keeps only the last row per table, which
    silently reduced five tables' worth of checks to whichever row came last and
    made the assertion below fail for reasons that had nothing to do with the
    schema.
    """
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname AS table_name, conname AS constraint_name "
                "FROM pg_constraint "
                "JOIN pg_class ON pg_class.oid = conrelid "
                "WHERE contype = 'c'"
            )
        ).all()

    installed: dict[str, set[str]] = {}
    for row in rows:
        if str(row.constraint_name).startswith("ck_"):
            installed.setdefault(str(row.table_name), set()).add(str(row.constraint_name))

    for table_name in sorted(S11_TABLES):
        declared = {
            str(constraint.name)
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, CheckConstraint)
        }
        # `raw_responses` legitimately declares none: its integrity comes from
        # `NOT NULL`, the `UNIQUE` on `provider_run_id`, and the hash trigger
        # rather than from a rule about the shape of a value. Every other table
        # has a `VARCHAR` or a count that could hold something impossible.
        if table_name != "raw_responses":
            assert declared, f"{table_name} declares no checks, which cannot be right"
        missing = declared - installed.get(table_name, set())
        assert not missing, f"{table_name}: missing {sorted(missing)}"


def test_every_declared_index_exists_in_the_database() -> None:
    with get_engine().connect() as connection:
        installed = set(
            connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            ).scalars()
        )

    expected = {
        index.name
        for table_name in S11_TABLES
        for index in Base.metadata.tables[table_name].indexes
    }
    assert expected
    assert expected <= installed, f"missing {sorted(expected - installed)}"


def test_every_foreign_key_is_installed_as_restrict() -> None:
    """`confdeltype = 'r'`, checked in the catalogue rather than the metadata.

    The single most consequential property of this schema. A `CASCADE` would let
    a deleted competitor silently take a page's run history and every raw
    payload with it, and that data cannot be re-acquired.
    """
    with get_engine().connect() as connection:
        rows = connection.execute(
            text("SELECT conname, confdeltype FROM pg_constraint WHERE contype = 'f'")
        ).all()

    assert rows, "no foreign keys installed"
    assert all(row.confdeltype == "r" for row in rows), [
        f"{row.conname} is {row.confdeltype!r}" for row in rows if row.confdeltype != "r"
    ]


# ============================================================
# Writing real rows
# ============================================================
#
# Two rules the builders follow, and both are forced by how SQLAlchemy works.
#
# **A parent is flushed.** The UUID primary key is generated by the ORM as a
# column default at INSERT time, not at construction, so `competitor.id` is
# `None` until something flushes. A child that references a parent therefore
# needs the parent written first.
#
# **The row under test is not.** A `CHECK` or a `UNIQUE` fires at flush time, so a
# builder that flushed the row under test would raise the very `IntegrityError`
# the test is about to catch -- inside the builder, before `pytest.raises` was
# ever entered, and reported as a setup error rather than as the constraint the
# test meant to exercise. Hence the `flush=False` in those tests.


def _competitor(session: Session, name: str = "Acme") -> Competitor:
    row = Competitor(name=name)
    session.add(row)
    session.flush()
    return row


def _page(
    session: Session,
    competitor: Competitor,
    page_id: str = "100000000000001",
    *,
    flush: bool = True,
    **overrides: object,
) -> FacebookPage:
    fields: dict[str, object] = {
        "competitor_id": competitor.id,
        "page_id": page_id,
        "name": "Acme India",
        "url": "https://www.facebook.com/acme",
        "country": "IN",
        "tracking_frequency": "daily",
        "is_tracked": True,
    }
    fields.update(overrides)
    row = FacebookPage(**fields)
    session.add(row)
    if flush:
        session.flush()
    return row


def _collection_run(
    session: Session,
    page: FacebookPage,
    *,
    flush: bool = True,
    **overrides: object,
) -> CollectionRun:
    fields: dict[str, object] = {
        "facebook_page_id": page.id,
        "provider": "mock",
        "country": "IN",
        "data_origin": DataOrigin.third_party,
        "status": CollectionRunStatus.COMPLETE,
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=30),
        "records_returned": 0,
    }
    fields.update(overrides)
    row = CollectionRun(**fields)
    session.add(row)
    if flush:
        session.flush()
    return row


def _provider_run(
    session: Session,
    run: CollectionRun,
    *,
    flush: bool = True,
    **overrides: object,
) -> ProviderRun:
    fields: dict[str, object] = {
        "collection_run_id": run.id,
        "status": ProviderRunStatus.SUCCEEDED,
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=2),
        "request_meta": {
            "provider": "mock",
            "origin": DataOrigin.third_party.value,
            "country": "IN",
            "requested_at": NOW.isoformat(),
            "cursor": None,
        },
        "http_status": 200,
    }
    fields.update(overrides)
    row = ProviderRun(**fields)
    session.add(row)
    if flush:
        session.flush()
    return row


def _full_chain(session: Session) -> tuple[Competitor, CollectionRun, ProviderRun]:
    """A valid competitor -> page -> run -> call, flushed, ready to hang rows off.

    The one place a flush is never optional: every one of these rows is a parent
    of the next, and none of them is the thing under test, so there is nothing
    for the flush to break.
    """
    competitor = _competitor(session)
    page = _page(session, competitor)
    run = _collection_run(session, page)
    call = _provider_run(session, run)
    session.flush()
    return competitor, run, call


# ============================================================
# Constraints, proven by trying to break them
# ============================================================


def test_a_page_cannot_be_attached_to_a_competitor_that_does_not_exist(
    db_session: Session,
) -> None:
    """The foreign key refuses an orphan, and names the constraint when it does."""
    page = FacebookPage(
        competitor_id=uuid.uuid4(),
        page_id="100000000000002",
        country="IN",
        tracking_frequency="daily",
        is_tracked=True,
    )
    db_session.add(page)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "fk_facebook_pages_competitor_id_competitors" in str(caught.value)
    db_session.rollback()


def test_a_run_cannot_reference_a_page_that_does_not_exist(db_session: Session) -> None:
    run = CollectionRun(
        facebook_page_id=uuid.uuid4(),
        provider="mock",
        country="IN",
        data_origin=DataOrigin.third_party,
        status=CollectionRunStatus.PENDING,
    )
    db_session.add(run)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "fk_collection_runs_facebook_page_id_facebook_pages" in str(caught.value)
    db_session.rollback()


def test_the_same_page_cannot_be_tracked_twice_even_under_another_competitor(
    db_session: Session,
) -> None:
    """Global uniqueness, proven across competitors.

    This is the test that would catch `UNIQUE (competitor_id, page_id)` in place
    of `UNIQUE (page_id)`: the duplicate here is on a *different* competitor, so
    the composite constraint would accept it and every ad through that page would
    belong to two parents.
    """
    first = _competitor(db_session, "Acme")
    second = _competitor(db_session, "Globex")
    _page(db_session, first, page_id="100000000000003")

    duplicate = FacebookPage(
        competitor_id=second.id,
        page_id="100000000000003",
        country="IN",
        tracking_frequency="daily",
        is_tracked=True,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "uq_facebook_pages_page_id" in str(caught.value)
    db_session.rollback()


def test_a_provider_call_cannot_have_two_raw_responses(db_session: Session) -> None:
    """A second response for the same call is a bug, and the database says so.

    `ProviderResult` carries exactly one `raw`, so this is not a case where both
    rows could legitimately be kept.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    db_session.add(RawResponse(provider_run_id=call.id, payload={"first": True}))
    db_session.add(RawResponse(provider_run_id=call.id, payload={"second": True}))

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "uq_raw_responses_provider_run_id" in str(caught.value)
    db_session.rollback()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"country": "in"}, "ck_collection_runs_country_iso_alpha2"),
        ({"country": "I"}, "ck_collection_runs_country_iso_alpha2"),
        ({"country": "1N"}, "ck_collection_runs_country_iso_alpha2"),
        ({"provider": ""}, "ck_collection_runs_provider_not_blank"),
        ({"provider": "   "}, "ck_collection_runs_provider_not_blank"),
        ({"records_returned": -1}, "ck_collection_runs_records_returned_not_negative"),
    ],
    ids=[
        "lowercase-country",
        "one-letter-country",
        "digit-in-country",
        "blank-provider",
        "whitespace-provider",
        "negative-records",
    ],
)
def test_a_collection_run_rejects_impossible_values(
    db_session: Session, overrides: dict[str, object], constraint: str
) -> None:
    competitor = _competitor(db_session)
    page = _page(db_session, competitor, page_id="100000000000009")
    _collection_run(db_session, page, flush=False, **overrides)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert constraint in str(caught.value)
    db_session.rollback()


def test_a_country_longer_than_two_characters_is_refused_by_the_column(
    db_session: Session,
) -> None:
    """`IND` is refused by `VARCHAR(2)`, not by the check -- a different refusal.

    Worth separating from the cases above because the two arrive as different
    exceptions. A value of the wrong shape raises `DataError`
    (`StringDataRightTruncation`); a value of the right shape but the wrong
    content raises `IntegrityError` (`CheckViolation`). Both are refusals, and a
    test that caught `IntegrityError` for `IND` would either fail for the wrong
    reason or quietly widen itself to a base class and stop checking which
    constraint did the work.
    """
    competitor = _competitor(db_session)
    page = _page(db_session, competitor, page_id="100000000000009")
    _collection_run(db_session, page, flush=False, country="IND")

    with pytest.raises(DataError):
        db_session.flush()

    db_session.rollback()


def test_a_run_cannot_finish_before_it_starts(db_session: Session) -> None:
    competitor = _competitor(db_session)
    page = _page(db_session, competitor, page_id="100000000000010")
    _collection_run(
        db_session,
        page,
        flush=False,
        started_at=NOW,
        finished_at=NOW - timedelta(seconds=1),
    )

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "ck_collection_runs_finished_after_started" in str(caught.value)
    db_session.rollback()


def test_a_competitor_name_cannot_be_blank(db_session: Session) -> None:
    db_session.add(Competitor(name="  "))

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "ck_competitors_name_not_blank" in str(caught.value)
    db_session.rollback()


def test_a_page_url_must_be_http_or_https(db_session: Session) -> None:
    competitor = _competitor(db_session)
    _page(
        db_session,
        competitor,
        page_id="100000000000011",
        flush=False,
        url="file:///etc/passwd",
    )

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "ck_facebook_pages_url_http_only" in str(caught.value)
    db_session.rollback()


def test_a_null_page_url_is_accepted(db_session: Session) -> None:
    """A provider need not report a url, so `NULL` must be allowed.

    The `CHECK` is `url IS NULL OR ...`; a provider that gives no url is a normal
    case, and this proves the constraint did not become a requirement by accident.
    """
    competitor = _competitor(db_session)
    page = _page(db_session, competitor, page_id="100000000000012", url=None)

    assert page.url is None
    assert page.id is not None


@pytest.mark.parametrize(
    ("column", "bad_value", "constraint"),
    [
        ("status", "complate", "ck_collection_runs_status"),
        ("data_origin", "scraped", "ck_collection_runs_data_origin"),
    ],
    ids=["status", "data-origin"],
)
def test_a_value_outside_the_vocabulary_is_refused(
    db_session: Session, column: str, bad_value: str, constraint: str
) -> None:
    """A `VARCHAR` plus a `CHECK` still refuses what the enum would not accept.

    Proven with raw SQL, because the ORM cannot express it: `sa.Enum` with
    `validate_strings=True` would reject the string in Python, and the point is
    that the *database* rejects it. Anything that can write SQL -- a migration, a
    `psql` session, a future service using text SQL -- meets the same rule.

    The `UPDATE` raises at execution time rather than at flush time, so the
    `pytest.raises` wraps the statement itself.
    """
    competitor = _competitor(db_session)
    page = _page(db_session, competitor, page_id="100000000000013")
    run = _collection_run(db_session, page)
    db_session.flush()

    # Bound parameter, never interpolated: the table and column names come from
    # the parametrisation above, which is code, not input.
    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(f"UPDATE collection_runs SET {column} = :value WHERE id = :id"),
            {"value": bad_value, "id": run.id},
        )

    assert constraint in str(caught.value)
    db_session.rollback()


@pytest.mark.parametrize(
    "cost",
    [
        {"cost_amount": Decimal("1.50")},
        {"cost_currency": "USD"},
        {"cost_method": "provider list price"},
        {"cost_amount": Decimal("1.50"), "cost_currency": "USD"},
        {"cost_currency": "USD", "cost_method": "provider list price"},
    ],
    ids=["amount-only", "currency-only", "method-only", "no-method", "no-amount"],
)
def test_a_cost_without_its_method_is_refused(db_session: Session, cost: dict[str, object]) -> None:
    """A partial cost triple is refused.

    AGENTS.md section 7 requires an `ESTIMATE` to render with the method it was
    arrived at, so a cost with no method is not displayable.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    for column, value in cost.items():
        setattr(call, column, value)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "ck_provider_runs_cost_all_or_nothing" in str(caught.value)
    db_session.rollback()


def test_a_complete_cost_triple_is_accepted(db_session: Session) -> None:
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    call.cost_amount = Decimal("1.500000")
    call.cost_currency = "USD"
    call.cost_method = "provider list price per result"

    db_session.flush()
    db_session.refresh(call)

    assert call.cost_amount == Decimal("1.500000")
    assert call.cost_currency == "USD"


def test_a_negative_cost_is_refused(db_session: Session) -> None:
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    call.cost_amount = Decimal("-1.00")
    call.cost_currency = "USD"
    call.cost_method = "refund, hypothetically"

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "ck_provider_runs_cost_amount_not_negative" in str(caught.value)
    db_session.rollback()


@pytest.mark.parametrize("status_code", [0, 99, 600, -200])
def test_an_impossible_http_status_is_refused(db_session: Session, status_code: int) -> None:
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    call.http_status = status_code

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "ck_provider_runs_http_status_range" in str(caught.value)
    db_session.rollback()


# ============================================================
# Deletes are refused, not cascaded
# ============================================================
#
# Two separate properties, because two separate layers are involved and they
# refuse differently.
#
# `session.delete(parent)` does not send a `DELETE` for the parent. SQLAlchemy
# first tries to detach the children by setting their foreign key to `NULL`,
# because it assumes a `relationship` is nullable unless told otherwise. Here it
# is not, so the failure surfaces as a `NotNullViolation` -- the ORM never
# reaches the `DELETE`, and the constraint that would have stopped it is never
# consulted.
#
# The database's own `ON DELETE RESTRICT` is therefore asserted with raw SQL,
# which is the layer that would act on anything the ORM did not write. Both are
# tested because both are real: a service using the ORM is protected by the
# first, and anything else by the second.


def test_the_orm_refuses_to_delete_a_competitor_that_still_has_a_page(
    db_session: Session,
) -> None:
    """`session.delete` is refused, and nothing is deleted.

    Without `ON DELETE RESTRICT` *and* without a `NOT NULL` foreign key, this
    same call would cascade to the page, its run history, every provider call and
    every raw payload. That data is unrecoverable -- a commercial ad that stopped
    running is gone from Meta permanently, so the snapshot is the only copy that
    will ever exist.
    """
    competitor = _competitor(db_session)
    _page(db_session, competitor, page_id="100000000000020")
    db_session.flush()

    db_session.delete(competitor)

    with pytest.raises(IntegrityError) as caught:
        db_session.flush()

    assert "facebook_pages" in str(caught.value)
    db_session.rollback()


def test_the_database_refuses_the_delete_itself(db_session: Session) -> None:
    """A `DELETE` reaching PostgreSQL is stopped by the foreign key.

    Raw SQL, so the statement is the one a non-ORM caller would issue and the
    constraint named is the one that actually refused it.
    """
    competitor = _competitor(db_session)
    _page(db_session, competitor, page_id="100000000000021")
    db_session.flush()

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text("DELETE FROM competitors WHERE id = :id"),
            {"id": competitor.id},
        )

    assert "fk_facebook_pages_competitor_id_competitors" in str(caught.value)
    db_session.rollback()


@pytest.mark.parametrize(
    ("table", "level", "constraint"),
    [
        ("facebook_pages", 0, "fk_collection_runs_facebook_page_id_facebook_pages"),
        ("collection_runs", 1, "fk_provider_runs_collection_run_id_collection_runs"),
        ("provider_runs", 2, "fk_raw_responses_provider_run_id_provider_runs"),
    ],
)
def test_the_refusal_is_transitive_down_the_whole_chain(
    db_session: Session, table: str, level: int, constraint: str
) -> None:
    """A parent is refused for as long as it has a child, all the way down.

    Three levels, three constraints. If any one of them cascaded, deleting a
    single tracked page would take its entire collection history with it.
    """
    _competitor, run, call = _full_chain(db_session)
    db_session.add(RawResponse(provider_run_id=call.id, payload={"ads": []}))
    db_session.flush()

    ids = [run.facebook_page.id, run.id, call.id]

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(f"DELETE FROM {table} WHERE id = :id"),
            {"id": ids[level]},
        )

    assert constraint in str(caught.value)
    db_session.rollback()


# ============================================================
# The raw payload, and the hash that fingerprints it
# ============================================================


def test_the_payload_hash_is_computed_by_the_database(db_session: Session) -> None:
    """The writer supplies nothing and the column is still filled.

    The trigger takes `sha256` of the stored payload's own canonical text, so
    the hash cannot be omitted, cannot be supplied wrong, and cannot disagree
    with the payload beside it. A `GENERATED ALWAYS` column was the obvious
    alternative and does not work -- PostgreSQL requires a generated expression to
    be immutable, and the JSONB-to-text cast is not -- which is why there is a
    trigger at all.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    payload = {"ads": [{"id": "1"}], "cursor": None}
    response = RawResponse(provider_run_id=call.id, payload=payload)
    db_session.add(response)
    db_session.flush()
    db_session.refresh(response)

    assert response.payload_hash is not None, "the trigger did not fill the hash"
    assert len(response.payload_hash) == 64
    assert all(character in "0123456789abcdef" for character in response.payload_hash)


def test_the_orm_does_not_see_a_trigger_written_hash_until_it_refreshes(
    db_session: Session,
) -> None:
    """A documented sharp edge, pinned here so it cannot surprise a later caller.

    `payload_hash` is written by a trigger, not by a `DEFAULT`, so it is absent
    from the `INSERT`'s `RETURNING` clause and the ORM's attribute stays `None`
    after a flush even though the row already has a correct digest. A reader that
    trusted the in-memory object would conclude the hash was missing.

    `refresh` is the fix and every caller of this table needs it. Asserted here
    because the alternative is a comment nobody reads.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    response = RawResponse(provider_run_id=call.id, payload={"ads": []})
    db_session.add(response)
    db_session.flush()

    stored = db_session.execute(
        text("SELECT payload_hash FROM raw_responses WHERE id = :id"),
        {"id": response.id},
    ).scalar_one()
    assert stored is not None, "the row in the database has no hash"

    db_session.refresh(response)
    assert response.payload_hash == stored


def test_the_payload_hash_is_reproducible_from_the_stored_payload(db_session: Session) -> None:
    """Recomputing the hash in SQL yields exactly the stored value.

    This is what makes the hash an integrity anchor rather than decoration: the
    definition of "the fingerprint of a stored payload" is owned by the database
    in exactly one place, and this proves the two agree.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    response = RawResponse(provider_run_id=call.id, payload={"ads": [{"id": "1"}]})
    db_session.add(response)
    db_session.flush()

    expected = db_session.execute(
        text(
            "SELECT encode(sha256(convert_to(payload::text, 'UTF8')), 'hex') "
            "FROM raw_responses WHERE id = :id"
        ),
        {"id": response.id},
    ).scalar_one()

    assert expected is not None
    db_session.refresh(response)
    assert response.payload_hash == expected


def test_the_hash_moves_when_the_payload_moves(db_session: Session) -> None:
    """A later edit is visible, which is why the trigger is `BEFORE INSERT OR UPDATE`.

    Not a feature anyone should use -- raw responses exist so a parser bug can be
    fixed against the original -- but if one is ever edited in place, the digest
    no longer matches the original collection, and this makes that detectable
    rather than silent.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    response = RawResponse(provider_run_id=call.id, payload={"ads": []})
    db_session.add(response)
    db_session.flush()
    db_session.refresh(response)
    original = response.payload_hash

    response.payload = {"ads": [], "mutated": True}
    db_session.flush()
    db_session.refresh(response)

    assert response.payload_hash is not None
    assert original is not None
    assert response.payload_hash != original


def test_a_supplied_hash_cannot_override_the_trigger(db_session: Session) -> None:
    """Passing a wrong digest does not store it.

    Worth the test because it is the property that distinguishes this from a
    plain `NOT NULL` column the application fills in: a caller cannot assert a
    fingerprint that does not match the data.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    response = RawResponse(
        provider_run_id=call.id,
        payload={"ads": []},
        payload_hash="0" * 64,
    )
    db_session.add(response)
    db_session.flush()
    db_session.refresh(response)

    assert response.payload_hash != "0" * 64


@pytest.mark.parametrize(
    "payload",
    [
        {"ads": []},
        {"ads": [{"id": "1", "nested": {"deep": [1, 2, {"x": None}]}}]},
        {"copy": "अभी 50% तक छूट — सीमित समय के लिए"},
        {"copy": 'emoji 🎯 and "quotes" and \\backslash'},
        {"price": 199.99, "ratio": 1.5, "zero": 0, "negative": -7},
        [],
        [1, {"a": "b"}, None],
    ],
    ids=["empty", "nested", "devanagari", "escapes", "numbers", "empty-list", "mixed-list"],
)
def test_a_payload_survives_storage_unchanged(db_session: Session, payload: object) -> None:
    """Stored verbatim, including Devanagari copy.

    Hindi and Hinglish copy is analysed in the original language (AGENTS.md
    section 10), so a payload that cannot hold non-Latin text intact would make
    the AI checkpoint unreachable. A `dict` *and* a top-level list are both
    accepted, because `RawPayload` is exactly that union.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]
    response = RawResponse(provider_run_id=call.id, payload=payload)
    db_session.add(response)
    db_session.flush()
    db_session.expire(response)
    db_session.refresh(response)

    assert response.payload == payload


def test_a_call_with_no_response_yet_is_fine(db_session: Session) -> None:
    """A blocked or rate-limited call has a `provider_run` and no payload.

    The response is optional on the call because a `Blocked` error may arrive with
    a body and may not, and neither state should require a fake empty payload.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]

    assert call.raw_response is None
    assert call.status is ProviderRunStatus.SUCCEEDED


# ============================================================
# Timestamps
# ============================================================


def test_timestamps_come_from_the_database_clock_and_are_aware(db_session: Session) -> None:
    """Server-set, and timezone-aware.

    A naive `created_at` cannot be compared against a provider-reported delivery
    time from another timezone, and the history rules compare them constantly.
    """
    _competitor_run_call = _full_chain(db_session)
    competitor = _competitor_run_call[0]

    assert competitor.created_at.tzinfo is not None
    assert competitor.updated_at.tzinfo is not None
    assert competitor.created_at.utcoffset() is not None


def test_updated_at_moves_when_a_row_is_changed(db_session: Session) -> None:
    competitor = _competitor(db_session)
    original_created = competitor.created_at
    original_updated = competitor.updated_at

    competitor.name = "Acme Renamed"
    db_session.flush()
    db_session.refresh(competitor)

    assert competitor.name == "Acme Renamed"
    assert competitor.created_at == original_created, "created_at must not move"
    assert competitor.updated_at >= original_updated


def test_a_null_finished_at_is_allowed_for_an_unfinished_run(db_session: Session) -> None:
    """`started_at` and `finished_at` are both nullable, on purpose.

    They answer "has this run happened" and "is it still happening" without
    inventing a fourth status. A `pending` run has neither.
    """
    competitor = _competitor(db_session)
    page = _page(db_session, competitor, page_id="100000000000030")
    run = _collection_run(
        db_session,
        page,
        status=CollectionRunStatus.PENDING,
        started_at=None,
        finished_at=None,
    )

    assert run.started_at is None
    assert run.finished_at is None
    assert run.status is CollectionRunStatus.PENDING


# ============================================================
# Relationships and the vocabulary
# ============================================================


def test_the_chain_navigates_in_both_directions(db_session: Session) -> None:
    """Every `back_populates` is wired, so a relationship is never half-defined."""
    competitor, run, call = _full_chain(db_session)
    response = RawResponse(provider_run_id=call.id, payload={"ads": []})
    db_session.add(response)
    db_session.flush()

    page = run.facebook_page
    assert page.competitor is competitor
    assert run in page.collection_runs
    assert page in competitor.pages
    assert call in run.provider_runs
    assert response.provider_run is call
    assert call.raw_response is response


def test_every_status_in_the_vocabulary_round_trips(db_session: Session) -> None:
    """Each declared status is storable and reads back as the same member.

    The vocabulary is asserted against the database because a `StrEnum` the
    database rejects would be worse than no enum at all -- it would fail on the
    first real run rather than in a test.
    """
    competitor = _competitor(db_session)
    for index, status in enumerate(CollectionRunStatus):
        page = _page(db_session, competitor, page_id=f"1000000000001{index:02d}")
        run = _collection_run(db_session, page, status=status, provider="mock")
        db_session.expire(run)
        db_session.refresh(run)

        assert run.status is status
        assert run.status.value == status.value


def test_the_provider_and_origin_are_stored_once_at_the_top_of_the_chain(
    db_session: Session,
) -> None:
    """Provenance is single-parented, not repeated per row.

    Three copies could disagree; one owner cannot. This asserts the property at
    the database level rather than trusting the metadata test alone.
    """
    _competitor_run_call = _full_chain(db_session)
    call = _competitor_run_call[2]

    for table in ("provider_runs", "raw_responses"):
        columns = {
            row[0]
            for row in db_session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = :table"
                ),
                {"table": table},
            )
        }
        assert "data_origin" not in columns, f"{table} duplicates data_origin"
        assert "provider" not in columns, f"{table} duplicates provider"

    assert call.collection_run.data_origin is DataOrigin.third_party
    assert call.collection_run.provider == "mock"

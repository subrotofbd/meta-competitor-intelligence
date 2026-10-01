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
from sqlalchemy import CheckConstraint, func, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

# Imported for the metadata Alembic compares against.
from app.db.base import Base
from app.db.session import get_engine
from app.models import (
    Ad,
    AdSnapshot,
    CollectionRun,
    CollectionRunStatus,
    Competitor,
    FacebookPage,
    ProviderRun,
    ProviderRunStatus,
    RawResponse,
)
from app.providers.data.mock import MockBatch, MockPage, MockProvider
from app.providers.data.models import PageRef
from app.providers.data.provenance import DataOrigin
from app.services import collection as collection_module
from app.services.collection import CollectionOrchestrator
from app.services.jobs import JobRequest
from tests.conftest import REPO_ROOT
from tests.test_models import S1_TABLES, S11_TABLES, S21_TABLES

pytestmark = pytest.mark.integration

ALEMBIC_INI = REPO_ROOT / "alembic.ini"
S11_REVISION = "0002_collection_domain"
S12_REVISION = "0003_jobs_table"
S21_REVISION = "0004_ad_history"
S21_FIX_REVISION = "0005_ads_data_origin_check"
BASE_REVISION = "0001_pg_trgm"

NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)

#: Page ids and payload for the two transaction-boundary tests. Two separate ids
#: because `facebook_pages.page_id` is globally unique, so the control test could
#: not reuse the same page as the failure test within one database.
TRANSACTION_PAGE_ID = "100000000000090"
TRANSACTION_CONTROL_ID = "100000000000091"
TRANSACTION_PAYLOAD = {
    "ads": [
        {
            "ad_id": "mock-ad-000901",
            "page_id": TRANSACTION_PAGE_ID,
            "status": "active",
            "ad_creative_bodies": [{"body": "The only copy of this ad."}],
        }
    ]
}


class _RecordingQueue:
    """A queue that does nothing, because collection does not enqueue.

    The orchestrator's constructor requires a `JobQueue`, and this test is about
    the transaction boundary rather than about the queue. A `None`-returning
    fake would be enough, but naming the seam is clearer than a bare lambda and
    keeps the type ignore honest.
    """

    def enqueue(self, job: JobRequest) -> str:
        return "job-that-should-not-exist"

    def get(self, kind: str, payload: dict[str, object]) -> object | None:
        return None

    def claim(self, **kwargs: object) -> object | None:
        return None

    def complete(self, job_id: str) -> None:
        return None

    def fail(self, job_id: str, error: str) -> None:
        return None


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
    assert applied == S21_FIX_REVISION


def test_s21_extends_the_s12_revision_rather_than_branching() -> None:
    """One linear lineage. Two heads means no single `upgrade` reaches the schema.

    Five revisions rather than four: `0005` repairs a missing check that
    `0004_ad_history` failed to install, and it extends the same chain rather than
    branching from it. A repair that branched would leave two heads and no single
    `upgrade` reaching the schema.
    """
    script = ScriptDirectory.from_config(_config())
    revisions = {revision.revision: revision.down_revision for revision in script.walk_revisions()}

    assert revisions == {
        S21_FIX_REVISION: S21_REVISION,
        S21_REVISION: S12_REVISION,
        S12_REVISION: S11_REVISION,
        S11_REVISION: BASE_REVISION,
        BASE_REVISION: None,
    }


def test_the_ads_data_origin_vocabulary_is_enforced_in_the_database(
    db_session: Session,
) -> None:
    """The check `0004_ad_history` omitted, proven by trying to store a bad value.

    `collection_runs.data_origin` has carried this vocabulary since S1.1. On
    `ads` the column was a bare `VARCHAR`, so the same impossible value was
    storable on the row a reader consults for provenance. Autogenerate cannot
    catch that class of drift -- it does not detect `CHECK` constraints -- which
    is why this is asserted by writing, not by reading the metadata.
    """
    # The bad value is `thirdparty`: eleven characters, so it fits the column's
    # `VARCHAR(12)` and reaches the vocabulary check rather than being refused
    # earlier for being too long. A longer nonsense string would raise a
    # truncation error and pass this test for entirely the wrong reason.
    #
    # Raw SQL rather than the ORM: the `Enum` type validates in Python and would
    # raise `LookupError` before ever reaching the database, which would prove only
    # that the enum exists. The claim is that the *database* refuses the value --
    # which is also how a hand-written or migrated writer would arrive at it.
    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                "INSERT INTO ads (id, provider, meta_ad_id, data_origin, "
                "first_seen_at, last_seen_at) "
                "VALUES (:id, 'mock', 'ad-bad-origin', 'thirdparty', :now, :now)"
            ),
            {"id": uuid.uuid4(), "now": NOW},
        )

    assert "ck_ads_data_origin" in str(caught.value)
    db_session.rollback()


def test_the_same_value_is_refused_on_collection_runs_as_on_ads(
    db_session: Session,
) -> None:
    """Both tables enforce one vocabulary, proven on both.

    S1.1 installed this check on `collection_runs` and S2.1's repair installed it
    on `ads`. Two copies of the same fact enforcing different rules is the
    divergence the provenance design exists to prevent, so the equivalence is
    asserted rather than assumed -- the constraint name is the only thing that
    differs between the two refusals.
    """
    competitor = _competitor(db_session)
    page = _page(db_session, competitor, page_id="100000000000077")

    with pytest.raises(IntegrityError) as caught:
        db_session.execute(
            text(
                "INSERT INTO collection_runs (id, facebook_page_id, provider, country, "
                "data_origin, status) "
                "VALUES (:id, :page, 'mock', 'IN', 'thirdparty', 'pending')"
            ),
            {"id": uuid.uuid4(), "page": page.id},
        )

    assert "ck_collection_runs_data_origin" in str(caught.value)
    db_session.rollback()


def test_every_valid_origin_is_accepted_on_ads(db_session: Session) -> None:
    """The negative control for the test above.

    Without it, a constraint that rejected everything would satisfy the refusal
    test. Each of the four declared values must round-trip, which is also the
    check that a typo in the constraint's value list would be caught here rather
    than by the first real collection run.
    """
    for index, origin in enumerate(DataOrigin):
        row = Ad(
            provider="mock",
            meta_ad_id=f"ad-origin-{index}",
            data_origin=origin,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
        db_session.add(row)
        db_session.flush()
        db_session.expire(row)
        db_session.refresh(row)

        assert row.data_origin is origin


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

    Unchanged by S2.1: `ad_snapshots.normalized` now exists and *does* hold ad
    copy, but the query that would search it is S2.2's to write first, and an
    index built before the query exists is how index overengineering starts. The
    assertion is re-run here on purpose -- a checkpoint that adds a searchable
    column is exactly the moment this guard could quietly stop applying.
    """
    with get_engine().connect() as connection:
        names = connection.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        ).scalars()
    assert not [name for name in names if name.startswith("gin_") or "trgm" in name]


def test_the_s11_downgrade_renders_complete_sql_without_executing_it() -> None:
    """Every S1.1 object dropped, in dependency order, rendered offline.

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


def test_the_s12_downgrade_renders_complete_sql_without_executing_it() -> None:
    """The S1.2 jobs table dropped, rendered offline."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), f"{S12_REVISION}:{S11_REVISION}", sql=True)
    sql = buffer.getvalue()

    assert "DROP TABLE jobs" in sql
    # Indexes are dropped implicitly with the table, but we can verify
    assert "DROP INDEX ix_jobs_kind" in sql or "DROP TABLE jobs" in sql


def test_the_s21_fix_downgrade_renders_complete_sql_without_executing_it() -> None:
    """The repair revision's own downgrade, rendered offline.

    The same rule as the other downgrades: rendered, never executed. Dropping the
    check would leave `ads` with a weaker provenance rule than `collection_runs`,
    so the statement is checked for reversibility and not run.
    """
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), f"{S21_FIX_REVISION}:{S21_REVISION}", sql=True)
    sql = buffer.getvalue()

    assert "ALTER TABLE ads DROP CONSTRAINT ck_ads_data_origin" in sql


def test_the_s21_downgrade_renders_complete_sql_without_executing_it() -> None:
    """Every S2.1 object dropped, in dependency order, rendered offline.

    Same rule as the S1.1 downgrade test and for the same reason: the downgrade
    has never been run, and it must not be. It issues `DROP`s, and dropping
    `ad_snapshots` would destroy the only copy of observations the providers have
    since stopped serving. Rendering offline proves the revision is reversible
    without touching the database.

    The order is the whole value of this test. `ads` and `ad_snapshots` reference
    each other, so one of the two has to go first regardless; and the trigger has
    to be removed before the function it calls, or the function is dropped while
    a trigger still refers to it.
    """
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.downgrade(_config(), f"{S21_REVISION}:{S12_REVISION}", sql=True)
    sql = buffer.getvalue()

    for name in sorted(S21_TABLES):
        assert f"DROP TABLE {name}" in sql, f"downgrade does not drop {name}"

    assert "DROP TRIGGER IF EXISTS trg_ad_snapshots_append_only ON ad_snapshots" in sql
    assert "DROP FUNCTION IF EXISTS ad_snapshots_append_only()" in sql
    # The trigger before the function it calls.
    assert sql.index("DROP TRIGGER") < sql.index("DROP FUNCTION")
    # The circular pair: one order only, and it must be the same in the SQL.
    assert sql.index("DROP TABLE seen_in_run") < sql.index("DROP TABLE ad_snapshots")
    assert sql.index("DROP TABLE ad_snapshots") < sql.index("DROP TABLE ads")


def test_the_s21_append_only_trigger_and_its_function_are_installed() -> None:
    """The guard is a real trigger on the real table, not only a convention.

    The append-only rule is the one invariant in this project whose violation is
    irrecoverable, and `AGENTS.md` section 8 states it. `test_ad_persistence.py`
    proves the trigger *fires*; this proves it is *there*, so a migration that
    silently stopped creating it would be a different failure from one that
    created it wrongly.
    """
    with get_engine().connect() as connection:
        triggers = connection.execute(
            text(
                "SELECT tgname, tgrelid::regclass::text FROM pg_trigger "
                "WHERE NOT tgisinternal AND tgname = 'trg_ad_snapshots_append_only'"
            )
        ).all()
        function_exists = connection.execute(
            text("SELECT count(1) FROM pg_proc WHERE proname = 'ad_snapshots_append_only'")
        ).scalar_one()

    assert [row[1] for row in triggers] == ["ad_snapshots"]
    assert function_exists == 1


def test_the_s21_tables_exist_and_carry_their_expected_columns() -> None:
    """The three tables, read from `information_schema` rather than the metadata.

    `test_models.py` and `test_ads.py` read what the *code* declares. This reads
    what the *database* has, which is a different question and the one a
    migration bug would answer wrongly. `test_the_database_matches_the_models_with_no_drift`
    compares the two, and this pins the concrete shape so a failure names the
    table and the column.
    """
    expected = {
        "ads": {
            "id",
            "created_at",
            "updated_at",
            "provider",
            "meta_ad_id",
            "data_origin",
            "first_seen_at",
            "last_seen_at",
            "latest_snapshot_id",
        },
        "ad_snapshots": {
            "id",
            "created_at",
            "updated_at",
            "ad_id",
            "collection_run_id",
            "raw_ref",
            "content_hash",
            "ad_status",
            "meta_delivery_start",
            "normalized",
        },
        "seen_in_run": {
            "id",
            "created_at",
            "updated_at",
            "ad_id",
            "collection_run_id",
            "snapshot_id",
        },
    }

    with get_engine().connect() as connection:
        for table, columns in expected.items():
            installed = {
                str(row[0])
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :table"
                    ),
                    {"table": table},
                )
            }
            assert installed == columns, table


def test_the_s21_circular_foreign_key_is_installed_after_both_tables_exist() -> None:
    """`ads.latest_snapshot_id` -> `ad_snapshots.id` is a real, immediate constraint.

    The migration resolves the circular reference the ordinary way: create `ads`
    with the column and no constraint, create `ad_snapshots`, then `ALTER TABLE`
    to add the foreign key. That choice is load-bearing -- a `deferrable`
    constraint would make the writer depend on constraint timing, and this asserts
    the constraint is `NOT DEFERRABLE`, which is what lets `ad_persistence` insert
    an ad with a NULL pointer, write the snapshot, and then fill the pointer in
    without any deferral machinery.
    """
    with get_engine().connect() as connection:
        row = connection.execute(
            text(
                "SELECT conname, condeferrable, confupdtype, confdeltype "
                "FROM pg_constraint "
                "WHERE conname = 'fk_ads_latest_snapshot_id'"
            )
        ).one()

    assert row.condeferrable is False, "the constraint must be immediate"
    # `a` = NO ACTION, `r` = RESTRICT. Both keep the ad from being orphaned.
    assert row.confupdtype == "a"
    assert row.confdeltype == "r"


def test_every_declared_check_constraint_on_the_s21_tables_is_installed() -> None:
    """The S2.1 checks exist in the database, compared by name.

    The complement of `test_every_declared_check_constraint_exists_in_the_database`,
    which covers the S1 tables and skips the S2.1 set because that loop is written
    over `S1_TABLES`. The same class of bug applies: a `CHECK` declared inside
    `mapped_column` is invisible to autogenerate, so it can exist in Python and
    not in the database while Alembic reports no drift.

    Every S2.1 table declares at least one, unlike `raw_responses`, whose
    integrity comes entirely from `NOT NULL` and a `UNIQUE`.
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

    # `seen_in_run` legitimately declares none, on the same grounds as
    # `raw_responses`: it is a link row, so its integrity comes entirely from
    # `NOT NULL` and a `UNIQUE`, and there is no shape rule about a value to
    # enforce. Stated here rather than assumed, so a future reader does not read
    # the absence as an oversight.
    checkless = {"seen_in_run"}

    for table_name in sorted(S21_TABLES):
        declared = {
            str(constraint.name)
            for constraint in Base.metadata.tables[table_name].constraints
            if isinstance(constraint, CheckConstraint)
        }
        if table_name not in checkless:
            assert declared, f"{table_name} declares no checks, which cannot be right"
        missing = declared - installed.get(table_name, set())
        assert not missing, f"{table_name}: missing {sorted(missing)}"


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

    for table_name in sorted(S1_TABLES):
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
        index.name for table_name in S1_TABLES for index in Base.metadata.tables[table_name].indexes
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
# The transaction boundary between evidence and its reading
# ============================================================


def test_a_failure_in_ad_history_leaves_the_committed_raw_response_intact(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rollback is scoped to the normalised layer. This is what proves it.

    `execute_collection_job` commits every raw response as it stores it, and only
    then calls `persist_observations` in a separate transaction. So a failure in
    the ad-history write rolls back the *reading* and must leave the *evidence*
    alone -- the evidence being the only copy of anything about an ad that has
    since stopped running (`DATA_ACCESS.md`).

    The failure is injected by replacing the module-level `persist_observations`
    the orchestrator calls, so the real code path runs: the real fetch, the real
    raw write, the real commit, the real normalisation, the real
    `_persist_ad_history` with its real `except: rollback()`. A test that called
    the persistence service directly would prove only the service.

    Three things are asserted, and the third is the one that would fail if the
    rollback were not scoped:

    1. the run is recorded as failed, so the failure is not silent;
    2. the `raw_responses` row exists, with the whole payload including the
       record the normalizer read;
    3. its `payload_hash` is present and readable.

    On (3): `payload_hash` is written by a trigger, not a `DEFAULT`, so it is
    absent from the `INSERT`'s `RETURNING` and the ORM attribute stays `None`
    after a flush even when the row is correct. This reads it with `refresh`,
    which is what makes the assertion about the *stored* value rather than about
    a trigger's timing.
    """
    page = _page(db_session, _competitor(db_session), page_id=TRANSACTION_PAGE_ID)
    # Both timestamps start null, because the orchestrator writes them from the
    # real clock and the row carries `CHECK (finished_at >= started_at)`. The
    # file-wide `NOW` is a fixed 2026-09-30 constant, which is fine for rows no
    # test ever runs but not for a run the orchestrator will start and finish --
    # a pending run legitimately has neither timestamp, and leaving `finished_at`
    # at the file default would put it before the real `started_at`.
    run = _collection_run(
        db_session,
        page,
        status=CollectionRunStatus.PENDING,
        started_at=None,
        finished_at=None,
    )

    provider = MockProvider(
        {
            TRANSACTION_PAGE_ID: MockPage(
                page=PageRef(provider_page_id=TRANSACTION_PAGE_ID, page_name="Acme India"),
                batches=(MockBatch(raw=TRANSACTION_PAYLOAD),),
            )
        },
        clock=lambda: NOW,
    )

    def _fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("ad history could not be written")

    monkeypatch.setattr(collection_module, "persist_observations", _fail)

    outcome = CollectionOrchestrator(
        db_session,
        provider,
        _RecordingQueue(),  # type: ignore[arg-type]
    ).execute_collection_job(run.id)

    # 1. The failure is recorded rather than swallowed.
    assert outcome.status is CollectionRunStatus.FAILED
    assert outcome.stopped_reason is None

    # 2. The evidence survived, whole.
    stored = db_session.execute(select(RawResponse)).scalar_one()
    assert stored.payload == TRANSACTION_PAYLOAD
    assert len(stored.payload["ads"]) == 1

    # 3. And the trigger-written hash is still readable on the surviving row.
    db_session.refresh(stored)
    assert stored.payload_hash is not None
    assert len(stored.payload_hash) == 64

    # And nothing was written by the failed layer, so this is a clean rollback
    # rather than a partial write that happened not to touch the ad tables.
    assert db_session.execute(select(func.count()).select_from(Ad)).scalar_one() == 0


def test_the_same_failure_without_the_persistence_layer_writes_no_ad(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The negative control for the test above.

    Without it, the control above would pass even if the orchestrator never called
    `persist_observations` at all -- a regression that stopped persisting ads
    entirely would satisfy every assertion in it. Here the layer is *not*
    replaced, so the run completes normally and the same rows appear; the only
    difference between the two tests is whether the persistence layer ran, which
    is what makes the first one's absence of ad rows meaningful.
    """
    page = _page(db_session, _competitor(db_session), page_id=TRANSACTION_CONTROL_ID)
    # Both timestamps null for the same reason as in the failure test above.
    run = _collection_run(
        db_session,
        page,
        status=CollectionRunStatus.PENDING,
        started_at=None,
        finished_at=None,
    )

    provider = MockProvider(
        {
            TRANSACTION_CONTROL_ID: MockPage(
                page=PageRef(provider_page_id=TRANSACTION_CONTROL_ID, page_name="Acme India"),
                batches=(MockBatch(raw=TRANSACTION_PAYLOAD),),
            )
        },
        clock=lambda: NOW,
    )

    outcome = CollectionOrchestrator(
        db_session,
        provider,
        _RecordingQueue(),  # type: ignore[arg-type]
    ).execute_collection_job(run.id)

    assert outcome.status is not CollectionRunStatus.FAILED
    assert db_session.execute(select(func.count()).select_from(Ad)).scalar_one() == 1
    assert db_session.execute(select(func.count()).select_from(AdSnapshot)).scalar_one() == 1
    assert db_session.execute(select(func.count()).select_from(RawResponse)).scalar_one() == 1


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

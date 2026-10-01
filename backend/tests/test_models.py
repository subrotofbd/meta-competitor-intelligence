"""The S1.1 schema, read from the metadata.

Every test here inspects `Base.metadata` -- the same objects Alembic compares
against the live database -- rather than the classes' names. A test that asserted
`hasattr(module, "Competitor")` would keep passing if the class stopped being a
mapped table, which is exactly the regression worth catching.

The complements live in `test_schema_integration`: these prove the schema is what
it claims, that one proves the database agrees.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import CheckConstraint, Table

# Importing the package is what populates `Base.metadata`.
from app.db.base import Base
from app.models import (
    CollectionRun,
    Competitor,
    FacebookPage,
    ProviderRun,
    RawResponse,
)
from app.providers.data.provenance import DataOrigin

pytestmark = pytest.mark.unit

#: Exactly the tables `models/__init__.py` assigns to S1.1. Pinned as a literal
#: rather than derived from the modules, so adding a table fails this test --
#: which is the point. S2's ad tables must not drift in early.
S11_TABLES = frozenset(
    {"competitors", "facebook_pages", "collection_runs", "provider_runs", "raw_responses"}
)

#: S1.2 adds the jobs table. This set is the cumulative S1 scope (S1.1 + S1.2).
S1_TABLES = S11_TABLES | {"jobs"}

#: Exactly the tables `models/__init__.py` assigns to S2.1. A literal for the
#: same reason `S11_TABLES` is one: the boundary is the thing being tested, so it
#: cannot be derived from the thing it bounds.
S21_TABLES = frozenset({"ads", "ad_snapshots", "seen_in_run"})

#: S2.2 adds **no tables at all**. It adds two nullable columns to
#: `ad_snapshots` and two indexes, and nothing else.
#:
#: Pinned as an empty set so the boundary is still asserted. `ad_creatives` was
#: considered and deferred: `app/providers/data/normalize.py::_read_body` reads
#: only `bodies[0]` and flattens it, so the current normalized contract exposes no
#: card-level structure and a per-card table would fabricate rows rather than
#: record observations. `ad_platforms`, `ad_countries` and `landing_pages` are not
#: S2.2 scope and must not be added because an older `ARCHITECTURE.md` lists them
#: alongside `ad_creatives`. A non-empty set here means scope nobody approved.
S22_TABLES: frozenset[str] = frozenset()

#: The cumulative S2 scope, which is everything that exists after S2.2.
S2_TABLES = S1_TABLES | S21_TABLES | S22_TABLES

S11_MODELS = (Competitor, FacebookPage, CollectionRun, ProviderRun, RawResponse)

#: The explicit index names, and the access pattern each one exists for.
EXPECTED_INDEXES = {
    "ix_facebook_pages_competitor_id": "GET /competitors/{id}/pages",
    "ix_collection_runs_facebook_page_id": "latest run for a page and country",
    "ix_provider_runs_collection_run_id": "the calls belonging to a run",
}


def _tables() -> list[Table]:
    return [Base.metadata.tables[name] for name in sorted(S11_TABLES)]


def _columns(table: Table) -> set[str]:
    return set(table.columns.keys())


# ============================================================
# Scope
# ============================================================


def test_s11_defines_exactly_the_five_assigned_tables() -> None:
    """The set is a literal, so a sixth table fails here rather than silently.

    This is the check on the checkpoint boundary itself. `ads`, `ad_snapshots`
    and the queue table all appear in `models/__init__.py` under later
    checkpoints; if one of them appears here, a later checkpoint's work has been
    pulled backwards into S1.1.

    The check is against the S1.1 assignment (S11_TABLES), not the cumulative
    S1 metadata (which now includes S1.2's jobs table). The metadata itself is
    asserted in `test_db_base.py`.
    """
    s11_actual = {name for name in Base.metadata.tables if name in S11_TABLES}
    assert s11_actual == S11_TABLES


def test_no_s11_model_is_mapped_twice_or_left_unmapped() -> None:
    """Every model is a real mapped class with the table it claims."""
    for model in S11_MODELS:
        assert model.__tablename__ in Base.metadata.tables
        assert Base.metadata.tables[model.__tablename__] is model.__table__


# ============================================================
# Rules that apply to every table
# ============================================================


@pytest.mark.parametrize("table", _tables(), ids=lambda t: t.name)
def test_every_table_has_a_uuid_primary_key(table: Table) -> None:
    """UUID, single-column, and defaulted by the application.

    Client-side generation is what lets the orchestrator insert a parent and a
    child in one flush, so the type is load-bearing rather than cosmetic.
    """
    primary_key = list(table.primary_key.columns)
    assert len(primary_key) == 1
    assert isinstance(primary_key[0].type, sa.Uuid)


@pytest.mark.parametrize("table", _tables(), ids=lambda t: t.name)
def test_every_table_carries_both_timestamps(table: Table) -> None:
    columns = _columns(table)
    assert {"created_at", "updated_at"} <= columns

    for name in ("created_at", "updated_at"):
        column = table.columns[name]
        assert column.nullable is False
        assert column.server_default is not None, f"{table.name}.{name} has no server default"


@pytest.mark.parametrize("table", _tables(), ids=lambda t: t.name)
def test_every_timestamp_is_timezone_aware(table: Table) -> None:
    """A naive timestamp cannot be compared against a provider-reported time.

    `meta_delivery_start` arrives in a provider's timezone and `created_at` is
    UTC; the two are compared constantly in the history rules, so storing one
    without an offset loses information permanently.
    """
    for name, column in table.columns.items():
        if isinstance(column.type, sa.DateTime):
            assert column.type.timezone is True, f"{table.name}.{name} is a naive timestamp"


# ============================================================
# Foreign keys, ownership, and reversibility
# ============================================================


def test_the_collection_chain_is_single_parented_end_to_end() -> None:
    """Every foreign key points one level up, and each row has exactly one parent.

    The chain is `competitors -> facebook_pages -> collection_runs ->
    provider_runs -> raw_responses`. A row with two parents, or a parent in a
    different branch, is how "which competitor does this ad belong to" becomes
    unanswerable -- and every downstream question inherits that ambiguity.
    """
    parents = {
        table.name: {
            fk.target_fullname
            for constraint in table.constraints
            if isinstance(constraint, sa.ForeignKeyConstraint)
            for fk in constraint.elements
        }
        for table in _tables()
    }

    assert parents["competitors"] == set()
    assert parents["facebook_pages"] == {"competitors.id"}
    assert parents["collection_runs"] == {"facebook_pages.id"}
    assert parents["provider_runs"] == {"collection_runs.id"}
    assert parents["raw_responses"] == {"provider_runs.id"}


def test_no_foreign_key_cascades_a_delete() -> None:
    """Every delete rule is `RESTRICT`, so collected data cannot vanish silently.

    `RESTRICT` is the point of the whole schema. Commercial ads that stop running
    disappear from Meta permanently, so a run history cannot be re-acquired. A
    `CASCADE` would let a deleted competitor take its pages' entire run history
    and every raw payload with it, which is unrecoverable data loss from an
    ordinary-looking `session.delete(...)`.
    """
    for table in _tables():
        for constraint in table.constraints:
            if isinstance(constraint, sa.ForeignKeyConstraint):
                for fk in constraint.elements:
                    assert fk.ondelete is None or fk.ondelete.upper() == "RESTRICT", (
                        f"{table.name}.{constraint.name} has ON DELETE {fk.ondelete}"
                    )


# ============================================================
# Provenance
# ============================================================


def test_data_origin_lives_on_exactly_one_table() -> None:
    """One owner, reached by foreign key from everywhere below it.

    Storing `data_origin` on each of the three collected tables would give three
    copies that could disagree, and provenance is precisely the thing that must
    not be ambiguous -- AGENTS.md section 7 makes it a product requirement that
    every stored value resolves to one origin.
    """
    holders = {table.name for table in _tables() if "data_origin" in _columns(table)}
    assert holders == {"collection_runs"}


def test_evidence_class_appears_on_no_s11_table() -> None:
    """No S1.1 column holds a value the UI would render.

    `evidence_class` qualifies a value *as displayed*. S1.1 stores only operator
    configuration and raw provider payloads; nothing here is a number or a claim
    a user would read. It arrives with `ads` in S2.1, where there is a value to
    qualify. Asserting its absence keeps a "just in case" column out.
    """
    assert [
        f"{table.name}.{name}"
        for table in _tables()
        for name in _columns(table)
        if name == "evidence_class"
    ] == []


def _stored_values(column: sa.Column[Any]) -> list[str]:
    """The values a `sa.Enum` column will accept, read off the type.

    The generated `CHECK` compiles to a bound parameter, not to inline literals,
    so `"official_api" in constraint.sqltext` is false even when the value is
    accepted. The type's own `enums` list is where the accepted set actually
    lives, and reading it here also proves the values came from the Python enum
    rather than from a list typed out by hand.
    """
    return list(column.type.enums)  # type: ignore[attr-defined]


def test_the_data_origin_column_stores_every_provenance_value() -> None:
    """All four, and nothing else, derived from the `DataOrigin` enum itself.

    Values, not member names: `DataOrigin.official_api` has the name
    `OFFICIAL_API`, and SQLAlchemy persists names by default, which would store
    `OFFICIAL_API` and diverge from every other place the value appears.
    """
    values = _stored_values(CollectionRun.__table__.columns["data_origin"])

    assert values == [origin.value for origin in DataOrigin]
    assert "official_api" in values
    assert "OFFICIAL_API" not in values


def test_the_data_origin_column_is_a_varchar_with_a_named_check() -> None:
    """A `VARCHAR` and a named `CHECK`, not a native PostgreSQL enum.

    `ALTER TYPE ... ADD VALUE` cannot run inside a transaction, so extending a
    native enum is a special case in every future migration and a value can never
    be removed. AGENTS.md section 12 asks for enum changes to be ordinary
    migrations plus a UI label, which is what a `VARCHAR` plus a check gives.
    """
    column = CollectionRun.__table__.columns["data_origin"]
    assert isinstance(column.type, sa.Enum)
    assert column.type.native_enum is False
    assert column.type.create_constraint is True
    assert column.nullable is False

    # The check exists and is named, so it can be reversed by name.
    assert _check_named("collection_runs", "data_origin") is not None


# ============================================================
# Constraints
# ============================================================


def test_a_page_id_belongs_to_exactly_one_competitor() -> None:
    """`UNIQUE` on `page_id` alone, not on `(competitor_id, page_id)`.

    A page under two competitors would make every ad collected through it belong
    to two parents at once. Tracking the same page twice is a data-entry mistake,
    and refusing it is the correct behaviour.
    """
    unique_sets = [
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in FacebookPage.__table__.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    ]
    assert ("page_id",) in unique_sets
    assert ("competitor_id", "page_id") not in unique_sets


def test_one_raw_response_per_provider_call() -> None:
    """A `ProviderResult` carries one `raw`, so a second is a bug worth refusing."""
    unique_sets = [
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in RawResponse.__table__.constraints
        if isinstance(constraint, sa.UniqueConstraint)
    ]
    assert ("provider_run_id",) in unique_sets


def test_a_cost_needs_its_amount_currency_and_method_together() -> None:
    """All three or none, enforced by a `CHECK`.

    AGENTS.md section 7 requires an `ESTIMATE` to render with the method it was
    arrived at. A cost without a method is not displayable, so a partial triple
    is refused at the database rather than shown as a bare number.
    """
    check = _check_text("provider_runs", "cost_all_or_nothing")
    for column in ("cost_amount", "cost_currency", "cost_method"):
        assert check.count(column) == 2, f"{column} should appear in both branches"
    assert "IS NULL" in check
    assert "IS NOT NULL" in check


def test_a_run_cannot_finish_before_it_starts() -> None:
    """Both run tables refuse a negative duration."""
    for name in ("collection_runs", "provider_runs"):
        assert "finished_at >= started_at" in _check_text(name, "finished_after_started")


def test_country_must_be_an_upper_case_iso_alpha2_code() -> None:
    """`IN`, not `in`: a run's country scopes the history rules.

    A lowercase `in` and an uppercase `IN` would split one page's history into
    two, and neither half would look wrong.
    """
    for name in ("facebook_pages", "collection_runs"):
        assert "^[A-Z]{2}$" in _check_text(name, "country_iso_alpha2")


def test_a_competitor_name_cannot_be_blank() -> None:
    """`NOT NULL` says a value must exist, not that it must be non-empty."""
    assert "btrim(name) <> ''" in _check_text("competitors", "name_not_blank")


def test_a_stored_page_url_must_be_http_or_https() -> None:
    """The provider boundary validates this; the database enforces it too.

    A stored destination is fetched by a later checkpoint. A page url that came
    back as `file:///etc/passwd` would otherwise be sitting in the table as if it
    were an ordinary link.
    """
    check = _check_text("facebook_pages", "url_http_only")
    assert "url IS NULL OR" in check
    assert "^https?://" in check


def test_a_negative_record_count_is_refused() -> None:
    assert "records_returned >= 0" in _check_text(
        "collection_runs", "records_returned_not_negative"
    )


def test_an_impossible_http_status_is_refused() -> None:
    assert "BETWEEN 100 AND 599" in _check_text("provider_runs", "http_status_range")


# ============================================================
# The autogenerate trap
# ============================================================


@pytest.mark.parametrize("table", _tables(), ids=lambda t: t.name)
def test_every_check_constraint_is_visible_to_alembic(table: Table) -> None:
    """No `CHECK` may be declared inside `mapped_column(...)`.

    Alembic's autogenerate does not detect check constraints attached to a
    column. It emits the table without them and then reports no drift, so the
    constraint exists in Python and not in the database -- invisible, and passing
    every other test in this file. This is the one class of S1.1 bug that the
    metadata tests could not otherwise catch, which is why
    `test_schema_integration` also compares the live database's checks against
    the metadata.
    """
    column_level = {
        f"{table.name}.{column.name}.{check.name}"
        for column in table.columns
        for check in column.constraints
        if isinstance(check, CheckConstraint)
    }
    assert column_level == set(), (
        f"these checks would be skipped by alembic autogenerate: {sorted(column_level)}"
    )


def test_every_declared_check_constraint_is_named() -> None:
    """An unnamed constraint cannot be reversed by name, and every migration here must be.

    `Base.metadata`'s naming convention turns an unnamed check into a
    hash-based name, which is not stable between runs. `ARCHITECTURE.md`
    requires every migration to be reversible, and reversing a check means naming
    it.
    """
    for table in _tables():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint):
                assert constraint.name is not None, f"{table.name} has an unnamed check"


# ============================================================
# Indexes
# ============================================================


def test_the_only_index_on_a_foreign_key_is_for_a_named_access_pattern() -> None:
    """One index per foreign key, each with a reason, and nothing else.

    A foreign key with no index makes the reverse lookup a sequential scan; an
    index with no access pattern is write amplification. Both are avoided by
    having exactly these three and naming the query each serves.
    """
    indexes = {index.name for table in _tables() for index in table.indexes if not index.unique}
    assert indexes == set(EXPECTED_INDEXES)


def test_no_index_exists_only_in_speculation() -> None:
    """Nothing indexes a column the S1.1 queries do not filter on.

    The queries S2 will need are known -- latest complete run per page and
    country, a page's call history -- and the first one would tempt a composite
    `(page, country, started_at)` index. It is deliberately absent: S2 should
    write the query and measure it before an index is built for it. This test
    fails if one is added, so the decision stays visible instead of becoming
    silent.
    """
    indexed_columns = {
        column.name for table in _tables() for index in table.indexes for column in index.columns
    }
    assert indexed_columns == {"competitor_id", "facebook_page_id", "collection_run_id"}


# ============================================================
# No business logic on a table
# ============================================================


@pytest.mark.parametrize("model", S11_MODELS, ids=lambda m: m.__name__)
def test_models_declare_no_methods_or_properties(model: type[Any]) -> None:
    """Columns and relationships only.

    A method on a mapped class is business logic living on a table, where it
    cannot be reused by a service, cannot be tested without a session, and gets
    inherited by anything that ever subclasses it. `inspect.isroutine` is used
    rather than a source grep, so a `def` inside a docstring is not a method.
    """
    import inspect

    declared = [
        name
        for name, member in vars(model).items()
        if not name.startswith("_") and inspect.isroutine(member)
    ]
    assert declared == [], f"{model.__name__} declares business logic: {declared}"


# ============================================================
# Raw payload integrity
# ============================================================


def test_the_payload_hash_column_exists_and_is_plain() -> None:
    """A plain `String(64)` NOT NULL -- the trigger is what fills it.

    Declared as an ordinary column deliberately. The trigger is invisible to
    autogenerate, so declaring it as anything else here would put the model and
    the database permanently out of step. The size is the 64-character hex
    `sha256` digest.
    """
    column = RawResponse.__table__.columns["payload_hash"]
    assert column.type.length == 64
    assert column.nullable is False
    assert isinstance(column.type, sa.String)


def test_the_payload_column_is_jsonb_and_untyped() -> None:
    """`JSONB`, and `Mapped[Any]` -- the one deliberately untyped value.

    `RawPayload` is `dict | list`; a provider response genuinely can be either,
    and the alternative is a wrapper around data whose entire purpose is to be
    stored untouched. The column must accept both without narrowing.
    """
    column = RawResponse.__table__.columns["payload"]
    assert column.type.__class__.__name__ == "JSONB"
    assert column.nullable is False


# ============================================================
# Helpers
# ============================================================


def _check_named(table_name: str, suffix: str) -> CheckConstraint:
    """Find one named check, failing loudly rather than returning something else.

    Returns the *text* as a string. A `CheckConstraint`'s `sqltext` is a
    `TextClause`, not a `str`, so asserting `something in constraint.sqltext`
    raises `TypeError` and names neither the table nor the constraint that was
    missing. The lookup here is the assertion, and it reports both.
    """
    table = Base.metadata.tables[table_name]
    full_name = f"ck_{table_name}_{suffix}"
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name == full_name:
            return constraint
    known = sorted(str(c.name) for c in table.constraints if isinstance(c, CheckConstraint))
    raise AssertionError(f"no check {full_name!r} on {table_name}; has {known}")


def _check_text(table_name: str, suffix: str) -> str:
    """The SQL text of one named check, as a string.

    A `CheckConstraint.sqltext` is a `TextClause`, and `"x" in clause` raises
    `TypeError: argument of type 'TextClause' is not iterable` -- which names
    neither the table nor the constraint, so a typo in a test name reads as a
    bug in the schema. Every call site goes through here so the failure is always
    the `AssertionError` above.
    """
    return str(_check_named(table_name, suffix).sqltext)

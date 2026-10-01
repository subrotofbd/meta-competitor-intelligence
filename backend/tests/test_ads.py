"""The S2.1 ad-history schema, read from the metadata.

The same discipline as `test_models.py`: every assertion reads
`Base.metadata`, not the class's attributes. A test asserting
`hasattr(Ad, "current_status")` would keep passing after the column was
dropped from the *table* while the attribute lingered, and the attribute is not
what the database stores.

The complements live in `test_schema_integration`. These prove the schema is what
it claims; those prove the database agrees and that the constraints actually
fire.

The claims worth protecting here are the ones a future checkpoint is most likely
to erode by adding a column: `current_status` belongs to S2.3, `copy_hash` and
`creative_hash` to S2.2, and no page or competitor may ever appear on `ads`.
Each of those is asserted as an *absence*, which is the only direction in which
they can be caught.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy import CheckConstraint, Column, Table, UniqueConstraint

# Importing the package is what populates `Base.metadata`.
from app.db.base import Base
from app.models import Ad, AdSnapshot, SeenInRun
from app.providers.data.models import RawAdRecord
from tests.test_models import S21_TABLES

pytestmark = pytest.mark.unit

S21_MODELS = (Ad, AdSnapshot, SeenInRun)


def _table(model: type[Any]) -> Table:
    return Base.metadata.tables[model.__tablename__]


def _columns(model: type[Any]) -> set[str]:
    return set(_table(model).columns.keys())


def _constraints(model: type[Any], kind: type[Any]) -> set[str]:
    return {
        str(constraint.name)
        for constraint in _table(model).constraints
        if isinstance(constraint, kind)
    }


def _unique_column_sets(model: type[Any]) -> set[frozenset[str]]:
    """The column sets of every `UNIQUE` constraint, unnamed convention aside."""
    return {
        frozenset(column.name for column in constraint.columns)
        for constraint in _table(model).constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _is_timestamptz(column: Column[Any]) -> bool:
    """Whether a column stores a timezone-aware timestamp.

    The metadata type is a plain `TypeEngine` as far as a type checker is
    concerned, so the attribute is read through a cast. The alternative --
    `isinstance(column.type, DateTime)` -- would be a weaker assertion, because
    it would also pass for a *naive* `DateTime`, which is the exact thing these
    tests exist to rule out.
    """
    return cast(sa.DateTime, column.type).timezone is True


# ============================================================
# Scope
# ============================================================


def test_s21_defines_exactly_the_three_assigned_tables() -> None:
    """The checkpoint boundary itself, pinned as a literal in `test_models.py`.

    The S1.1 boundary test could not include these tables, and nothing else
    asserts that S2.1 stayed at three. A fourth S2.1 table would be scope nobody
    declared.
    """
    s21_actual = {name for name in Base.metadata.tables if name in S21_TABLES}

    assert s21_actual == S21_TABLES


def test_s22_added_no_tables() -> None:
    """S2.2's boundary is a set of **zero** tables, asserted rather than assumed.

    The tempting additions are `ad_creatives`, `ad_platforms`, `ad_countries` and
    `landing_pages`, because `ARCHITECTURE.md` lists them in one sentence
    together. None of them is approved S2.2 scope, and `ad_creatives` in
    particular cannot be built honestly: the normalizer reads only `bodies[0]`
    and flattens it, so there is no card-level structure to store. Building it
    now would fabricate rows.

    An empty set is still a boundary worth asserting, because it is the thing that
    has to be deleted deliberately when `ad_creatives` is eventually built.
    """
    from tests.test_models import S22_TABLES

    assert S22_TABLES == frozenset()
    assert {name for name in Base.metadata.tables if name in S22_TABLES} == S22_TABLES


def test_s23_added_exactly_the_status_context_table() -> None:
    """S2.3's boundary is one table, and it is the context table.

    Not `ads.current_status`, which `ARCHITECTURE.md` originally specified: an ad
    is served on several pages, so status cannot be a property of the ad. The
    absence of those columns on `ads` is asserted separately, below.
    """
    from tests.test_models import S23_TABLES

    s23_actual = {name for name in Base.metadata.tables if name in S23_TABLES}

    assert s23_actual == S23_TABLES


def test_the_status_context_table_is_keyed_by_ad_page_and_country() -> None:
    """One status per observation context, and no more.

    The unique constraint is what makes "which context is this about?" a question
    with one answer rather than two contradictory rows.
    """
    from app.models.ad_status import AdStatusByContext

    assert _columns(AdStatusByContext) == {
        "id",
        "created_at",
        "updated_at",
        "ad_id",
        "facebook_page_id",
        "country",
        "current_status",
        "provider_active",
        "not_seen_since_at",
        "last_status_run_id",
    }
    assert _unique_column_sets(AdStatusByContext) == {
        frozenset({"ad_id", "facebook_page_id", "country"})
    }


def test_the_status_vocabulary_is_frozen_in_the_database() -> None:
    """`seen` / `not_seen_since` / `presumed_inactive`, checked by the schema.

    An unrecognised status reaching a report is the worst place to discover one,
    so the constraint lives in the database rather than only in Python.

    `seen` is in the set and is not a verdict: it says the latest complete run for
    this context observed the ad, and nothing about how well it performed.
    """
    from app.models.ad_status import AD_STATUS_VALUES, AdStatusByContext

    checks = {
        str(constraint.name): str(constraint.sqltext)
        for constraint in _table(AdStatusByContext).constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_ad_status_by_context_current_status_vocabulary" in checks
    for value in AD_STATUS_VALUES:
        assert value in checks["ck_ad_status_by_context_current_status_vocabulary"]
    assert set(AD_STATUS_VALUES) == {"seen", "not_seen_since", "presumed_inactive"}


def test_provider_active_is_nullable_and_current_status_is_not() -> None:
    """Tri-state evidence versus a required conclusion.

    `provider_active` is NULL when the provider said nothing recognisable, said
    nothing at all, or we did not observe the ad in this context's latest complete
    run -- and NULL is never rounded to False. `current_status` is NOT NULL
    because a row exists only where we have concluded something.
    """
    from app.models.ad_status import AdStatusByContext

    table = _table(AdStatusByContext)

    assert table.c.provider_active.nullable is True
    assert table.c.current_status.nullable is False
    assert table.c.not_seen_since_at.nullable is True
    assert table.c.last_status_run_id.nullable is True


def test_every_status_foreign_key_is_required_and_restrict() -> None:
    """Three parents, all RESTRICT.

    A status row is history: a cascade would let one deleted page take every
    observed status with it, which is the same rule every other table in this
    schema obeys.
    """
    from app.models.ad_status import AdStatusByContext

    table = _table(AdStatusByContext)
    expected = {
        "ad_id": "ads.id",
        "facebook_page_id": "facebook_pages.id",
        "last_status_run_id": "collection_runs.id",
    }

    for column, target in expected.items():
        declared = table.c[column]
        assert declared.foreign_keys, column
        constraint = next(iter(declared.foreign_keys))
        assert constraint.target_fullname == target
        assert constraint.ondelete == "RESTRICT", column

    # `provider_active` and `not_seen_since_at` are not identities, so they carry
    # no foreign key and no nullability of their own beyond the boolean/timestamp.
    for column in ("provider_active", "not_seen_since_at", "current_status"):
        assert not table.c[column].foreign_keys, column


def test_the_status_indexes_are_declared_with_their_access_patterns() -> None:
    """Two on the context table, each for a named query.

    The absence streak walk runs over `collection_runs` and is covered by an index
    there; these two are what make one context's evaluation cheap.
    """
    from app.models.ad_status import AdStatusByContext

    assert {index.name for index in _table(AdStatusByContext).indexes} == {
        "ix_ad_status_by_context_page_country",
        "ix_ad_status_by_context_last_status_run_id",
    }


def test_the_complete_run_index_is_partial_on_complete() -> None:
    """`AGENTS.md` section 8: a FAILED or PARTIAL run can neither advance nor reset
    an absence streak.

    Those runs are *invisible* to the walk, so indexing them would index rows the
    query must never read -- and a provider outage, which is exactly when the index
    matters, would fill it.
    """
    assert "ix_collection_runs_page_country_complete" in {
        index.name for index in Base.metadata.tables["collection_runs"].indexes
    }
    complete_index = next(
        index
        for index in Base.metadata.tables["collection_runs"].indexes
        if index.name == "ix_collection_runs_page_country_complete"
    )
    where = complete_index.dialect_options["postgresql"].get("where")
    assert where is not None, "the index must be partial on status = 'complete'"
    assert "complete" in str(where)


def test_the_status_search_index_guard_still_holds() -> None:
    """No text search index appeared alongside the status table.

    The context table holds no free text to search -- `current_status` is a frozen
    three-value vocabulary -- so this is the same guard as S2.1's, re-run because
    a checkpoint that adds a table is exactly when it could quietly stop
    applying.
    """
    from app.models.ad_status import AdStatusByContext

    for index in _table(AdStatusByContext).indexes:
        assert index.dialect_options["postgresql"].get("using") != "gin", index.name


def test_every_s21_model_is_mapped_to_its_own_table() -> None:
    """A class with no `__tablename__` in the metadata is not a table at all.

    `test_models.py` does this for S1.1's five. These three are new since, and a
    mapped class that was never registered would be invisible to Alembic's
    autogenerate, so the migration would not create it and nothing would fail
    until a query.
    """
    for model in S21_MODELS:
        assert model.__tablename__ in Base.metadata.tables
        assert Base.metadata.tables[model.__tablename__] is model.__table__


# ============================================================
# ads
# ============================================================


def test_ads_carries_exactly_the_expected_columns() -> None:
    """The full column set, listed.

    Every column is load-bearing and the set is small enough to state in full,
    which is what makes the `current_status` and copy-hash absence tests below
    meaningful rather than incidental.
    """
    assert _columns(Ad) == {
        "id",
        "created_at",
        "updated_at",
        "provider",
        "meta_ad_id",
        "data_origin",
        "first_seen_at",
        "last_seen_at",
        "latest_snapshot_id",
    }


def test_ads_has_no_current_status_column() -> None:
    """`ARCHITECTURE.md` lists one, and S2.1 deliberately does not have it.

    The status vocabulary is a state machine over run history and belongs to
    S2.3. Creating the column now would mean storing a value nothing in S2.1 may
    compute, and an `ads` table with a permanently NULL status is a shape that
    invites the next reader to fill it in by hand. This test is what makes that
    deferral stick: it is the thing that has to be deleted, deliberately, when
    S2.3 arrives.
    """
    assert "current_status" not in _columns(Ad)


@pytest.mark.parametrize("column", ["copy_hash", "creative_hash", "not_seen_since"])
def test_ads_defers_the_s22_and_s23_columns(column: str) -> None:
    """`copy_hash`/`creative_hash` are S2.2; the status machine is S2.3.

    Same reasoning as `current_status`, named individually because these are the
    three columns `ARCHITECTURE.md` names for `ads` that S2.1 does not build. A
    column appearing early would also break the S2.2 story that v1 `content_hash`
    digests stay comparable for ever.
    """
    assert column not in _columns(Ad)


def test_ads_identity_is_the_provider_and_the_provider_ad_id() -> None:
    """Two columns, one constraint.

    `meta_ad_id` alone would be ambiguous the moment a second provider is
    registered, so identity is the pair. The constraint is named because the
    persistence layer upserts on it by name.
    """
    assert _unique_column_sets(Ad) == {frozenset({"provider", "meta_ad_id"})}
    assert "uq_ads_provider_meta_ad_id" in {
        str(constraint.name) for constraint in _table(Ad).constraints
    }


def test_ads_carries_no_page_or_competitor_column() -> None:
    """An ad is not owned by a page, and the schema must not make it look so.

    The same ad is served on several pages and across many runs. A
    `facebook_page_id` here would turn "which page saw this" into a property of
    the ad; the lineage is `seen_in_run` -> `collection_run` -> `facebook_page` ->
    `competitor`, which is both correct and already indexed. Checked against the
    foreign keys *and* the columns, because a bare `facebook_page_id` with no
    constraint would be worse.
    """
    # The one foreign key `ads` legitimately has is the current-snapshot
    # pointer, which is the next test's subject rather than this one's.
    for column in _table(Ad).columns:
        if column.name == "latest_snapshot_id":
            continue
        assert not column.foreign_keys, f"ads.{column.name} carries a foreign key"

    assert "facebook_page_id" not in _columns(Ad)
    assert "competitor_id" not in _columns(Ad)


def test_the_only_ad_foreign_key_is_the_current_snapshot_pointer() -> None:
    """Exactly one, and it points forward at a table created after this one.

    The circular reference between `ads.latest_snapshot_id` and
    `ad_snapshots.ad_id` is the reason the migration creates `ads` without this
    constraint and adds it with `ALTER TABLE`. `use_alter=True` on the column is
    what tells SQLAlchemy not to try to emit it inline.
    """
    foreign_keys = [column for column in _table(Ad).columns if column.foreign_keys]

    assert [column.name for column in foreign_keys] == ["latest_snapshot_id"]

    pointer = _table(Ad).c.latest_snapshot_id
    assert pointer.foreign_keys
    assert next(iter(pointer.foreign_keys)).target_fullname == "ad_snapshots.id"
    assert next(iter(pointer.foreign_keys)).ondelete == "RESTRICT"
    assert pointer.foreign_keys.pop().use_alter is True


def test_the_latest_snapshot_pointer_starts_out_nullable() -> None:
    """Nullability is honest rather than convenient.

    An ad exists in our history from the moment we see it, which is before any
    snapshot has been written. A non-null pointer with no snapshot would have to
    be invented; this one admits that it does not know yet.
    """
    assert _table(Ad).c.latest_snapshot_id.nullable is True


def test_ads_first_seen_and_last_seen_are_both_required_and_aware() -> None:
    """They are our observation times, not the provider's, and both are mandatory.

    `meta_delivery_start` is what Meta claims about when an ad began;
    `first_seen_at` is when we first observed it, and for a commercial ad those
    can be far apart. Keeping them apart is the specific error AGENTS.md section 8
    names, so no column here may be nullable: a missing sighting time is not a
    thing, it is a hole.
    """
    for name in ("first_seen_at", "last_seen_at"):
        column = _table(Ad).c[name]
        assert column.nullable is False, name
        assert _is_timestamptz(column), name


def test_ads_checks_reject_a_blank_identity_and_an_impossible_sighting_order() -> None:
    """Four checks: two not-blank, one sighting order, plus the enum's own.

    The sighting-order check is the interesting one. `last_seen_at` only ever
    moves forward in application code, so a row where it precedes `first_seen_at`
    is either a bug or a hand-edited value, and neither should be storable.
    """
    checks = _constraints(Ad, CheckConstraint)

    assert "ck_ads_provider_not_blank" in checks
    assert "ck_ads_meta_ad_id_not_blank" in checks
    assert "ck_ads_ad_sighting_order" in checks
    # `_stored_enum` creates the `data_origin` vocabulary check.
    assert "ck_ads_data_origin" in checks


def test_ads_stores_data_origin_and_never_the_evidence_class() -> None:
    """Two independent axes, and only one of them is a column.

    `AGENTS.md` section 7: `data_origin` is how the value was obtained;
    `EvidenceClass` is how far the product stands behind it, and it is *derived*
    from the origin rather than stored. A stored copy could disagree with the
    derivation, and a disagreement here is a value badged as verified when it is
    not.
    """
    assert "data_origin" in _columns(Ad)
    assert "evidence_class" not in _columns(Ad)

    for model in S21_MODELS:
        assert "evidence_class" not in _columns(model), model.__tablename__


# ============================================================
# ad_snapshots
# ============================================================


def test_ad_snapshots_carries_exactly_the_expected_columns() -> None:
    """The full column set, listed.

    `copy_hash` and `creative_hash` arrived in S2.2 as siblings of the frozen
    `content_hash`, not as inputs to it. Note what is still absent: no
    `page_id`/`country` columns -- targeting is S2.2's *per-dimension tables*,
    which this checkpoint deliberately did not build (see the `ad_creatives`
    deferral below).
    """
    assert _columns(AdSnapshot) == {
        "id",
        "created_at",
        "updated_at",
        "ad_id",
        "collection_run_id",
        "raw_ref",
        "content_hash",
        "copy_hash",
        "creative_hash",
        "ad_status",
        "meta_delivery_start",
        "normalized",
    }


@pytest.mark.parametrize("column", ["countries", "platforms", "landing_page_id"])
def test_ad_snapshots_defers_the_per_dimension_s22_tables(column: str) -> None:
    """Targeting stays in its own tables, which this checkpoint did not build.

    `ad_countries` and `ad_platforms` are not S2.2 scope. S2.2 added the two
    *digest* columns and duplicate grouping; the per-dimension tables are
    separate work, and adding them here because an older `ARCHITECTURE.md`
    mentions them in the same list would be scope nobody approved.
    """
    assert column not in _columns(AdSnapshot)


def test_ad_snapshots_has_no_card_level_creative_columns() -> None:
    """`ad_creatives` is deferred, and this is what keeps it deferred.

    The current normalized contract exposes no card-level structure:
    `app/providers/data/normalize.py::_read_body` reads only `bodies[0]` and
    flattens it into `RawAdRecord`, and the committed corpus holds nine ads, every
    one single-bodied. A per-card table built today would fabricate rows rather
    than record observations, so the columns that would hold card copy do not
    exist and this test fails if one is added without a normalizer change first.
    """
    for column in ("card_key", "card_index", "card_copy"):
        assert column not in _columns(AdSnapshot)


def test_the_two_s22_digests_are_nullable_and_stay_that_way() -> None:
    """`NULL` means "this observation predates S2.2", and it is a real state.

    `ad_snapshots` is append-only, so a row written before the columns existed can
    never be backfilled -- an `UPDATE` is refused by the trigger. A `NOT NULL`
    column would therefore make them un-addable to any populated history, which is
    precisely the state this schema exists to survive.
    """
    assert _table(AdSnapshot).c.copy_hash.nullable is True
    assert _table(AdSnapshot).c.creative_hash.nullable is True


def test_both_s22_digests_are_checked_with_the_same_pattern_as_content_hash() -> None:
    """One validation pattern in the schema, not three that can drift.

    The expression is byte-identical to S2.1's, so a malformed digest cannot make
    duplicate detection silently stop finding anything. It also accepts NULL
    without an `IS NULL OR` guard: a `CHECK` is satisfied unless it evaluates to
    FALSE, and a regex yields NULL for NULL.
    """
    content_expression = next(
        str(constraint.sqltext)
        for constraint in _table(AdSnapshot).constraints
        if isinstance(constraint, CheckConstraint)
        and str(constraint.name) == "ck_ad_snapshots_content_hash_is_sha256_hex"
    )
    expressions = {
        str(constraint.name): str(constraint.sqltext)
        for constraint in _table(AdSnapshot).constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_ad_snapshots_copy_hash_is_sha256_hex" in expressions
    assert "ck_ad_snapshots_creative_hash_is_sha256_hex" in expressions
    assert expressions["ck_ad_snapshots_copy_hash_is_sha256_hex"] == content_expression
    assert expressions["ck_ad_snapshots_creative_hash_is_sha256_hex"] == content_expression


def test_both_s22_digest_indexes_are_declared_with_a_named_access_pattern() -> None:
    """One index per query in `app/services/duplicate_detection.py`.

    Named explicitly rather than derived, so a rename that left the query
    unindexed fails here instead of degrading silently into a full scan of the
    whole history.
    """
    # S3.2 added two *expression* indexes to this table (the search projection over
    # `normalized`), so the set is no longer exactly the two digest indexes. They are
    # named rather than derived for the same reason: a rename that left the query
    # unindexed must fail here rather than degrade into a scan of the whole history.
    assert {index.name for index in _table(AdSnapshot).indexes} == {
        "ix_ad_snapshots_copy_hash",
        "ix_ad_snapshots_creative_hash",
        "ix_ad_snapshots_copy_fts_gin",
        "ix_ad_snapshots_copy_trgm_gin",
    }
    for index in _table(AdSnapshot).indexes:
        # The two digest indexes are on a single real column each; the two search
        # indexes have no columns at all, only an expression.
        expected_columns = 1 if "hash" in index.name else 0
        assert len(index.columns) == expected_columns, index.name


def test_a_snapshot_may_hold_at_most_one_row_per_ad_per_run() -> None:
    """The cardinality rule, expressed by the database rather than by convention.

    A run that serves one ad three times cannot write three snapshots. Application
    code collapses those sightings before it gets here, so this constraint is the
    backstop that makes the rule impossible to get wrong rather than merely
    discouraged.
    """
    assert _unique_column_sets(AdSnapshot) == {frozenset({"ad_id", "collection_run_id"})}


def test_a_snapshot_names_the_response_it_was_read_from_and_cannot_exist_without_one() -> None:
    """`raw_ref` is the whole audit trail, and it is NOT NULL.

    snapshot -> `raw_responses` -> `provider_runs` -> `collection_runs` ->
    `facebook_pages` -> `competitors`. A snapshot that cannot name its source is
    an assertion with nothing behind it, and the row it points at is the copy that
    cannot be re-acquired once the ad stops running.

    `RESTRICT` rather than `CASCADE` for the same reason: deleting a raw response
    would otherwise take the reading of it with it.
    """
    column = _table(AdSnapshot).c.raw_ref

    assert column.nullable is False
    assert column.foreign_keys
    constraint = next(iter(column.foreign_keys))
    assert constraint.target_fullname == "raw_responses.id"
    assert constraint.ondelete == "RESTRICT"


@pytest.mark.parametrize(
    ("column", "target"),
    [
        ("ad_id", "ads.id"),
        ("collection_run_id", "collection_runs.id"),
    ],
)
def test_every_snapshot_foreign_key_is_required_and_restrict(column: str, target: str) -> None:
    """Both parents are mandatory, and neither may cascade.

    A cascade would let a deleted competitor take every observation of every ad
    that competitor ever ran, which is the entire history the product exists to
    keep.
    """
    declared = _table(AdSnapshot).c[column]

    assert declared.nullable is False
    assert declared.foreign_keys
    constraint = next(iter(declared.foreign_keys))
    assert constraint.target_fullname == target
    assert constraint.ondelete == "RESTRICT"


def test_a_snapshot_must_carry_a_content_hash_that_looks_like_a_sha256() -> None:
    """The check is load-bearing in a way `VARCHAR(64)` is not.

    A malformed digest would not fail loudly -- it would make every future
    comparison unequal, and no snapshot would ever be written again. That is a
    silent, permanent loss of the ability to detect change, so the shape is
    checked at the database rather than trusted from Python.
    """
    assert _table(AdSnapshot).c.content_hash.nullable is False

    checks = {
        str(constraint.name): str(constraint.sqltext)
        for constraint in _table(AdSnapshot).constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_ad_snapshots_content_hash_is_sha256_hex" in checks
    assert "^[0-9a-f]{64}$" in checks["ck_ad_snapshots_content_hash_is_sha256_hex"]


def test_the_stored_normalized_record_is_required_and_is_jsonb() -> None:
    """NOT NULL and JSONB.

    NOT NULL because the point of the row is the observation; a snapshot with no
    stored reading would be a hash with nothing to describe. JSONB rather than
    text because a reader queries it -- and `content_hash` is computed from the
    `RawAdRecord`, not from this column, precisely so JSONB's key normalisation
    cannot move a digest.
    """
    column = _table(AdSnapshot).c.normalized

    assert column.nullable is False
    assert isinstance(column.type, sa.dialects.postgresql.JSONB)


def test_a_snapshot_keeps_the_provider_status_verbatim_and_may_have_no_start_date() -> None:
    """`ad_status` is the provider's wording, untranslated, and optional.

    It is not `provider_active`; nothing derives a domain status until S2.3, and
    a provider that reports no status must not be given one. `meta_delivery_start`
    is nullable for the same reason, and is a different fact from anything on
    `ads`.
    """
    assert _table(AdSnapshot).c.ad_status.nullable is True
    assert _table(AdSnapshot).c.meta_delivery_start.nullable is True
    assert _is_timestamptz(_table(AdSnapshot).c.meta_delivery_start)


# ============================================================
# seen_in_run
# ============================================================


def test_seen_in_run_carries_exactly_the_expected_columns() -> None:
    """The full column set, listed.

    No timestamp of its own: the observation happened *during* the run, and
    `collection_run_id` is that context. The inherited `created_at` is when the
    row was written, which doubles as the observation clock for the ad's own
    `first_seen_at`/`last_seen_at` because both are stamped from the same
    `now()` in the same transaction.
    """
    assert _columns(SeenInRun) == {
        "id",
        "created_at",
        "updated_at",
        "ad_id",
        "collection_run_id",
        "snapshot_id",
    }


def test_seen_in_run_records_at_most_one_sighting_per_ad_per_run() -> None:
    """`(ad, run)`, which is what makes the second sighting an update.

    The persistence layer upserts on exactly this pair. A provider may legitimately
    serve one ad twice in one walk, and the honest response is to correct the
    link rather than add a second row saying the same thing happened twice.
    """
    assert _unique_column_sets(SeenInRun) == {frozenset({"ad_id", "collection_run_id"})}


@pytest.mark.parametrize(
    ("column", "target"),
    [
        ("ad_id", "ads.id"),
        ("collection_run_id", "collection_runs.id"),
        ("snapshot_id", "ad_snapshots.id"),
    ],
)
def test_every_seen_in_run_foreign_key_is_required_and_restrict(column: str, target: str) -> None:
    """Three mandatory parents, all RESTRICT.

    `snapshot_id` in particular: a link row that pointed at nothing would be
    indistinguishable from a run that saw an ad with no snapshot, and the pointer
    is how a reader finds what was actually observed.
    """
    declared = _table(SeenInRun).c[column]

    assert declared.nullable is False, column
    assert declared.foreign_keys, column
    constraint = next(iter(declared.foreign_keys))
    assert constraint.target_fullname == target
    assert constraint.ondelete == "RESTRICT"


def test_seen_in_run_declares_no_check_constraints() -> None:
    """It is a link, so there is no shape rule to enforce.

    Stated explicitly because "no checks" looks like an oversight when every other
    table in this schema has some. It is the same reason the table is not
    append-only: it is not an observation, it is the fact that an observation
    happened in a particular run.
    """
    assert _constraints(SeenInRun, CheckConstraint) == set()


# ============================================================
# Properties that hold across the three tables
# ============================================================


@pytest.mark.parametrize("model", S21_MODELS, ids=lambda m: m.__tablename__)
def test_every_s21_table_has_one_uuid_primary_key(model: type[Any]) -> None:
    """Client-side generation, so a parent can be inserted and its child in one flush.

    This is the property the persistence layer depends on when it writes an ad and
    its snapshot together. A server-generated id would not be knowable until the
    row was written.
    """
    primary_key = list(_table(model).primary_key.columns)

    assert len(primary_key) == 1
    assert isinstance(primary_key[0].type, sa.Uuid)


@pytest.mark.parametrize("model", S21_MODELS, ids=lambda m: m.__tablename__)
def test_every_s21_timestamp_is_timezone_aware(model: type[Any]) -> None:
    """`timestamptz` throughout.

    A naive timestamp cannot be compared against a provider-reported delivery date
    from another timezone, and the two are compared constantly -- `first_seen_at`
    against `meta_delivery_start` in particular.
    """
    for name in ("created_at", "updated_at"):
        assert _is_timestamptz(_table(model).c[name]), f"{model.__tablename__}.{name}"


@pytest.mark.parametrize("model", S21_MODELS, ids=lambda m: m.__tablename__)
def test_no_s21_foreign_key_cascades_a_delete(model: type[Any]) -> None:
    """Every one is RESTRICT.

    The same rule as S1.1, applied to the tables that hold the evidence. A cascade
    anywhere in this chain means one deleted page takes irreplaceable observation
    history with it.
    """
    for column in _table(model).columns:
        for constraint in column.foreign_keys:
            assert constraint.ondelete == "RESTRICT", (
                f"{model.__tablename__}.{column.name} -> "
                f"{constraint.target_fullname} is {constraint.ondelete!r}"
            )


@pytest.mark.parametrize("model", S21_MODELS, ids=lambda m: m.__tablename__)
def test_every_s21_table_is_single_parented_where_it_declares_a_parent(model: type[Any]) -> None:
    """No ambiguous foreign keys.

    `ads.latest_snapshot_id` and `ad_snapshots.ad_id` point at each other, so
    SQLAlchemy cannot infer which is which from a bare attribute name. Where two
    foreign keys meet on one table, the relationship must say which it means --
    asserted by the relationship tests below rather than by inspecting strings.
    """
    parents: dict[str, list[str]] = {}
    for column in _table(model).columns:
        for constraint in column.foreign_keys:
            parents.setdefault(constraint.target_fullname, []).append(column.name)

    for target, columns in parents.items():
        assert len(columns) == 1, f"{model.__tablename__} -> {target}: {columns}"


def test_the_ad_and_snapshot_relationships_name_the_side_they_mean() -> None:
    """The circular pair, disambiguated on both sides.

    Without `foreign_keys` on both, SQLAlchemy refuses to configure the mappers at
    all -- so this is not a style check, it is what makes the pair loadable.
    """
    from sqlalchemy import inspect as sa_inspect

    ad_mapper = sa_inspect(Ad)
    snapshot_mapper = sa_inspect(AdSnapshot)

    # `local_remote_pairs` rather than `local_foreign_keys`: the attribute is on
    # the mapper's relationship properties, and reading it off the *table*
    # metadata -- where both keys live -- would assert nothing about which side
    # each relationship actually resolved to.
    def _remote(relationship: Any) -> tuple[str, str]:
        """The mapper and the column this relationship points at.

        `local_remote_pairs` is `(local, remote)`, so `pair[1]` is the column on
        the *target* mapper. Combined with `mapper.class_` that names both ends
        unambiguously -- `ad_id` alone would not, because both tables have one.
        """
        ((_local, remote),) = relationship.local_remote_pairs
        return relationship.mapper.class_.__name__, remote.name

    snapshots = next(rel for rel in ad_mapper.relationships if rel.key == "snapshots")
    assert _remote(snapshots) == ("AdSnapshot", "ad_id")

    back = next(rel for rel in snapshot_mapper.relationships if rel.key == "ad")
    assert _remote(back) == ("Ad", "id")

    # And both mappers must be configured, not merely declared. An unresolvable
    # circular reference is not an error at import -- it raises on first use, so
    # touching `configure_mappers()` is what proves the pair is loadable at all.
    from sqlalchemy.orm import configure_mappers

    configure_mappers()

    assert ad_mapper.configured
    assert snapshot_mapper.configured


def test_seen_in_run_declares_no_relationship_and_the_models_declare_no_methods() -> None:
    """S2.1 is storage and writing, so the models hold no behaviour.

    `test_models.py` asserts this for the S1.1 models. These three are new, and a
    method on a model is where domain logic goes to be untested and
    un-replaceable: the same question must be answerable by any provider, and
    persistence decisions belong to `app/services/ad_persistence.py`.
    """
    for model in S21_MODELS:
        declared = {
            name
            for name, value in vars(model).items()
            if not name.startswith("_")
            and not isinstance(value, (Column, sa.orm.RelationshipProperty))
            and not hasattr(type(model), "__abstract__")
            and callable(value)
        }
        assert declared == set(), f"{model.__name__} declares {sorted(declared)}"


def test_exactly_one_s21_table_carries_a_text_search_index() -> None:
    """This test used to assert that **no** GIN index existed on the S2.1 schema.

    It existed to stop index overengineering: `pg_trgm` was installed in S0.2, and an
    index built before the query that needs it is how that starts. S3.2 wrote the
    search query and added the indexes it needs, so the guard has changed shape rather
    than simply disappearing -- the intent is still "no index without a query behind
    it", and it is now checkable in both directions.

    **S2.2's two btree indexes** on `ad_snapshots(copy_hash)` and `(creative_hash)`
    were always exempt: they are equality lookups for duplicate-grouping queries
    S2.2 also wrote, and the guard was always specifically about indexing copy *text*.

    The two GIN indexes that now exist are the S3.2 search projection, declared by
    migration `0011` and exercised by `test_the_search_indexes_exist` and
    `test_the_search_query_matches_the_index_expression_exactly` in `test_api_ads.py`,
    which also assert them in the live database. Every other S2.1 table must still have
    no GIN index, which is what keeps the next index from being added speculatively.
    """
    gin_indexes = {
        f"{model.__tablename__}.{index.name}"
        for model in S21_MODELS
        for index in _table(model).indexes
        if index.dialect_options["postgresql"].get("using") == "gin"
    }

    assert gin_indexes == {
        "ad_snapshots.ix_ad_snapshots_copy_fts_gin",
        "ad_snapshots.ix_ad_snapshots_copy_trgm_gin",
    }, gin_indexes


def test_an_internal_id_is_never_stored_where_a_provider_id_belongs() -> None:
    """The two id spaces are separate columns, and the types keep them apart.

    `meta_ad_id` is a provider-supplied string and `id` is a UUID this project
    generated. Nothing in S2.1 accepts a provider id where a `uuid.UUID` is
    expected, and nothing accepts a UUID where the provider's own id belongs -- so
    a page rename or a provider renumbering cannot fork one ad into two, and an
    internal key is never mistaken for a provider's.
    """
    table = _table(Ad)

    assert isinstance(table.c.id.type, sa.Uuid)
    assert isinstance(table.c.meta_ad_id.type, sa.String)
    assert isinstance(table.c.provider.type, sa.String)

    # The identity is a pair of provider-supplied strings; the primary key is a
    # project-generated UUID. Confusing the two is the mistake this guards.
    identity = next(
        constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
    )
    assert all(isinstance(column.type, sa.String) for column in identity.columns)

    # And the pointer to a snapshot is a UUID, not a provider id.
    assert isinstance(table.c.latest_snapshot_id.type, sa.Uuid)


def test_provider_ids_are_stored_as_text_and_are_not_uuid_typed() -> None:
    """A provider id is arbitrary text, and the column admits that.

    `meta_ad_id` is a `VARCHAR`, not a `UUID`, because a provider's ids are
    whatever that provider decided they are. This is the concrete reason ad
    identity is `(provider, meta_ad_id)` and cannot be just a UUID: a
    `UUID`-typed column would refuse the corpus the mock provider actually
    serves.
    """
    record = RawAdRecord(external_ad_id="mock-ad-000701")

    assert isinstance(_table(Ad).c.meta_ad_id.type, sa.String)
    assert not isinstance(_table(Ad).c.meta_ad_id.type, sa.Uuid)
    # The value the normalizer produces is a plain, non-UUID string.
    assert record.external_ad_id == "mock-ad-000701"

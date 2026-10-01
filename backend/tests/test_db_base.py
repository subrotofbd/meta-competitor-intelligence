"""Declarative base and constraint naming.

The naming convention is not cosmetic: Alembic drops constraints by name when
reversing a migration, and an unnamed constraint gets a hash-based name that can
change between runs. These tests pin the convention and prove it reaches the
generated DDL.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.db.base import Base

pytestmark = pytest.mark.unit


def test_the_metadata_holds_exactly_the_shipped_tables() -> None:
    """The base is the single registry every table joins, and it holds everything shipped.

    S0.2 asserted this metadata was empty. S1.1 added 5 tables, S1.2 the jobs
    table, S2.1 the three ad-history tables, S2.3 one status table, S2.4 two media
    tables, and S3.1 two analysis tables. This test asserts the cumulative scope
    while the per-checkpoint boundary tests in `test_models.py` assert the
    assignments specifically.

    The name said "s2" and the assertion said `S2_TABLES` while the scope had moved
    on, so S3.1 pushed this test **already failing** -- it was never re-run. It
    asserts `ALL_TABLES` now.
    """
    from tests.test_models import ALL_TABLES

    assert set(Base.metadata.tables) == ALL_TABLES
    assert Base.metadata.naming_convention, "the naming convention must survive S2.1"


def test_convention_covers_every_constraint_kind() -> None:
    convention = Base.metadata.naming_convention
    assert set(convention) == {"ix", "uq", "ck", "fk", "pk"}


def test_convention_reaches_generated_ddl() -> None:
    """Compile real DDL and check the names Alembic will later need to drop by.

    A throwaway MetaData is used rather than `Base.metadata`, so the probe table
    cannot leak into `Base.metadata` and make the next `--autogenerate` emit a
    `create_table` for a table that does not exist.
    """
    probe = MetaData(naming_convention=Base.metadata.naming_convention)
    table = Table(
        "ad_probe",
        probe,
        Column("id", Integer, primary_key=True),
        Column("code", String(16), nullable=False, unique=True),
    )

    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "CONSTRAINT pk_ad_probe" in ddl
    assert "CONSTRAINT uq_ad_probe_code" in ddl

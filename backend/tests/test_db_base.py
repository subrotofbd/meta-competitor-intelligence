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


def test_the_metadata_holds_exactly_the_s1_tables() -> None:
    """The base is the single registry every table joins, and it holds S1.1 + S1.2.

    S0.2 asserted this metadata was empty. S1.1 added 5 tables. S1.2 adds the
    jobs table. The cumulative S1 scope is 6 tables. This test asserts the
    cumulative scope while the S1.1 boundary test in test_models.py asserts
    the S1.1 assignment specifically.
    """
    from tests.test_models import S1_TABLES

    assert set(Base.metadata.tables) == S1_TABLES
    assert Base.metadata.naming_convention, "the naming convention must survive S1.2"


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

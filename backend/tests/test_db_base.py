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


def test_the_metadata_holds_exactly_the_s11_tables() -> None:
    """The base is the single registry every table joins, and it holds only S1.1's.

    S0.2 asserted this metadata was empty. S1.1's own scope check lives in
    `test_models`, where it can also compare the table names against the
    checkpoint charter; what is pinned here is narrower and about the *base*: the
    convention is still attached, and no table arrived from outside the five the
    migration creates.
    """
    from tests.test_models import S11_TABLES

    assert set(Base.metadata.tables) == S11_TABLES
    assert Base.metadata.naming_convention, "the naming convention must survive S1.1"


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

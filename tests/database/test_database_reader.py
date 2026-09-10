# File: tests/database/test_database_reader.py
"""Tests for uadas_core.database.database_reader.DatabaseReader, against a real DuckDB connection."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from uadas_core.core.exceptions import ReaderError
from uadas_core.database.connection_profile import ConnectionProfile, DatabaseType
from uadas_core.database.database_reader import DatabaseReader
from uadas_core.database.duckdb_connection import DuckDbConnection


@pytest.fixture()
def connection(tmp_path: Path) -> DuckDbConnection:
    db_path = tmp_path / "test.duckdb"
    raw = duckdb.connect(str(db_path))
    raw.execute("CREATE TABLE sales (region VARCHAR, revenue INTEGER)")
    raw.execute("INSERT INTO sales VALUES ('east', 100), ('west', 200)")
    raw.close()

    profile = ConnectionProfile(
        name="test-conn", db_type=DatabaseType.DUCKDB, database=str(db_path)
    )
    return DuckDbConnection(profile)


@pytest.fixture()
def query_connection(connection: DuckDbConnection) -> DuckDbConnection:
    """The same seeded DuckDB, but with the arbitrary-SQL capability granted (Phase 1.8)."""
    return DuckDbConnection(connection.profile, allow_arbitrary_queries=True)


def test_read_table_returns_a_dataset(connection: DuckDbConnection) -> None:
    dataset = DatabaseReader.read_table(connection, "sales")

    assert dataset.row_count == 2
    assert dataset.column_count == 2
    assert dataset.name == "test-conn — sales"
    assert dataset.source_format == "database:duckdb"


def test_read_table_unknown_table_raises_reader_error(
    connection: DuckDbConnection,
) -> None:
    with pytest.raises(ReaderError):
        DatabaseReader.read_table(connection, "does_not_exist")


def test_read_query_returns_a_dataset(query_connection: DuckDbConnection) -> None:
    dataset = DatabaseReader.read_query(
        query_connection, "SELECT SUM(revenue) AS total FROM sales"
    )

    assert dataset.row_count == 1
    assert dataset.dataframe["total"].iloc[0] == 300
    assert dataset.name == "test-conn — query"


def test_read_query_with_explicit_name(query_connection: DuckDbConnection) -> None:
    dataset = DatabaseReader.read_query(
        query_connection, "SELECT * FROM sales", name="My Query"
    )
    assert dataset.name == "My Query"


def test_read_query_bad_sql_raises_reader_error(
    query_connection: DuckDbConnection,
) -> None:
    with pytest.raises(ReaderError):
        DatabaseReader.read_query(query_connection, "NOT VALID SQL AT ALL")


def test_read_query_refused_when_connection_lacks_the_query_capability(
    connection: DuckDbConnection,
) -> None:
    """read_query surfaces the capability refusal as a ReaderError (web-transition Phase 1.8).

    Red before the fix: the query ran for any connection. Green after:
    a connection opened without ``allow_arbitrary_queries=True`` makes
    ``execute_query`` raise ``ServiceError``, which ``read_query`` wraps
    as ``ReaderError``.
    """
    with pytest.raises(ReaderError, match="not permitted to run arbitrary SQL"):
        DatabaseReader.read_query(connection, "SELECT * FROM sales")

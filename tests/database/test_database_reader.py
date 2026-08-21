# File: tests/database/test_database_reader.py
"""Tests for src.database.database_reader.DatabaseReader, against a real DuckDB connection."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.core.exceptions import ReaderError
from src.database.connection_profile import ConnectionProfile, DatabaseType
from src.database.database_reader import DatabaseReader
from src.database.duckdb_connection import DuckDbConnection


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


def test_read_query_returns_a_dataset(connection: DuckDbConnection) -> None:
    dataset = DatabaseReader.read_query(
        connection, "SELECT SUM(revenue) AS total FROM sales"
    )

    assert dataset.row_count == 1
    assert dataset.dataframe["total"].iloc[0] == 300
    assert dataset.name == "test-conn — query"


def test_read_query_with_explicit_name(connection: DuckDbConnection) -> None:
    dataset = DatabaseReader.read_query(
        connection, "SELECT * FROM sales", name="My Query"
    )
    assert dataset.name == "My Query"


def test_read_query_bad_sql_raises_reader_error(connection: DuckDbConnection) -> None:
    with pytest.raises(ReaderError):
        DatabaseReader.read_query(connection, "NOT VALID SQL AT ALL")

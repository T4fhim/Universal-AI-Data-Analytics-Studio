# File: tests/database/test_base_connection.py
"""Tests for uadas_core.database.base_connection.BaseDatabaseConnection's shared logic.

Exercised through DuckDbConnection specifically — the one connector in
this package that needs no live server, so these tests run a genuine,
unmocked connect()/list_tables()/read_table()/execute_query() round
trip against a real (temporary, file-based) database rather than
mocking the SQLAlchemy layer. The four server connectors
(PostgresConnection/MySqlConnection/SqlServerConnection/
OracleConnection) share this exact same base-class logic — see
tests/database/test_server_connection_urls.py for what is actually
connector-specific about them (their connection URLs), which is what
those tests cover instead, since no live server of any of those four
kinds is available to test against here.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.database.base_connection import _redact_credentials
from uadas_core.database.connection_profile import ConnectionProfile, DatabaseType
from uadas_core.database.duckdb_connection import DuckDbConnection


@pytest.fixture()
def seeded_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute("CREATE TABLE sales (region VARCHAR, revenue INTEGER)")
    connection.execute(
        "INSERT INTO sales VALUES ('east', 100), ('west', 200), ('north', 300)"
    )
    connection.close()
    return db_path


@pytest.fixture()
def connection(seeded_db_path: Path) -> DuckDbConnection:
    profile = ConnectionProfile(
        name="test-duckdb", db_type=DatabaseType.DUCKDB, database=str(seeded_db_path)
    )
    return DuckDbConnection(profile)


@pytest.fixture()
def query_connection(seeded_db_path: Path) -> DuckDbConnection:
    """A connection with the arbitrary-SQL capability granted (web-transition Phase 1.8)."""
    profile = ConnectionProfile(
        name="test-duckdb", db_type=DatabaseType.DUCKDB, database=str(seeded_db_path)
    )
    return DuckDbConnection(profile, allow_arbitrary_queries=True)


def test_test_connection_succeeds_against_a_real_database(
    connection: DuckDbConnection,
) -> None:
    assert connection.test_connection() is True


def test_list_tables_returns_the_seeded_table(connection: DuckDbConnection) -> None:
    assert connection.list_tables() == ["sales"]


def test_read_table_returns_all_rows(connection: DuckDbConnection) -> None:
    dataframe = connection.read_table("sales")
    assert len(dataframe) == 3
    assert set(dataframe.columns) == {"region", "revenue"}


def test_read_table_respects_row_limit(connection: DuckDbConnection) -> None:
    dataframe = connection.read_table("sales", row_limit=1)
    assert len(dataframe) == 1


def test_read_table_unknown_table_raises(connection: DuckDbConnection) -> None:
    with pytest.raises(ServiceError):
        connection.read_table("does_not_exist")


def test_execute_query_runs_arbitrary_sql(query_connection: DuckDbConnection) -> None:
    dataframe = query_connection.execute_query(
        "SELECT SUM(revenue) AS total FROM sales"
    )
    assert dataframe["total"].iloc[0] == 600


def test_execute_query_bad_sql_raises(query_connection: DuckDbConnection) -> None:
    with pytest.raises(ServiceError):
        query_connection.execute_query("SELECT this is not valid sql")


def test_execute_query_refused_without_the_capability(
    connection: DuckDbConnection,
) -> None:
    """A connection opened for table browsing must reject arbitrary SQL (Phase 1.8).

    Red before the fix: ``execute_query`` ran the SQL for any connection.
    Green after: it raises ``ServiceError`` before the engine is touched
    unless ``allow_arbitrary_queries=True`` was passed at construction.
    """
    with pytest.raises(ServiceError, match="not permitted to run arbitrary SQL"):
        connection.execute_query("SELECT SUM(revenue) AS total FROM sales")


def test_connect_missing_database_file_raises_on_use(tmp_path: Path) -> None:
    # DuckDB creates a fresh empty database file if one doesn't exist
    # at the given path (rather than erroring), so "missing file" isn't
    # itself a failure mode here — but querying a table that was never
    # created in that fresh database is.
    profile = ConnectionProfile(
        name="fresh", db_type=DatabaseType.DUCKDB, database=str(tmp_path / "new.duckdb")
    )
    connection = DuckDbConnection(profile)
    with pytest.raises(ServiceError):
        connection.read_table("nonexistent")


def test_close_disposes_the_engine(connection: DuckDbConnection) -> None:
    connection.connect()
    assert connection._engine is not None
    connection.close()
    assert connection._engine is None


# -- _redact_credentials (security-reviewer-flagged fix: exception text from a
# DBAPI driver can embed a password; every ServiceError this module raises
# passes str(exc) through this first) --------------------------------------


def test_redact_credentials_strips_url_embedded_password() -> None:
    text = "connection to postgresql://alice:hunter2@dbhost:5432/mydb failed"
    assert "hunter2" not in _redact_credentials(text)
    assert "alice" in _redact_credentials(text)  # username isn't secret


def test_redact_credentials_strips_password_query_param() -> None:
    text = "Login failed: password=hunter2; user=alice"
    assert "hunter2" not in _redact_credentials(text)


def test_redact_credentials_strips_odbc_pwd_param() -> None:
    text = "driver error: pwd=hunter2;uid=alice"
    assert "hunter2" not in _redact_credentials(text)


def test_redact_credentials_leaves_ordinary_text_unchanged() -> None:
    text = "table 'sales' does not exist"
    assert _redact_credentials(text) == text

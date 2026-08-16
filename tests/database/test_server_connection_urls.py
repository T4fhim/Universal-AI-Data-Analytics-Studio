# File: tests/database/test_server_connection_urls.py
"""Tests for the four server connectors' connection-URL construction.

No live PostgreSQL/MySQL/SQL Server/Oracle server is available in this
environment (or in most CI environments) to test a real connect()
against — these tests instead cover the one thing each connector is
actually responsible for beyond BaseDatabaseConnection's shared logic
(already covered against a real database in
tests/database/test_base_connection.py via DuckDB): building the
correct, dialect-specific SQLAlchemy URL from a ConnectionProfile.
"""

from __future__ import annotations

from src.database.connection_profile import ConnectionProfile, DatabaseType
from src.database.mysql_connection import MySqlConnection
from src.database.oracle_connection import OracleConnection
from src.database.postgres_connection import PostgresConnection
from src.database.sqlserver_connection import SqlServerConnection


def _profile(db_type: DatabaseType, **overrides) -> ConnectionProfile:
    defaults = dict(
        name="t", db_type=db_type, database="mydb", host="dbhost", username="alice"
    )
    defaults.update(overrides)
    return ConnectionProfile(**defaults)


def test_postgres_url_uses_psycopg2_and_default_port() -> None:
    connection = PostgresConnection(
        _profile(DatabaseType.POSTGRESQL), password="secret"
    )
    url = connection._build_connection_url()
    assert url.drivername == "postgresql+psycopg2"
    assert url.host == "dbhost"
    assert url.port == 5432
    assert url.username == "alice"
    assert url.password == "secret"
    assert url.database == "mydb"


def test_mysql_url_uses_pymysql_and_default_port() -> None:
    connection = MySqlConnection(_profile(DatabaseType.MYSQL), password="secret")
    url = connection._build_connection_url()
    assert url.drivername == "mysql+pymysql"
    assert url.port == 3306


def test_sqlserver_url_uses_pyodbc_and_names_a_driver() -> None:
    connection = SqlServerConnection(
        _profile(DatabaseType.SQL_SERVER), password="secret"
    )
    url = connection._build_connection_url()
    assert url.drivername == "mssql+pyodbc"
    assert url.port == 1433
    assert "driver" in url.query


def test_oracle_url_uses_oracledb_thin_mode_and_default_port() -> None:
    connection = OracleConnection(_profile(DatabaseType.ORACLE), password="secret")
    url = connection._build_connection_url()
    assert url.drivername == "oracle+oracledb"
    assert url.port == 1521


def test_explicit_port_overrides_the_default() -> None:
    connection = PostgresConnection(
        _profile(DatabaseType.POSTGRESQL, port=6543), password="secret"
    )
    url = connection._build_connection_url()
    assert url.port == 6543

# File: tests/database/test_connection_registry.py
"""Tests for src.database.connection_registry."""

from __future__ import annotations

import pytest

from src.core.exceptions import ServiceError
from src.database.connection_profile import DatabaseType
from src.database.connection_registry import get_connector_class, list_supported_types
from src.database.duckdb_connection import DuckDbConnection
from src.database.mysql_connection import MySqlConnection
from src.database.oracle_connection import OracleConnection
from src.database.postgres_connection import PostgresConnection
from src.database.sqlserver_connection import SqlServerConnection


def test_list_supported_types_covers_all_five_engines() -> None:
    assert set(list_supported_types()) == set(DatabaseType)


@pytest.mark.parametrize(
    ("db_type", "expected_class"),
    [
        (DatabaseType.POSTGRESQL, PostgresConnection),
        (DatabaseType.MYSQL, MySqlConnection),
        (DatabaseType.SQL_SERVER, SqlServerConnection),
        (DatabaseType.ORACLE, OracleConnection),
        (DatabaseType.DUCKDB, DuckDbConnection),
    ],
)
def test_get_connector_class_returns_the_right_class(db_type, expected_class) -> None:
    assert get_connector_class(db_type) is expected_class


def test_get_connector_class_unknown_type_raises() -> None:
    with pytest.raises(ServiceError):
        get_connector_class("not_a_real_db_type")  # type: ignore[arg-type]

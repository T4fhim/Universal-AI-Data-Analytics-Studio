# File: tests/database/test_connection_profile.py
"""Tests for src.database.connection_profile.ConnectionProfile/DatabaseType.

Covers the to_dict()/from_dict() round trip that
src.services.database_connection_service.DatabaseConnectionService
relies on to persist profiles through config.yaml, and confirms no
password field exists anywhere on the dataclass (see that class's own
docstring for why this is a deliberate security property, not an
oversight).
"""

from __future__ import annotations

import dataclasses

import pytest

from src.database.connection_profile import (
    DEFAULT_PORTS,
    ConnectionProfile,
    DatabaseType,
)


def test_connection_profile_has_no_password_field() -> None:
    field_names = {f.name for f in dataclasses.fields(ConnectionProfile)}
    assert "password" not in field_names


def test_to_dict_round_trips_through_from_dict() -> None:
    profile = ConnectionProfile(
        name="Prod Postgres",
        db_type=DatabaseType.POSTGRESQL,
        database="mydb",
        host="db.example.com",
        port=5433,
        username="alice",
    )

    restored = ConnectionProfile.from_dict(profile.to_dict())

    assert restored == profile


def test_to_dict_never_contains_a_password_key() -> None:
    profile = ConnectionProfile(
        name="t", db_type=DatabaseType.MYSQL, database="d", host="h", username="u"
    )
    assert "password" not in profile.to_dict()


@pytest.mark.parametrize(
    "db_type",
    [
        DatabaseType.POSTGRESQL,
        DatabaseType.MYSQL,
        DatabaseType.SQL_SERVER,
        DatabaseType.ORACLE,
    ],
)
def test_resolved_port_falls_back_to_default(db_type: DatabaseType) -> None:
    profile = ConnectionProfile(name="t", db_type=db_type, database="d")
    assert profile.resolved_port() == DEFAULT_PORTS[db_type]


def test_resolved_port_prefers_explicit_port() -> None:
    profile = ConnectionProfile(
        name="t", db_type=DatabaseType.POSTGRESQL, database="d", port=9999
    )
    assert profile.resolved_port() == 9999


def test_duckdb_has_no_default_port() -> None:
    profile = ConnectionProfile(
        name="t", db_type=DatabaseType.DUCKDB, database="local.duckdb"
    )
    assert profile.resolved_port() is None

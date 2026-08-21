# File: tests/services/test_database_connection_service.py
"""Tests for src.services.database_connection_service.DatabaseConnectionService.

Uses a real SettingsService backed by a tmp_path config.yaml (same
construction pattern src.core.bootstrap.bootstrap itself uses), so
save_profile()/list_profiles()/delete_profile() are tested against
real persistence, not a mock — and against a real DuckDB connection
for the live-connection half of this service, for the same "no mocked
SQL layer" reasoning as tests/database/test_base_connection.py.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.core.config import AppConfig, load_config
from src.core.exceptions import ServiceError
from src.database.connection_profile import ConnectionProfile, DatabaseType
from src.services.database_connection_service import DatabaseConnectionService
from src.services.settings_service import SettingsService


@pytest.fixture()
def settings_service(tmp_path: Path) -> SettingsService:
    config_path = tmp_path / "config.yaml"
    config = AppConfig.from_dict(load_config(config_path))
    return SettingsService(config, config_path)


@pytest.fixture()
def database_service(settings_service: SettingsService) -> DatabaseConnectionService:
    return DatabaseConnectionService(settings_service)


@pytest.fixture()
def duckdb_profile(tmp_path: Path) -> ConnectionProfile:
    db_path = tmp_path / "svc_test.duckdb"
    raw = duckdb.connect(str(db_path))
    raw.execute("CREATE TABLE t (x INTEGER)")
    raw.execute("INSERT INTO t VALUES (1), (2)")
    raw.close()
    return ConnectionProfile(
        name="svc-test", db_type=DatabaseType.DUCKDB, database=str(db_path)
    )


def test_list_profiles_starts_empty(
    database_service: DatabaseConnectionService,
) -> None:
    assert database_service.list_profiles() == []


def test_save_profile_persists_across_a_fresh_settings_service(
    database_service: DatabaseConnectionService,
    settings_service: SettingsService,
    tmp_path: Path,
) -> None:
    profile = ConnectionProfile(
        name="Prod",
        db_type=DatabaseType.POSTGRESQL,
        database="db",
        host="h",
        username="u",
    )
    database_service.save_profile(profile)

    reloaded_config = AppConfig.from_dict(load_config(tmp_path / "config.yaml"))
    reloaded_settings = SettingsService(reloaded_config, tmp_path / "config.yaml")
    reloaded_service = DatabaseConnectionService(reloaded_settings)

    profiles = reloaded_service.list_profiles()
    assert len(profiles) == 1
    assert profiles[0].name == "Prod"


def test_save_profile_twice_with_same_id_updates_not_duplicates(
    database_service: DatabaseConnectionService,
) -> None:
    profile = ConnectionProfile(
        name="Original",
        db_type=DatabaseType.MYSQL,
        database="db",
        host="h",
        username="u",
    )
    database_service.save_profile(profile)

    profile.name = "Renamed"
    database_service.save_profile(profile)

    profiles = database_service.list_profiles()
    assert len(profiles) == 1
    assert profiles[0].name == "Renamed"


def test_delete_profile_removes_it(database_service: DatabaseConnectionService) -> None:
    profile = ConnectionProfile(
        name="ToDelete", db_type=DatabaseType.MYSQL, database="db", host="h"
    )
    database_service.save_profile(profile)

    database_service.delete_profile(profile.profile_id)

    assert database_service.list_profiles() == []


def test_open_connection_and_get_connection(
    database_service: DatabaseConnectionService, duckdb_profile: ConnectionProfile
) -> None:
    connection = database_service.open_connection(duckdb_profile)

    assert database_service.get_connection(duckdb_profile.profile_id) is connection
    assert connection.list_tables() == ["t"]


def test_get_connection_without_opening_raises(
    database_service: DatabaseConnectionService,
) -> None:
    with pytest.raises(ServiceError):
        database_service.get_connection("never-opened")


def test_close_connection_forgets_it(
    database_service: DatabaseConnectionService, duckdb_profile: ConnectionProfile
) -> None:
    database_service.open_connection(duckdb_profile)
    database_service.close_connection(duckdb_profile.profile_id)

    with pytest.raises(ServiceError):
        database_service.get_connection(duckdb_profile.profile_id)


def test_close_all_connections(
    database_service: DatabaseConnectionService, duckdb_profile: ConnectionProfile
) -> None:
    database_service.open_connection(duckdb_profile)
    database_service.close_all_connections()

    with pytest.raises(ServiceError):
        database_service.get_connection(duckdb_profile.profile_id)


def test_delete_profile_also_closes_its_live_connection(
    database_service: DatabaseConnectionService, duckdb_profile: ConnectionProfile
) -> None:
    database_service.open_connection(duckdb_profile)
    database_service.delete_profile(duckdb_profile.profile_id)

    with pytest.raises(ServiceError):
        database_service.get_connection(duckdb_profile.profile_id)

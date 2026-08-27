# File: src/database/connection_registry.py
"""Maps DatabaseType -> connector class.

Mirrors :mod:`src.visualization.chart_registry`/:mod:`src.cleaning.
operation_registry`'s shape (a single source of truth a UI/service
layer looks up by key) but is deliberately much smaller and read-only
— five fixed connectors, no ``register_*``/``unregister_*`` plugin
extension points. Unlike report exporters (see :mod:`src.services.
report_service`'s own reasoning for the same omission) or cleaning
operations, a database connector is not something this project expects
third-party plugins to add: :data:`~src.plugins.plugin_manifest.
SUPPORTED_CATEGORIES` has no ``"database_connectors"`` entry, and
adding one is out of this milestone's scope.
"""

from __future__ import annotations

from src.core.exceptions import ServiceError
from src.database.base_connection import BaseDatabaseConnection
from src.database.connection_profile import DatabaseType
from src.database.duckdb_connection import DuckDbConnection
from src.database.mysql_connection import MySqlConnection
from src.database.oracle_connection import OracleConnection
from src.database.postgres_connection import PostgresConnection
from src.database.sqlserver_connection import SqlServerConnection

_CONNECTORS: dict[DatabaseType, type[BaseDatabaseConnection]] = {
    DatabaseType.POSTGRESQL: PostgresConnection,
    DatabaseType.MYSQL: MySqlConnection,
    DatabaseType.SQL_SERVER: SqlServerConnection,
    DatabaseType.ORACLE: OracleConnection,
    DatabaseType.DUCKDB: DuckDbConnection,
}


def get_connector_class(db_type: DatabaseType) -> type[BaseDatabaseConnection]:
    """Return the connector class for ``db_type``.

    Raises:
        ServiceError: If ``db_type`` has no registered connector — in
            practice unreachable through normal use, since
            :class:`~src.database.connection_profile.DatabaseType` and
            this mapping are defined together and kept in sync by
            construction, but checked explicitly rather than trusting
            a bare ``KeyError`` to be self-explanatory to a caller.
    """
    connector_class = _CONNECTORS.get(db_type)
    if connector_class is None:
        # db_type may not even be a genuine DatabaseType member here (a
        # caller could pass a plain string) — str(db_type) rather than
        # db_type.value so this error message itself can't raise a
        # second, more confusing AttributeError on the way to
        # reporting the first problem.
        raise ServiceError(f"No connector registered for database type: {db_type!r}.")
    return connector_class


def list_supported_types() -> list[DatabaseType]:
    """Return every supported :class:`~src.database.connection_profile.DatabaseType`, in a fixed order."""
    return list(_CONNECTORS.keys())

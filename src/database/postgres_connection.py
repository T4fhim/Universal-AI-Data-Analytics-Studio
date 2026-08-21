# File: src/database/postgres_connection.py
"""Connects to a PostgreSQL server.

Requires the ``psycopg2-binary`` package (a real, separate runtime
dependency this connector's SQLAlchemy URL names explicitly via
``+psycopg2`` — see :mod:`src.database.base_connection`'s ``connect``
for how a missing driver surfaces as a clear ``ServiceError`` rather
than a bare ``ModuleNotFoundError`` from deep inside SQLAlchemy).
"""

from __future__ import annotations

import sqlalchemy

from src.database.base_connection import BaseDatabaseConnection
from src.database.connection_profile import DEFAULT_PORTS, DatabaseType


class PostgresConnection(BaseDatabaseConnection):
    """Connects to a PostgreSQL database via the ``psycopg2`` driver."""

    def _build_connection_url(self) -> sqlalchemy.URL:
        return sqlalchemy.URL.create(
            "postgresql+psycopg2",
            username=self._profile.username or None,
            password=self._password or None,
            host=self._profile.host,
            port=self._profile.resolved_port()
            or DEFAULT_PORTS[DatabaseType.POSTGRESQL],
            database=self._profile.database,
        )

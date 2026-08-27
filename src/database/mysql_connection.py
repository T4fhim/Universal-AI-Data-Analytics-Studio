# File: src/database/mysql_connection.py
"""Connects to a MySQL (or MySQL-compatible, e.g. MariaDB) server.

Requires the ``pymysql`` package — see
:mod:`src.database.postgres_connection`'s own docstring for why each
connector names its specific driver rather than leaving SQLAlchemy to
guess one.
"""

from __future__ import annotations

import sqlalchemy

from src.database.base_connection import BaseDatabaseConnection
from src.database.connection_profile import DEFAULT_PORTS, DatabaseType


class MySqlConnection(BaseDatabaseConnection):
    """Connects to a MySQL database via the ``pymysql`` driver."""

    def _build_connection_url(self) -> sqlalchemy.URL:
        return sqlalchemy.URL.create(
            "mysql+pymysql",
            username=self._profile.username or None,
            password=self._password or None,
            host=self._profile.host,
            port=self._profile.resolved_port() or DEFAULT_PORTS[DatabaseType.MYSQL],
            database=self._profile.database,
        )

# File: src/database/oracle_connection.py
"""Connects to an Oracle database.

Requires the ``oracledb`` package, used in its default "thin" mode
(pure Python, no separate Oracle Instant Client install required) —
deliberately not ``cx_Oracle`` (its predecessor, which does require a
native Oracle Client installation) specifically so this connector
works out of the box wherever this project's other dependencies do,
without an extra platform-specific install step the milestone plan
never asked for.
"""

from __future__ import annotations

import sqlalchemy

from src.database.base_connection import BaseDatabaseConnection
from src.database.connection_profile import DEFAULT_PORTS, DatabaseType


class OracleConnection(BaseDatabaseConnection):
    """Connects to an Oracle database via the ``oracledb`` driver (thin mode)."""

    def _build_connection_url(self) -> sqlalchemy.URL:
        return sqlalchemy.URL.create(
            "oracle+oracledb",
            username=self._profile.username or None,
            password=self._password or None,
            host=self._profile.host,
            port=self._profile.resolved_port() or DEFAULT_PORTS[DatabaseType.ORACLE],
            database=self._profile.database,
        )

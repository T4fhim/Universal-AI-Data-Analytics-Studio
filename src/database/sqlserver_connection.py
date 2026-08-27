# File: src/database/sqlserver_connection.py
"""Connects to a Microsoft SQL Server instance.

Requires the ``pyodbc`` package *and* a system-level ODBC driver (e.g.
"ODBC Driver 17/18 for SQL Server") to actually be installed on the
machine running this application — unlike this package's other three
server connectors, ``pyodbc`` alone is not sufficient, since it is
itself a thin wrapper over the operating system's ODBC driver manager.
A machine without that system driver installed will fail at
:meth:`~src.database.base_connection.BaseDatabaseConnection.connect`
time with a ``ServiceError`` naming the missing driver, not at import
time — this connector cannot detect that gap any earlier than
SQLAlchemy/pyodbc themselves do.

Deliberately does **not** set ``TrustServerCertificate=yes``. ODBC
Driver 18's default (``Encrypt=yes``, certificate validated against a
trusted CA) is the secure default this connector leaves in place — an
earlier draft set ``TrustServerCertificate=yes`` unconditionally to
make self-signed-certificate dev/test servers connect without a
config-time detour, but a security review of this milestone correctly
flagged that as silently disabling TLS certificate verification for
*every* connection, including production ones, which is a real
man-in-the-middle exposure a user has no way to opt back out of. A
server with a self-signed certificate will now fail to connect with a
clear certificate-validation error instead of connecting insecurely by
default; making trust-the-certificate a per-profile, explicit opt-in
is a reasonable future enhancement, not something this milestone
should default silently.
"""

from __future__ import annotations

import sqlalchemy

from src.database.base_connection import BaseDatabaseConnection
from src.database.connection_profile import DEFAULT_PORTS, DatabaseType

# The most common driver name across current Windows/Linux SQL Server
# ODBC installations. If a specific environment has a differently
# named driver installed, a future enhancement would need to make this
# configurable per profile — out of scope for this milestone, which
# targets the common case.
_ODBC_DRIVER_NAME = "ODBC Driver 18 for SQL Server"


class SqlServerConnection(BaseDatabaseConnection):
    """Connects to SQL Server via the ``pyodbc`` driver."""

    def _build_connection_url(self) -> sqlalchemy.URL:
        return sqlalchemy.URL.create(
            "mssql+pyodbc",
            username=self._profile.username or None,
            password=self._password or None,
            host=self._profile.host,
            port=self._profile.resolved_port()
            or DEFAULT_PORTS[DatabaseType.SQL_SERVER],
            database=self._profile.database,
            query={"driver": _ODBC_DRIVER_NAME},
        )

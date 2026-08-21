# File: src/database/connection_profile.py
"""The persisted, credential-free shape of a saved database connection.

:class:`ConnectionProfile` deliberately has no password field — see
its own docstring for the full reasoning, and
:mod:`src.services.database_connection_service` for where a password
actually lives (in-memory only, for the current session). This module
has no other behavior; it exists so
:mod:`src.core.config` (which stores a list of these, serialized to
plain dicts, under ``database.profiles``) and
:mod:`src.database.connection_registry`/every concrete connector both
depend on the same small shape rather than each defining their own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DatabaseType(str, Enum):
    """Which database engine a :class:`ConnectionProfile` connects to.

    Subclasses ``str`` for the same reason
    :class:`~src.core.expertise_level.ExpertiseLevel` does: a member
    compares equal to and serializes as its plain string value, so
    ``database.profiles[i].db_type`` round-trips through YAML with no
    manual conversion at the config boundary.
    """

    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQL_SERVER = "sql_server"
    ORACLE = "oracle"
    DUCKDB = "duckdb"


# Default TCP port per engine, used to pre-fill the "Connect to
# Database" dialog's port field and as ConnectionProfile.port's
# fallback when a caller constructs one without specifying a port.
# DuckDB has no entry — it is an embedded, file-based engine with no
# network port at all (see DuckDbConnection's own docstring).
DEFAULT_PORTS: dict[DatabaseType, int] = {
    DatabaseType.POSTGRESQL: 5432,
    DatabaseType.MYSQL: 3306,
    DatabaseType.SQL_SERVER: 1433,
    DatabaseType.ORACLE: 1521,
}


@dataclass
class ConnectionProfile:
    """A saved database connection's non-secret metadata.

    Attributes:
        name: User-facing label, e.g. ``"Production Postgres"``.
        db_type: Which engine to connect to.
        host: Server hostname/IP. Ignored by
            :class:`~src.database.duckdb_connection.DuckDbConnection`,
            which uses ``database`` as a file path instead (see that
            class's own docstring).
        port: TCP port. ``None`` uses :data:`DEFAULT_PORTS` for
            ``db_type`` at connection time.
        database: Database/schema name for server engines, or a file
            path for DuckDB.
        username: Login username. Ignored by DuckDB (file-based, no
            authentication concept).
        profile_id: Unique identifier within the current session/saved
            list. Generated automatically if not supplied.

    Deliberately has **no password field**. A saved profile records
    everything needed to *offer* a reconnect ("Production Postgres,
    host db.example.com, user analyst") without ever writing a secret
    into ``config.yaml``, which
    :class:`~src.services.settings_service.SettingsService` persists as
    plain, unencrypted YAML — the same file the milestone 14 plan text
    flags for a security-reviewer pass specifically because of
    credential handling. The password the user types into the
    "Connect to Database" dialog is passed straight to
    :meth:`~src.database.base_connection.BaseDatabaseConnection.connect`
    and held only in
    :class:`~src.services.database_connection_service.
    DatabaseConnectionService`'s in-memory session state; reconnecting
    after an application restart means re-entering it, by design. This
    project has no keyring/OS-credential-store dependency to build a
    more convenient option on top of, and inventing an encrypted
    on-disk store for this milestone was judged a materially bigger,
    separately-reviewable feature rather than something to improvise
    here — "never persisted" is the safe default in the absence of
    that infrastructure, not a placeholder for it.
    """

    name: str
    db_type: DatabaseType
    database: str
    host: str = ""
    port: int | None = None
    username: str = ""
    profile_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON/YAML-friendly dict — the shape stored in ``config.yaml``."""
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "db_type": self.db_type.value,
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectionProfile:
        return cls(
            profile_id=data.get("profile_id") or str(uuid.uuid4()),
            name=data["name"],
            db_type=DatabaseType(data["db_type"]),
            host=data.get("host", ""),
            port=data.get("port"),
            database=data["database"],
            username=data.get("username", ""),
        )

    def resolved_port(self) -> int | None:
        """Return :attr:`port`, or this profile's ``db_type`` default if not explicitly set."""
        if self.port is not None:
            return self.port
        return DEFAULT_PORTS.get(self.db_type)

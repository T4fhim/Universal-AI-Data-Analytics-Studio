# File: src/database/duckdb_connection.py
"""Connects to a DuckDB database file.

The one connector in this package for an embedded, file-based engine
rather than a client-server one — ``profile.database`` is a filesystem
path (or ``:memory:`` for an ephemeral in-process database), not a
server-side database name, and ``profile.host``/``port``/``username``/
the connector's own ``password`` argument are all ignored, since
DuckDB has no network layer or authentication concept to configure.
Uses the ``duckdb_engine`` SQLAlchemy dialect (built on ``duckdb``,
already a project dependency) so this connector still goes through
:class:`~src.database.base_connection.BaseDatabaseConnection`'s shared
``list_tables``/``read_table``/``execute_query`` implementation like
every other connector, rather than calling the ``duckdb`` package
directly.
"""

from __future__ import annotations

from src.database.base_connection import BaseDatabaseConnection


class DuckDbConnection(BaseDatabaseConnection):
    """Connects to a DuckDB file at ``profile.database``."""

    def _build_connection_url(self) -> str:
        return f"duckdb:///{self._profile.database}"

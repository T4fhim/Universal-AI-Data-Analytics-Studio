# File: src/database/base_connection.py
"""The shared interface every database connector implements.

:class:`BaseDatabaseConnection` is this project's second deliberate
exception to the ``Base*`` stateless-classmethod pattern (see
:mod:`src.database`'s own docstring) — the first being
:class:`~src.ai.llm_provider.BaseLLMProvider`, which this class
mirrors closely in shape: both hold a real, live connection object
constructed in ``__init__``/opened by an explicit method, both
translate a project-specific request (a chat turn; a table read) into
their backend's own wire format, and both exist so the layer above
(:class:`~src.ai.assistant_service.AssistantService`;
:mod:`src.database.database_reader`) never branches on which concrete
backend is active.

Every concrete connector builds a SQLAlchemy engine — SQLAlchemy
already abstracts the SQL dialect differences between PostgreSQL/
MySQL/SQL Server/Oracle, so this base class implements
:meth:`list_tables`/:meth:`read_table`/:meth:`execute_query` once,
generically, over ``sqlalchemy.Engine`` + ``sqlalchemy.inspect``, and
each concrete subclass's only real job is building the right
connection URL and requiring the right optional DBAPI driver package
(see each subclass's own docstring for which). :class:`~src.database.
duckdb_connection.DuckDbConnection` is the one exception — DuckDB is
embedded/file-based, not a client-server engine — but even it reuses
this same SQLAlchemy-backed base rather than a separate code path,
since ``duckdb_engine`` (DuckDB's own SQLAlchemy dialect) fits the
same shape.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

import pandas as pd
import sqlalchemy

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.database.connection_profile import ConnectionProfile

_logger = get_logger(__name__)

# Matches a password embedded in a connection-string-shaped substring,
# e.g. "postgresql://user:hunter2@host/db" or "password=hunter2" —
# some DBAPI drivers (found by inspection of exception text raised by
# psycopg2/pymysql/pyodbc/oracledb on a failed connection) include the
# full DSN they attempted in their own error message. Every exception
# this module surfaces to a caller (and from there, potentially
# straight into a QMessageBox — see
# src.ui.dialogs.connect_database_dialog) is passed through
# _redact_credentials() first, so a driver's own verbose error text can
# never leak a password onto the user's screen or into a log file.
_CREDENTIAL_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # scheme://user:PASSWORD@host -> scheme://user:***@host
    (re.compile(r"(://[^:/@]+:)[^@/]+(@)"), r"\1***\2"),
    # password=PASSWORD -> password=*** (also covers ODBC's pwd=)
    (re.compile(r"((?:^|[;&?\s])p(?:assword|wd)=)[^;&\s]+", re.IGNORECASE), r"\1***"),
)


def _redact_credentials(text: str) -> str:
    """Strip anything that looks like an embedded password out of ``text``."""
    redacted = text
    for pattern, replacement in _CREDENTIAL_SUBSTITUTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


# Row cap applied to every read_table()/execute_query() call unless a
# caller explicitly raises it. A live database table can be far larger
# than anything this application should pull into an in-memory pandas
# DataFrame in one call — unlike a file-based reader, where the file
# itself is a natural, already-bounded unit of work, a query against a
# production database has no such bound by default. Callers that
# genuinely need more can pass a larger row_limit explicitly.
DEFAULT_ROW_LIMIT = 100_000


class BaseDatabaseConnection(ABC):
    """Abstract base class every concrete database connector inherits from.

    Args:
        profile: The connection's non-secret metadata (host, port,
            database, username). See
            :class:`~src.database.connection_profile.ConnectionProfile`
            for why this deliberately excludes the password.
        password: The password to authenticate with, held only for the
            lifetime of this object — never written back to
            ``profile`` or anywhere else. Ignored by
            :class:`~src.database.duckdb_connection.DuckDbConnection`
            (file-based, no authentication).
    """

    def __init__(self, profile: ConnectionProfile, password: str = "") -> None:
        self._profile = profile
        self._password = password
        self._engine: sqlalchemy.Engine | None = None

    @property
    def profile(self) -> ConnectionProfile:
        return self._profile

    @abstractmethod
    def _build_connection_url(self) -> str | sqlalchemy.URL:
        """Return the SQLAlchemy connection URL for this connector's engine.

        The one method every concrete connector must implement — the
        entire dialect-specific difference between connectors lives
        here; everything else in this base class is generic once a
        URL exists.
        """
        raise NotImplementedError

    def connect(self) -> None:
        """Open the underlying engine, creating a real connection pool.

        Idempotent: calling this again on an already-connected instance
        replaces the existing engine rather than erroring, matching
        :meth:`~src.ai.llm_provider.BaseLLMProvider`'s own tolerance
        for being reconfigured. Does not itself verify the server is
        reachable — SQLAlchemy engines are lazy — see
        :meth:`test_connection` for an explicit reachability check.

        Raises:
            ServiceError: If the connection URL cannot be built (e.g. a
                required field missing from ``profile``) or the
                required DBAPI driver package is not installed.
        """
        try:
            url = self._build_connection_url()
            self._engine = sqlalchemy.create_engine(url)
        except ModuleNotFoundError as exc:
            raise ServiceError(
                f"Cannot connect to {self._profile.db_type.value}: a "
                f"required driver package is not installed ({exc})."
            ) from exc
        except Exception as exc:
            raise ServiceError(
                f"Failed to configure connection '{self._profile.name}': "
                f"{_redact_credentials(str(exc))}"
            ) from exc
        _logger.info(
            "Configured %s connection '%s'.",
            self._profile.db_type.value,
            self._profile.name,
        )

    def test_connection(self) -> bool:
        """Attempt a real round-trip to the server and return whether it succeeded.

        Calls :meth:`connect` first if not already connected. Unlike
        :meth:`connect` (which never actually talks to the server —
        SQLAlchemy engines are lazy), this issues ``SELECT 1`` and
        genuinely exercises the network/authentication path, which is
        what a "Test Connection" button in the UI needs.

        Raises:
            ServiceError: If the connection cannot be established (bad
                host/port/credentials, server unreachable, or the
                required driver is missing).
        """
        if self._engine is None:
            self.connect()
        assert self._engine is not None  # connect() always sets this or raises

        try:
            with self._engine.connect() as connection:
                connection.execute(sqlalchemy.text("SELECT 1"))
        except Exception as exc:
            raise ServiceError(
                f"Could not connect to '{self._profile.name}' "
                f"({self._profile.db_type.value}): {_redact_credentials(str(exc))}"
            ) from exc
        return True

    def list_tables(self) -> list[str]:
        """Return the names of tables visible to this connection.

        Raises:
            ServiceError: If not connected, or the server rejects the
                introspection query.
        """
        if self._engine is None:
            self.connect()
        assert self._engine is not None

        try:
            inspector = sqlalchemy.inspect(self._engine)
            return list(inspector.get_table_names())
        except Exception as exc:
            raise ServiceError(
                f"Failed to list tables for '{self._profile.name}': "
                f"{_redact_credentials(str(exc))}"
            ) from exc

    def read_table(
        self, table_name: str, row_limit: int = DEFAULT_ROW_LIMIT
    ) -> pd.DataFrame:
        """Read up to ``row_limit`` rows from ``table_name``.

        Args:
            table_name: Which table to read — must be one of the names
                :meth:`list_tables` returns; not otherwise validated
                here, since the underlying SQL error for an unknown
                table name is already a clear, specific message.
            row_limit: Maximum rows to return. See :data:`DEFAULT_ROW_LIMIT`'s
                own docstring for why this exists.

        Raises:
            ServiceError: If not connected, ``table_name`` does not
                exist, or the query otherwise fails.
        """
        # Table identifiers cannot be bound as query parameters in
        # standard SQL (parameters are for values, not identifiers) —
        # quote_identifier applies each dialect's own quoting rules so
        # a table name containing spaces or reserved words is handled
        # correctly without string-formatting raw user input directly
        # into the SQL text.
        if self._engine is None:
            self.connect()
        assert self._engine is not None

        quoted_name = self._engine.dialect.identifier_preparer.quote_identifier(
            table_name
        )
        query = sqlalchemy.text(f"SELECT * FROM {quoted_name} LIMIT :row_limit")
        try:
            return pd.read_sql_query(
                query, self._engine, params={"row_limit": row_limit}
            )
        except Exception as exc:
            raise ServiceError(
                f"Failed to read table '{table_name}' from "
                f"'{self._profile.name}': {_redact_credentials(str(exc))}"
            ) from exc

    def execute_query(
        self, sql: str, row_limit: int = DEFAULT_ROW_LIMIT
    ) -> pd.DataFrame:
        """Run an arbitrary read query and return its result as a DataFrame.

        Args:
            sql: The SQL query text, supplied by the user through the
                "Connect to Database" dialog (or, in the future, an AI
                tool call) — run as-is, with no row-limiting clause
                injected into the query text itself, since doing so
                would require dialect-specific SQL rewriting (``LIMIT``
                vs ``TOP`` vs ``FETCH FIRST``) that is easy to get
                subtly wrong. ``row_limit`` instead bounds how many
                *result* rows this method reads back into memory via
                ``pandas.read_sql_query``'s own chunking, which is
                dialect-agnostic.
            row_limit: Maximum rows to read back from the result.

        Raises:
            ServiceError: If not connected or the query fails (syntax
                error, permission denied, etc. — the underlying
                database's own error message is preserved).
        """
        if self._engine is None:
            self.connect()
        assert self._engine is not None

        try:
            chunks = pd.read_sql_query(
                sqlalchemy.text(sql), self._engine, chunksize=row_limit
            )
            return next(iter(chunks), pd.DataFrame())
        except Exception as exc:
            raise ServiceError(
                f"Query failed against '{self._profile.name}': "
                f"{_redact_credentials(str(exc))}"
            ) from exc

    def close(self) -> None:
        """Dispose of the underlying engine's connection pool, if one was opened."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            _logger.info("Closed connection '%s'.", self._profile.name)

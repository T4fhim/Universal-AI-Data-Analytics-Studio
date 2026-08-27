# File: src/database/database_reader.py
"""Turns a live database connection's table/query result into a Dataset.

Deliberately does **not** subclass :class:`~src.readers.base_reader.
BaseReader`, despite the milestone plan text describing it as
"``DatabaseReader(BaseReader)``". ``BaseReader``'s entire contract —
``can_read(path)``, ``list_tables(path)``, ``read(path, table_name)``
— is built around a filesystem ``Path`` as the one thing every reader
dispatches on (see :mod:`src.readers.reader_registry.
get_reader_for_path`); a live database connection has no path at all.
Forcing this class into that shape would mean a ``can_read`` that
always returns ``False`` (nothing will ever dispatch to it through
:func:`~src.readers.reader_registry.get_reader_for_path`) and a
``read`` whose ``path`` parameter is meaningless and whose real inputs
would have to travel through ``**kwargs`` instead — worse, not better,
than being honest that this is a different kind of data source with
its own two-method shape (:meth:`read_table`/:meth:`read_query`),
consistent with :class:`~src.database.base_connection.
BaseDatabaseConnection` itself already being a documented departure
from the ``Base*`` pattern for the same underlying reason (see that
module's own docstring). It still produces the exact same
:class:`~src.services.workspace_service.Dataset` shape every real
reader does and raises the same :class:`~src.core.exceptions.
ReaderError` on failure, so a dataset loaded this way is
indistinguishable to the rest of the application (Dataset Explorer,
cleaning, analysis, reporting) from one loaded via
:mod:`src.readers`.
"""

from __future__ import annotations

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.database.base_connection import BaseDatabaseConnection
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)


class DatabaseReader:
    """Reads a table or an arbitrary query result from a live database connection."""

    @classmethod
    def read_table(cls, connection: BaseDatabaseConnection, table_name: str) -> Dataset:
        """Read ``table_name`` from ``connection`` into a Dataset.

        Args:
            connection: An already-constructed (not necessarily yet
                connected — this calls methods that connect lazily)
                :class:`~src.database.base_connection.
                BaseDatabaseConnection`.
            table_name: Which table to read, e.g. from
                :meth:`~src.database.base_connection.
                BaseDatabaseConnection.list_tables`.

        Raises:
            ReaderError: If the table cannot be read (propagated from
                the connection's own :class:`~src.core.exceptions.
                ServiceError`, re-raised as ``ReaderError`` so this
                reader's failures are catchable the same way every
                file-based reader's are).
        """
        try:
            dataframe = connection.read_table(table_name)
        except Exception as exc:
            raise ReaderError(
                f"Failed to read table '{table_name}' from "
                f"'{connection.profile.name}': {exc}"
            ) from exc

        _logger.info(
            "Read database table '%s' from '%s': %d rows, %d columns.",
            table_name,
            connection.profile.name,
            len(dataframe),
            len(dataframe.columns),
        )

        return Dataset(
            name=f"{connection.profile.name} — {table_name}",
            dataframe=dataframe,
            source_format=f"database:{connection.profile.db_type.value}",
        )

    @classmethod
    def read_query(
        cls, connection: BaseDatabaseConnection, sql: str, name: str | None = None
    ) -> Dataset:
        """Run ``sql`` against ``connection`` and return its result as a Dataset.

        Args:
            connection: An already-constructed connection.
            sql: The query text to run — see
                :meth:`~src.database.base_connection.
                BaseDatabaseConnection.execute_query`'s own docstring
                for how row-limiting is handled.
            name: Display name for the resulting Dataset. Defaults to
                ``"<connection name> — query"``.

        Raises:
            ReaderError: If the query fails.
        """
        try:
            dataframe = connection.execute_query(sql)
        except Exception as exc:
            raise ReaderError(
                f"Query against '{connection.profile.name}' failed: {exc}"
            ) from exc

        _logger.info(
            "Ran query against '%s': %d rows, %d columns.",
            connection.profile.name,
            len(dataframe),
            len(dataframe.columns),
        )

        return Dataset(
            name=name or f"{connection.profile.name} — query",
            dataframe=dataframe,
            source_format=f"database:{connection.profile.db_type.value}",
        )

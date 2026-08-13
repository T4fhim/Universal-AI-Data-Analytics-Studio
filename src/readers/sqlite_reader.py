# File: src/readers/sqlite_reader.py
"""Reads tables from a SQLite database file into a Dataset.

:class:`SqliteReader` is this project's second multi-table reader — a
SQLite database file can contain any number of tables, each a
candidate for :meth:`~src.readers.base_reader.BaseReader.list_tables`
and :meth:`~src.readers.base_reader.BaseReader.read`'s ``table_name``
argument, following the same contract
:class:`~src.readers.excel_reader.ExcelReader` implements for Excel
worksheets.

Uses the standard library's ``sqlite3`` module directly for
introspection (listing tables) and ``pandas.read_sql_query`` for the
actual data read — ``sqlite3`` needs no separate installation, and
using it directly for the lightweight "what tables exist" question
avoids pulling in SQLAlchemy (already a project dependency, per the
technologies list, but heavier machinery than a single ``sqlite_master``
query needs).

One SQLite-specific situation this reader handles explicitly:
**dynamic typing**. Unlike most SQL databases, SQLite does not strictly
enforce a column's declared type — a column declared ``INTEGER`` can
still hold a text value in a given row, a behavior SQLite calls "type
affinity" rather than strict typing. This is exactly the same
*symptom* (a column ending up with mixed value types) that
:func:`~src.readers.type_inference.find_ambiguous_type_columns`
already detects for CSV files, so this reader calls that same shared
function rather than re-implementing equivalent logic independently —
see that function's own docstring for the detection approach and its
documented history of two rounds of fixes during milestone 2a's
testing.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.readers.type_inference import find_ambiguous_type_columns
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}

# SQLite's own reserved system table, present in every SQLite
# database. Never a candidate "table" from a user's perspective —
# always excluded from list_tables' results.
_SQLITE_SYSTEM_TABLE = "sqlite_sequence"


class SqliteReader(BaseReader):
    """Reads tables from a SQLite database file, one table per read."""

    SUPPORTED_EXTENSIONS = _SQLITE_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _SQLITE_EXTENSIONS

    @classmethod
    def list_tables(cls, path: Path) -> list[str]:
        """Return the names of user tables in the SQLite database at ``path``.

        Excludes SQLite's own internal ``sqlite_sequence`` table (see
        :data:`_SQLITE_SYSTEM_TABLE`), which exists in most SQLite
        databases as bookkeeping for autoincrement columns and is
        never a table a user would want to load as a dataset.

        Raises:
            ReaderError: If the file does not exist, or cannot be
                opened as a SQLite database at all (not a SQLite file
                despite the extension, or a corrupted database file).
        """
        if not path.exists():
            raise ReaderError(f"SQLite database file does not exist: {path}")

        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                cursor = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
                table_names = [row[0] for row in cursor.fetchall()]
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise ReaderError(
                f"Failed to open {path} as a SQLite database: {exc}"
            ) from exc

        return [name for name in table_names if name != _SQLITE_SYSTEM_TABLE]

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read one table from the SQLite database at ``path``.

        Args:
            path: The database file to read.
            table_name: Which table to read, by name. If the database
                has exactly one user table, ``None`` reads it
                directly. If the database has more than one table and
                ``table_name`` is ``None``, this raises rather than
                guessing — call :meth:`list_tables` first and pass one
                of the returned names.

        Raises:
            ReaderError: If the file does not exist, cannot be opened
                as a SQLite database, has zero user tables, has more
                than one table but no ``table_name`` was given, or
                ``table_name`` does not match any table in the
                database.
        """
        available_tables = cls.list_tables(path)

        if not available_tables:
            raise ReaderError(
                f"{path} is a valid SQLite database but contains no "
                f"user tables to read."
            )

        if table_name is None:
            if len(available_tables) == 1:
                table_name = available_tables[0]
            else:
                raise ReaderError(
                    f"{path} contains {len(available_tables)} tables "
                    f"({', '.join(available_tables)}); specify which "
                    f"one to read via the table_name argument."
                )
        elif table_name not in available_tables:
            raise ReaderError(
                f"{path} has no table named '{table_name}'. Available "
                f"tables: {', '.join(available_tables)}."
            )

        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                # table_name is validated against available_tables
                # (itself sourced from sqlite_master, not user input)
                # immediately above, so this f-string is safe from SQL
                # injection despite not using a parameterized query —
                # SQL parameterization applies to *values*, not table
                # identifiers, and this project has no path by which
                # an arbitrary, unvalidated string reaches this point.
                dataframe = pd.read_sql_query(f"SELECT * FROM {table_name}", connection)
            finally:
                connection.close()
        except (sqlite3.Error, pd.errors.DatabaseError) as exc:
            raise ReaderError(
                f"Failed to read table '{table_name}' from {path}: {exc}"
            ) from exc

        warnings: list[str] = []
        ambiguous_columns = find_ambiguous_type_columns(dataframe)
        if ambiguous_columns:
            warnings.append(
                f"Column(s) with mixed types (a known SQLite behavior "
                f"— see this reader's module docstring for why): "
                f"{', '.join(ambiguous_columns)}."
            )

        _logger.info(
            "Read SQLite table '%s' from %s: %d rows, %d columns, "
            "%d warning(s).",
            table_name,
            path,
            len(dataframe),
            len(dataframe.columns),
            len(warnings),
        )

        return Dataset(
            name=f"{path.stem} — {table_name}" if len(available_tables) > 1 else path.stem,
            dataframe=dataframe,
            source_format="sqlite",
            source_path=path,
            read_warnings=warnings,
        )

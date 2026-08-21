# File: src/readers/html_reader.py
"""Reads ``<table>`` elements from an HTML file into a Dataset.

Multi-table, the same conceptual shape as
:class:`~src.readers.excel_reader.ExcelReader`, except the "tables"
here are whichever ``<table>`` elements ``pandas.read_html`` (backed by
``lxml``/``beautifulsoup4``, both already project dependencies) finds
in the document — an arbitrary HTML page can have zero, one, or many,
in no particular structure the way a workbook's sheet list has. Each
table's first row is assumed to be its header, matching
``pandas.read_html``'s own default and this project's existing
header-row convention elsewhere in :mod:`src.readers`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_HTML_EXTENSIONS = {".html", ".htm"}


class HtmlReader(BaseReader):
    """Reads every ``<table>`` element found in an .html/.htm file, one per read."""

    SUPPORTED_EXTENSIONS = _HTML_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _HTML_EXTENSIONS

    @classmethod
    def list_tables(cls, path: Path) -> list[str]:
        """Return one label per ``<table>`` found in the document, e.g. ``"Table 1"``.

        Raises:
            ReaderError: If the file does not exist, cannot be parsed
                as HTML, or contains no ``<table>`` elements at all.
        """
        tables = cls._parse_tables(path)
        return [f"Table {index}" for index in range(1, len(tables) + 1)]

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read one ``<table>`` from the HTML document at ``path``.

        Args:
            path: The file to read.
            table_name: Which table to read, by the label returned
                from :meth:`list_tables` (e.g. ``"Table 2"``). If the
                document has exactly one table, ``None`` reads it
                directly.

        Raises:
            ReaderError: If the file does not exist, cannot be parsed,
                has more than one table but no ``table_name`` was
                given, or ``table_name`` does not match any table
                found.
        """
        tables = cls._parse_tables(path)
        labels = [f"Table {index}" for index in range(1, len(tables) + 1)]

        if table_name is None:
            if len(tables) == 1:
                table_index = 0
            else:
                raise ReaderError(
                    f"{path} contains {len(tables)} table(s) "
                    f"({', '.join(labels)}); specify which one to read "
                    f"via the table_name argument."
                )
        elif table_name in labels:
            table_index = labels.index(table_name)
        else:
            raise ReaderError(
                f"{path} has no table labeled '{table_name}'. "
                f"Available tables: {', '.join(labels)}."
            )

        dataframe = tables[table_index]
        selected_label = labels[table_index]

        _logger.info(
            "Read HTML table '%s' from %s: %d rows, %d columns.",
            selected_label,
            path,
            len(dataframe),
            len(dataframe.columns),
        )

        return Dataset(
            name=f"{path.stem} — {selected_label}" if len(tables) > 1 else path.stem,
            dataframe=dataframe,
            source_format="html",
            source_path=path,
        )

    @classmethod
    def _parse_tables(cls, path: Path) -> list[pd.DataFrame]:
        if not path.exists():
            raise ReaderError(f"HTML file does not exist: {path}")

        try:
            tables = pd.read_html(path)
        except ValueError as exc:
            # pandas.read_html raises ValueError specifically when it
            # finds zero <table> elements — the common, expected "not a
            # data page" case, distinguished here from a genuine parse
            # failure so the resulting message says what actually
            # happened rather than a generic "failed to read."
            raise ReaderError(f"No tables found in {path}: {exc}") from exc
        except Exception as exc:
            raise ReaderError(f"Failed to parse HTML file {path}: {exc}") from exc

        return tables

# File: src/readers/ods_reader.py
"""Reads OpenDocument Spreadsheet (.ods) files into a Dataset.

Same multi-table shape as :class:`~src.readers.excel_reader.
ExcelReader` (one sheet per read) — the two formats differ only in
container format, not in the "workbook with one or more worksheets"
concept, so this reader reuses pandas' own ``read_excel``/``ExcelFile``
entry points with ``engine="odf"`` (backed by ``odfpy``, already a
project dependency) rather than reimplementing sheet enumeration.
Deliberately does not attempt :class:`ExcelReader`'s merged-cell
detection — that used ``openpyxl``, which cannot open ``.ods`` files at
all, and ODS's own merged-region API differs enough that duplicating
that detection here for a much less common format was judged not worth
the added surface area for this milestone.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_ODS_EXTENSIONS = {".ods"}


class OdsReader(BaseReader):
    """Reads .ods (OpenDocument Spreadsheet) workbooks, one sheet per read."""

    SUPPORTED_EXTENSIONS = _ODS_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _ODS_EXTENSIONS

    @classmethod
    def list_tables(cls, path: Path) -> list[str]:
        """Return the names of sheets in the ODS workbook at ``path``.

        Raises:
            ReaderError: If the file does not exist or cannot be
                opened as an ODS workbook.
        """
        if not path.exists():
            raise ReaderError(f"ODS file does not exist: {path}")

        try:
            ods_file = pd.ExcelFile(path, engine="odf")
        except Exception as exc:
            raise ReaderError(
                f"Failed to open {path} as an ODS workbook: {exc}"
            ) from exc

        return list(ods_file.sheet_names)

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read one sheet from the ODS workbook at ``path``.

        Args:
            path: The workbook to read.
            table_name: Which sheet to read, by name. See
                :meth:`~src.readers.excel_reader.ExcelReader.read`'s
                own docstring for the exact single-sheet/multi-sheet
                resolution rule — identical here.

        Raises:
            ReaderError: Same conditions as
                :meth:`~src.readers.excel_reader.ExcelReader.read`.
        """
        available_sheets = cls.list_tables(path)

        if table_name is None:
            if len(available_sheets) == 1:
                table_name = available_sheets[0]
            else:
                raise ReaderError(
                    f"{path} contains {len(available_sheets)} sheets "
                    f"({', '.join(available_sheets)}); specify which "
                    f"one to read via the table_name argument."
                )
        elif table_name not in available_sheets:
            raise ReaderError(
                f"{path} has no sheet named '{table_name}'. Available "
                f"sheets: {', '.join(available_sheets)}."
            )

        try:
            dataframe = pd.read_excel(path, sheet_name=table_name, engine="odf")
        except Exception as exc:
            raise ReaderError(
                f"Failed to read sheet '{table_name}' from {path}: {exc}"
            ) from exc

        _logger.info(
            "Read ODS sheet '%s' from %s: %d rows, %d columns.",
            table_name,
            path,
            len(dataframe),
            len(dataframe.columns),
        )

        return Dataset(
            name=(
                f"{path.stem} — {table_name}"
                if len(available_sheets) > 1
                else path.stem
            ),
            dataframe=dataframe,
            source_format="ods",
            source_path=path,
        )

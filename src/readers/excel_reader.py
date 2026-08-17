# File: src/readers/excel_reader.py
"""Reads Excel workbooks (.xlsx, .xls) into a Dataset.

:class:`ExcelReader` is this project's first multi-table reader — an
Excel workbook can contain more than one worksheet, each of which is a
candidate table in its own right. See
:mod:`src.readers.base_reader`'s module docstring for the general
multi-table contract (:meth:`~src.readers.base_reader.BaseReader.
list_tables`, the ``table_name`` parameter on
:meth:`~src.readers.base_reader.BaseReader.read`) this reader is the
first concrete implementation of.

Two Excel-specific situations this reader handles explicitly, both
found worth addressing by thinking through what real spreadsheets
actually look like (not just what a clean, minimal test file looks
like):

* **Merged cells.** In a merged cell block, Excel stores the value
  only in the top-left cell; every other cell in that block reads as
  empty. This is standard, intentional spreadsheet authoring — not
  corrupted data — but it produces a column or row of ``NaN`` values
  that could be mistaken for missing data if the user doesn't know the
  source had merged cells. This reader detects merged regions (via
  ``openpyxl``, which exposes them directly) and records a warning
  naming which are present, without attempting to "fix" the shape by
  forward-filling values into the empty cells — that would be a
  content-altering judgment call belonging to a data-cleaning
  milestone, not this reader.
* **Header row assumption.** This reader assumes row 1 of the selected
  sheet is the header row, matching pandas' own ``read_excel``
  default. Real spreadsheets sometimes have a title row, a blank row,
  or other content before the real header — detecting that
  automatically is a meaningfully harder problem than anything in
  milestone 2a (it requires heuristics about what a "real" header row
  looks like versus a title or note), and is explicitly out of scope
  here rather than solved with an unreliable guess. If the assumption
  is wrong for a given file, the resulting ``Dataset`` will have
  columns named after whatever was actually in row 1 (likely including
  ``Unnamed: 0``-style pandas defaults for blank cells) — this is
  honest, inspectable behavior rather than a silent misread, even
  though it isn't automatically corrected.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_EXCEL_EXTENSIONS = {".xlsx", ".xls"}


class ExcelReader(BaseReader):
    """Reads .xlsx and .xls workbooks, one sheet per read.

    ``.xlsx`` (and legacy ``.xls``, via the ``xlrd`` engine) are both
    supported — pandas' ``read_excel`` picks the correct engine
    automatically based on file content, not just the extension, so
    this reader does not need to select an engine itself.
    """

    SUPPORTED_EXTENSIONS = _EXCEL_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _EXCEL_EXTENSIONS

    @classmethod
    def list_tables(cls, path: Path) -> list[str]:
        """Return the names of worksheets in the workbook at ``path``.

        Raises:
            ReaderError: If the file does not exist or cannot be
                opened as an Excel workbook at all (corrupted file,
                wrong format despite the extension).
        """
        if not path.exists():
            raise ReaderError(f"Excel file does not exist: {path}")

        try:
            excel_file = pd.ExcelFile(path)
        except Exception as exc:
            raise ReaderError(
                f"Failed to open {path} as an Excel workbook: {exc}"
            ) from exc

        return list(excel_file.sheet_names)

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read one worksheet from the workbook at ``path``.

        Args:
            path: The workbook to read.
            table_name: Which worksheet to read, by name. If the
                workbook has exactly one worksheet, ``None`` reads it
                directly. If the workbook has more than one worksheet
                and ``table_name`` is ``None``, this raises rather
                than guessing — call :meth:`list_tables` first and
                pass one of the returned names.

        Raises:
            ReaderError: If the file does not exist, cannot be opened
                as an Excel workbook, has more than one sheet but no
                ``table_name`` was given, or ``table_name`` does not
                match any sheet in the workbook.
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
            dataframe = pd.read_excel(path, sheet_name=table_name)
        except Exception as exc:
            raise ReaderError(
                f"Failed to read sheet '{table_name}' from {path}: {exc}"
            ) from exc

        warnings: list[str] = []
        merged_ranges = cls._find_merged_ranges(path, table_name)
        if merged_ranges:
            warnings.append(
                f"This sheet contains {len(merged_ranges)} merged "
                f"cell region(s) (e.g. {merged_ranges[0]}). Cells "
                f"within a merged region other than its top-left "
                f"cell will appear empty in the loaded data — this "
                f"reflects how Excel stores merged cells, not "
                f"missing data."
            )

        _logger.info(
            "Read Excel sheet '%s' from %s: %d rows, %d columns, " "%d warning(s).",
            table_name,
            path,
            len(dataframe),
            len(dataframe.columns),
            len(warnings),
        )

        return Dataset(
            name=(
                f"{path.stem} — {table_name}"
                if len(available_sheets) > 1
                else path.stem
            ),
            dataframe=dataframe,
            source_format="xlsx" if path.suffix.lower() == ".xlsx" else "xls",
            source_path=path,
            read_warnings=warnings,
        )

    @classmethod
    def _find_merged_ranges(cls, path: Path, sheet_name: str) -> list[str]:
        """Return string representations of merged cell ranges in the given sheet.

        Uses ``openpyxl`` directly (rather than pandas, which does not
        expose merged-cell information) since ``openpyxl`` is already
        a hard dependency of this project. Returns an empty list for
        ``.xls`` files, which ``openpyxl`` cannot open (it handles
        only the modern ``.xlsx`` format) — a merged-cell warning for
        legacy ``.xls`` files is a real gap this reader does not
        currently close, judged acceptable given how uncommon new
        ``.xls`` files are, rather than adding a second, ``xlrd``-based
        merged-cell detection path solely to cover a shrinking legacy
        case.
        """
        if path.suffix.lower() != ".xlsx":
            return []

        try:
            workbook = openpyxl.load_workbook(path, read_only=False, data_only=True)
            worksheet = workbook[sheet_name]
            return [str(merged_range) for merged_range in worksheet.merged_cells.ranges]
        except Exception as exc:
            # Merged-cell detection is a "nice to know" warning, not a
            # correctness-critical read step — if it fails for any
            # reason (an unusual workbook structure openpyxl can't
            # introspect, for instance), the read itself should still
            # succeed via the pandas path above. Log at debug rather
            # than surface this as a warning to the user, since the
            # actual data was already read successfully by this point.
            _logger.debug(
                "Could not check for merged cells in %s sheet '%s': %s",
                path,
                sheet_name,
                exc,
            )
            return []

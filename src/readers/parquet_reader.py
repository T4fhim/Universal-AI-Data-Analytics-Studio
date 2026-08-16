# File: src/readers/parquet_reader.py
"""Reads Apache Parquet files into a Dataset.

Single-table, and unusually simple among this project's readers:
Parquet is a typed, columnar format with no encoding-detection or
delimiter-sniffing analog to :class:`~src.readers.csv_reader.
CsvReader`'s concerns, and no header-row ambiguity like
:class:`~src.readers.excel_reader.ExcelReader`'s — the file's own
embedded schema is authoritative. ``pandas.read_parquet`` picks
whichever of ``pyarrow``/``fastparquet`` (both already project
dependencies) is available automatically.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_PARQUET_EXTENSIONS = {".parquet"}


class ParquetReader(BaseReader):
    """Reads .parquet files."""

    SUPPORTED_EXTENSIONS = _PARQUET_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _PARQUET_EXTENSIONS

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read a Parquet file at ``path``.

        Args:
            path: The file to read.
            table_name: Ignored — a Parquet file is single-table.

        Raises:
            ReaderError: If the file does not exist or cannot be
                parsed as Parquet.
        """
        if not path.exists():
            raise ReaderError(f"Parquet file does not exist: {path}")

        try:
            dataframe = pd.read_parquet(path)
        except Exception as exc:
            raise ReaderError(f"Failed to read Parquet file {path}: {exc}") from exc

        _logger.info(
            "Read Parquet file %s: %d rows, %d columns.",
            path,
            len(dataframe),
            len(dataframe.columns),
        )

        return Dataset(
            name=path.stem,
            dataframe=dataframe,
            source_format="parquet",
            source_path=path,
        )

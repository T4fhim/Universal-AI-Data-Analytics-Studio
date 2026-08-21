# File: src/readers/feather_reader.py
"""Reads Apache Feather files into a Dataset.

Single-table, and as simple as :class:`~src.readers.parquet_reader.
ParquetReader` for the same reason — Feather is also a typed, columnar
format backed by ``pyarrow`` (already a project dependency) with an
authoritative embedded schema and no encoding/delimiter ambiguity to
resolve.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_FEATHER_EXTENSIONS = {".feather"}


class FeatherReader(BaseReader):
    """Reads .feather files."""

    SUPPORTED_EXTENSIONS = _FEATHER_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _FEATHER_EXTENSIONS

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read a Feather file at ``path``.

        Args:
            path: The file to read.
            table_name: Ignored — a Feather file is single-table.

        Raises:
            ReaderError: If the file does not exist or cannot be
                parsed as Feather.
        """
        if not path.exists():
            raise ReaderError(f"Feather file does not exist: {path}")

        try:
            dataframe = pd.read_feather(path)
        except Exception as exc:
            raise ReaderError(f"Failed to read Feather file {path}: {exc}") from exc

        _logger.info(
            "Read Feather file %s: %d rows, %d columns.",
            path,
            len(dataframe),
            len(dataframe.columns),
        )

        return Dataset(
            name=path.stem,
            dataframe=dataframe,
            source_format="feather",
            source_path=path,
        )

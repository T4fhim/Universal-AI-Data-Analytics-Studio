# File: src/readers/yaml_reader.py
"""Reads YAML files into a Dataset.

Single-table (a YAML document has no worksheet/sheet concept), same
shape as :class:`~src.readers.json_reader.JsonReader` for the same
underlying reason: both formats can encode either a list of flat
records (the common, directly tabular case) or a single nested
document (which pandas' ``json_normalize`` flattens rather than this
reader inventing its own flattening rules). Parsed with
``yaml.safe_load`` specifically, never ``yaml.load`` — the unsafe
loader can construct arbitrary Python objects from tags in the file
(a real code-execution risk for a file format this reader has to
accept from an untrusted source, i.e. whatever the user opens), and
``safe_load`` accepts every YAML construct a legitimate tabular export
would ever use.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_YAML_EXTENSIONS = {".yaml", ".yml"}


class YamlReader(BaseReader):
    """Reads .yaml/.yml files, the same way :class:`~src.readers.json_reader.JsonReader` reads JSON."""

    SUPPORTED_EXTENSIONS = _YAML_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _YAML_EXTENSIONS

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read a YAML file at ``path``.

        Args:
            path: The file to read.
            table_name: Accepted for interface uniformity (see
                :meth:`~src.readers.csv_reader.CsvReader.read`'s own
                docstring for why); ignored — a YAML file has exactly
                one document by this reader's definition.

        Raises:
            ReaderError: If the file does not exist, is empty, is not
                valid YAML, or its top-level structure is neither a
                list of records nor an object pandas can normalize
                into a table (e.g. a single scalar value).
        """
        if not path.exists():
            raise ReaderError(f"YAML file does not exist: {path}")
        if path.stat().st_size == 0:
            raise ReaderError(f"YAML file is empty: {path}")

        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ReaderError(f"Failed to parse YAML file {path}: {exc}") from exc

        if document is None:
            raise ReaderError(f"YAML file has no content: {path}")

        try:
            if isinstance(document, (list, dict)):
                dataframe = pd.json_normalize(document)
            else:
                raise ReaderError(
                    f"YAML file {path}'s top-level content is a "
                    f"{type(document).__name__}, not a list or mapping "
                    f"— cannot represent it as a table."
                )
        except ReaderError:
            raise
        except Exception as exc:
            raise ReaderError(
                f"Could not convert YAML content from {path} to a table: {exc}"
            ) from exc

        _logger.info(
            "Read YAML file %s: %d rows, %d columns.",
            path,
            len(dataframe),
            len(dataframe.columns),
        )

        return Dataset(
            name=path.stem,
            dataframe=dataframe,
            source_format="yaml",
            source_path=path,
        )

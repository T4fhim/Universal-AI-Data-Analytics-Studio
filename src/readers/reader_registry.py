# File: src/readers/reader_registry.py
"""Finds the right reader for a given file.

:func:`get_reader_for_path` is the one function most callers (the
future "Open Dataset" UI action, in particular) should use, rather
than importing individual readers and checking extensions themselves.
It exists so that adding a new reader in 2b or 2c means registering it
here once, not updating every call site that currently has to guess
which reader a given file needs.
"""

from __future__ import annotations

from pathlib import Path

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.readers.csv_reader import CsvReader
from src.readers.excel_reader import ExcelReader
from src.readers.image_reader import ImageReader
from src.readers.json_reader import JsonReader
from src.readers.pdf_reader import PdfReader
from src.readers.sqlite_reader import SqliteReader
from src.readers.text_reader import TextReader
from src.readers.word_reader import WordReader
from src.readers.xml_reader import XmlReader

_logger = get_logger(__name__)

# Order matters only for which reader is tried first when more than
# one could theoretically claim a file. Across all nine readers as of
# milestone 2c-ii, can_read() checks remain based on mutually
# exclusive extensions, so no real ambiguity exists.
_REGISTERED_READERS: tuple[type[BaseReader], ...] = (
    CsvReader,
    JsonReader,
    TextReader,
    ExcelReader,
    SqliteReader,
    PdfReader,
    WordReader,
    XmlReader,
    ImageReader,
)


def get_reader_for_path(path: Path) -> type[BaseReader]:
    """Return the reader class that can handle ``path``.

    Args:
        path: The file to find a reader for.

    Raises:
        ReaderError: If no registered reader's ``can_read`` returns
            ``True`` for this path — most commonly an unsupported
            file extension.
    """
    for reader_class in _REGISTERED_READERS:
        if reader_class.can_read(path):
            _logger.debug("Selected %s for %s.", reader_class.__name__, path)
            return reader_class

    supported_extensions = sorted(
        {
            ext
            for reader_class in _REGISTERED_READERS
            for ext in reader_class.SUPPORTED_EXTENSIONS
        }
    )
    raise ReaderError(
        f"No reader available for {path} (extension: "
        f"'{path.suffix}'). Supported extensions: "
        f"{', '.join(supported_extensions)}."
    )

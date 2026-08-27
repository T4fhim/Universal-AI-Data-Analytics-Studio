# File: src/readers/text_reader.py
"""Reads plain .txt files into a Dataset.

Unlike CSV and JSON, a ``.txt`` file has no inherent tabular
structure — it is, by definition, unstructured text. This reader
handles the two situations that actually occur in practice, and is
honest about the difference between them rather than forcing every
text file into the same shape:

1. **A delimited file with a ``.txt`` extension.** Plenty of
   real-world "text files" are actually comma- or tab-separated data
   that someone saved with a ``.txt`` extension instead of ``.csv``.
   This reader checks for that first — via the same delimiter-sniffing
   :class:`~src.readers.csv_reader.CsvReader` uses — and if a
   consistent delimiter is detected across the file, delegates to
   :class:`~src.readers.csv_reader.CsvReader` entirely, since at that
   point it *is* a CSV file in every way that matters.
2. **Genuinely unstructured text** — prose, logs, a single column of
   values with no consistent delimiter. This reader does not invent
   fake structure to force a multi-column table out of this. Instead,
   it produces a single-column ``Dataset`` where each row is one line
   of the file. This is a real, useful representation (the user can
   filter, search, or count lines against it) rather than a rejection
   dressed up as success.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.readers.csv_reader import CsvReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_TEXT_EXTENSIONS = {".txt"}

# Sample size for delimiter-sniffing (see _looks_delimited below).
# Deliberately not imported from csv_reader.py's own
# _SNIFF_SAMPLE_BYTES: that name is private to that module, and the
# two readers happening to want a similarly-sized sample is a
# coincidence of both wanting "a reasonable chunk to sniff," not a
# shared contract that would need single-sourcing the way, for
# example, config.py's validate_config_structure needed to be made
# public and shared with settings_service.py in milestone 1b-i. A
# duplicated integer literal cannot drift into subtly different
# behavior the way duplicated logic can.
_SNIFF_SAMPLE_BYTES = 65536


class TextReader(BaseReader):
    """Reads .txt files, delegating to CsvReader if the content is actually delimited.

    See the module docstring for the two cases this handles. Which
    case applied is recorded in ``read_warnings`` only for case 1 (the
    delegation itself is worth flagging, since the resulting columns
    might surprise a user who expected a single text blob); case 2
    produces no warning, since "one row per line" is the expected,
    unsurprising behavior for genuinely unstructured text.
    """

    SUPPORTED_EXTENSIONS = _TEXT_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _TEXT_EXTENSIONS

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read a .txt file at ``path``.

        Args:
            path: The file to read.
            table_name: Accepted for interface uniformity with
                :meth:`~src.readers.base_reader.BaseReader.read`, but
                ignored — see
                :meth:`~src.readers.csv_reader.CsvReader.read`'s
                docstring for the full reasoning. Passed through
                unchanged to the ``CsvReader.read`` delegation call
                below when this file is detected as delimited data,
                purely for consistency (``CsvReader`` also ignores it,
                for the same reason).

        Raises:
            ReaderError: If the file does not exist, is empty, or
                cannot be decoded as UTF-8. Unlike
                :class:`~src.readers.csv_reader.CsvReader`, this
                reader does not attempt encoding fallbacks for the
                single-column-of-lines case — a non-UTF-8 plain text
                file is unusual enough, and the fallback-encoding
                logic complex enough, that duplicating it here for a
                case that delegates to ``CsvReader`` for the one
                situation (delimited content) where encoding fallback
                would matter most is not worth the duplication. If
                encoding fallback for genuinely unstructured text
                becomes a real, observed need, it should be factored
                out of ``CsvReader`` into a shared helper both readers
                call, rather than duplicated independently here.
        """
        if not path.exists():
            raise ReaderError(f"Text file does not exist: {path}")
        if path.stat().st_size == 0:
            raise ReaderError(f"Text file is empty: {path}")

        if cls._looks_delimited(path):
            dataset = CsvReader.read(path, table_name=table_name)
            dataset.source_format = "txt (delimited, read as csv)"
            dataset.read_warnings.append(
                "This .txt file was detected as delimited data and "
                "read using the same logic as a CSV file."
            )
            _logger.info(
                "Read TXT file %s as delimited data (delegated to CsvReader).",
                path,
            )
            return dataset

        try:
            raw_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ReaderError(f"Text file {path} is not valid UTF-8: {exc}") from exc

        lines = raw_text.splitlines()
        dataframe = pd.DataFrame({"line": lines})

        _logger.info(
            "Read TXT file %s as unstructured text: %d lines.",
            path,
            len(lines),
        )

        return Dataset(
            name=path.stem,
            dataframe=dataframe,
            source_format="txt",
            source_path=path,
        )

    @classmethod
    def _looks_delimited(cls, path: Path) -> bool:
        """Return whether ``path``'s content appears to be delimited data.

        Reuses the same sniffing approach
        :class:`~src.readers.csv_reader.CsvReader` uses for its own
        delimiter detection, but treats a sniff failure as "not
        delimited" (returning ``False``) rather than propagating an
        error — unlike ``CsvReader``, where a sniff failure on a file
        the user explicitly identified as CSV is a real problem worth
        raising, here a sniff failure just means "fall through to the
        unstructured-text case," which is this reader's normal,
        expected behavior for most .txt files.

        Requires at least 2 lines in the sample before attempting
        detection at all — found necessary by testing this reader
        against a single-line file of ordinary prose containing a
        comma as normal punctuation (e.g. "one line, no trailing
        newline"). ``csv.Sniffer``'s detection fundamentally relies on
        checking whether a candidate delimiter is used *consistently*
        across multiple lines; with only one line available, there is
        nothing to check consistency against, and a single incidental
        comma was enough to produce a false "yes, this is delimited"
        result, incorrectly routing a genuine single-line text file
        through CSV delegation instead of the correct single-row
        line-based path.
        """
        try:
            raw_sample = path.read_bytes()[:_SNIFF_SAMPLE_BYTES]
            sample_text = raw_sample.decode("utf-8", errors="ignore")

            if len(sample_text.splitlines()) < 2:
                return False

            csv.Sniffer().sniff(sample_text, delimiters=",\t;|")
            return True
        except (csv.Error, UnicodeDecodeError):
            return False

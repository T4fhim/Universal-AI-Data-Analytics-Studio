# File: src/readers/csv_reader.py
"""Reads CSV (and other single-character-delimited) files into a Dataset.

:class:`CsvReader` handles the general "delimited text" case, not just
literal comma-separated files — the delimiter is detected via
:mod:`csv`'s ``Sniffer`` rather than assumed to be a comma, so a
tab-separated or semicolon-separated file (both common exports from
regional spreadsheet software) is read correctly rather than parsed as
one giant unsplit column.

Two failure-adjacent situations this reader treats as warnings rather
than hard failures, because a real-world CSV export commonly has one
or both and refusing to load the file entirely would be worse than
loading it with the affected rows or columns flagged:

* Rows with a different number of fields than the header (too few or
  too many commas). pandas' own default behavior here varies by
  version and by the ``on_bad_lines`` setting; this reader is explicit
  about it — bad lines are skipped, and the count of skipped lines is
  recorded as a warning, rather than either silently succeeding with
  misaligned data or raising and refusing to load a mostly-good file
  over a handful of bad rows.
* Columns pandas could not confidently infer a single type for (mixed
  numeric and text values in the same column) — these are recorded as
  warnings so a later dataset-profiling milestone, or the user
  directly, knows which columns may need attention, without this
  reader making a silent guess about what the "right" type was.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.readers.type_inference import find_ambiguous_type_columns
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_CSV_EXTENSIONS = {".csv", ".tsv"}

# Sample size (bytes) read for encoding and delimiter detection before
# committing to a full parse. Large enough to give csv.Sniffer several
# real rows to work with on files with long lines; small enough that
# detection is fast even on a multi-gigabyte file.
_SNIFF_SAMPLE_BYTES = 65536

# Encodings tried in order when UTF-8 fails. utf-8-sig handles
# UTF-8-with-BOM (common from Excel's "CSV UTF-8" export option,
# which otherwise leaves a literal BOM character prepended to the
# first column's header). cp1252 (Windows-1252) is included because it
# is the single most common encoding for CSV files exported by
# non-Unicode-aware Windows software, and is deliberately tried before
# latin-1 despite latin-1 accepting any byte sequence, because cp1252
# assigns meaningful characters (curly quotes, em-dashes) to byte
# ranges latin-1 leaves as control characters — a cp1252 file
# mis-decoded as latin-1 still "succeeds" but silently corrupts those
# characters, which is worse than the encoding attempt failing
# loudly and moving to the next candidate.
_FALLBACK_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


class CsvReader(BaseReader):
    """Reads CSV and TSV files.

    Delimiter is auto-detected; encoding is detected via a fallback
    chain (see module docstring). Both detection results are recorded
    in the resulting :class:`~src.services.workspace_service.Dataset`'s
    ``read_warnings`` only if something notable happened (a non-UTF-8
    encoding was needed, bad lines were skipped, or a column's type
    could not be confidently inferred) — a clean, standard UTF-8 comma
    file produces zero warnings, not a warning announcing that
    everything went as expected.
    """

    SUPPORTED_EXTENSIONS = _CSV_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _CSV_EXTENSIONS

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Read a CSV/TSV file at ``path``.

        Args:
            path: The file to read.
            table_name: Accepted for interface uniformity with
                :meth:`~src.readers.base_reader.BaseReader.read`
                (multi-table readers like
                :class:`~src.readers.excel_reader.ExcelReader` use
                this parameter; see that class), but ignored here — a
                CSV file has exactly one table by definition, so there
                is nothing for this reader to select between. A caller
                that does not know in advance whether it is calling a
                single-table or multi-table reader can safely pass
                ``table_name=None`` (or any value) to any reader
                without needing to branch on which kind it is.

        Raises:
            ReaderError: If the file does not exist, is empty, cannot
                be decoded with any attempted encoding, or has no
                detectable delimiter (for example, a single-column
                file with no consistent separator at all — this is
                distinct from a genuinely single-column file, which
                ``csv.Sniffer`` still detects correctly using
                consistent line breaks).
        """
        if not path.exists():
            raise ReaderError(f"CSV file does not exist: {path}")
        if path.stat().st_size == 0:
            raise ReaderError(f"CSV file is empty: {path}")

        warnings: list[str] = []

        encoding, sample_text = cls._detect_encoding(path)
        if encoding != "utf-8":
            warnings.append(
                f"File was not valid UTF-8; decoded using '{encoding}' instead."
            )

        delimiter = cls._detect_delimiter(sample_text, path)

        bad_line_count = 0

        def _record_bad_line(bad_line: list[str]) -> str | None:
            # Passed to pandas as on_bad_lines when engine='python'.
            # Returning None tells pandas to skip the line; the
            # closure increments bad_line_count as a side effect so
            # the final warning can report how many were skipped.
            nonlocal bad_line_count
            bad_line_count += 1
            return None

        try:
            dataframe = pd.read_csv(
                path,
                sep=delimiter,
                encoding=encoding,
                engine="python",
                on_bad_lines=_record_bad_line,
            )
        except pd.errors.EmptyDataError as exc:
            raise ReaderError(f"CSV file has no parsable columns: {path}") from exc
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            raise ReaderError(f"Failed to parse CSV file {path}: {exc}") from exc

        if bad_line_count > 0:
            warnings.append(
                f"{bad_line_count} row(s) had a different number of "
                f"fields than the header and were skipped."
            )

        ambiguous_columns = cls._find_ambiguous_type_columns(dataframe)
        if ambiguous_columns:
            warnings.append(
                f"Column(s) with mixed or ambiguous types (loaded as "
                f"text): {', '.join(ambiguous_columns)}."
            )

        _logger.info(
            "Read CSV file %s: %d rows, %d columns, %d warning(s).",
            path,
            len(dataframe),
            len(dataframe.columns),
            len(warnings),
        )

        return Dataset(
            name=path.stem,
            dataframe=dataframe,
            source_format="csv",
            source_path=path,
            read_warnings=warnings,
        )

    @classmethod
    def _detect_encoding(cls, path: Path) -> tuple[str, str]:
        """Return (encoding_used, decoded_sample_text) for ``path``.

        Tries UTF-8 first (the common case, checked without penalty),
        then the fallback chain in :data:`_FALLBACK_ENCODINGS` in
        order, returning the first one that decodes the sample without
        error.

        Raises:
            ReaderError: If no attempted encoding can decode the
                sample.
        """
        raw_sample = path.read_bytes()[:_SNIFF_SAMPLE_BYTES]

        for encoding in ("utf-8", *_FALLBACK_ENCODINGS):
            try:
                return encoding, raw_sample.decode(encoding)
            except UnicodeDecodeError:
                continue

        raise ReaderError(
            f"Could not decode {path} using any of the attempted "
            f"encodings: utf-8, {', '.join(_FALLBACK_ENCODINGS)}."
        )

    @classmethod
    def _detect_delimiter(cls, sample_text: str, path: Path) -> str:
        """Return the detected field delimiter for ``sample_text``.

        Tries ``csv.Sniffer`` first, which considers the whole sample
        and is the more reliable approach for well-formed files. If
        that fails, falls back to counting delimiter-candidate
        characters on the first line only (see
        :meth:`_detect_delimiter_from_header`).

        This two-step approach exists because of a real gap found by
        testing this reader against a file with an inconsistent row
        length (a row with more fields than its header) — exactly the
        kind of file :meth:`read`'s bad-line-skipping logic is meant
        to handle gracefully. ``csv.Sniffer`` examines the full
        sample's consistency and can fail to determine a delimiter at
        all when later rows are malformed, even though the delimiter
        itself is completely unambiguous from the header line alone.
        Without this fallback, such a file would fail at delimiter
        detection before ever reaching the bad-line-skipping logic
        that would otherwise handle it correctly.

        Raises:
            ReaderError: If neither ``csv.Sniffer`` nor the
                header-based fallback can determine a delimiter. In
                practice this means the sample is empty or
                whitespace-only — a header line with content but no
                delimiter characters is handled by the fallback as a
                single-column file (see
                :meth:`_detect_delimiter_from_header`), not as a
                failure.
        """
        try:
            dialect = csv.Sniffer().sniff(sample_text, delimiters=",\t;|")
            return dialect.delimiter
        except csv.Error:
            pass  # fall through to the header-based heuristic below

        fallback_delimiter = cls._detect_delimiter_from_header(sample_text)
        if fallback_delimiter is not None:
            return fallback_delimiter

        raise ReaderError(
            f"Could not detect a delimiter in {path}. The file may be "
            f"empty, use an unsupported delimiter, or not be a "
            f"delimited text file at all."
        )

    @classmethod
    def _detect_delimiter_from_header(cls, sample_text: str) -> str | None:
        """Return the most likely delimiter based on the first line alone, or ``None``.

        Counts occurrences of each candidate delimiter
        (``,``, tab, ``;``, ``|``) on the first line only. The header
        line is used rather than the whole sample specifically because
        it is the line most likely to be well-formed even in a file
        whose data rows have inconsistent field counts — the exact
        situation that causes ``csv.Sniffer`` to fail (see
        :meth:`_detect_delimiter`'s docstring).

        Returns the candidate with the highest count, breaking ties in
        favor of comma (the most common delimiter, and a reasonable
        default when a line genuinely contains, for example, one
        semicolon and one comma with no other information to prefer
        one over the other).

        If the first line contains *none* of the candidate delimiters
        at all, this is treated as a genuinely single-column file —
        not a detection failure. This distinction was found necessary
        by testing: a file like ``"names\\nAlice\\nBob\\n"`` has no
        delimiter character anywhere in its header for the simple
        reason that it only has one column, which is a common, valid
        case, not an error. Comma is returned in this case as an
        arbitrary technical default — since there is nothing to split
        on regardless of which delimiter is specified, pandas will
        correctly load the file as a single column either way, so the
        specific choice of "unused" delimiter here cannot itself cause
        incorrect data to be produced.
        """
        first_line = sample_text.splitlines()[0] if sample_text.splitlines() else ""
        if not first_line:
            return None

        # Order matters for the tie-break: comma listed first, and
        # max() with this dict preserves insertion order for equal
        # values in Python 3.7+, so a tie resolves to whichever
        # candidate appears earliest here.
        candidate_counts = {
            ",": first_line.count(","),
            "\t": first_line.count("\t"),
            ";": first_line.count(";"),
            "|": first_line.count("|"),
        }

        best_delimiter = max(candidate_counts, key=candidate_counts.get)
        if candidate_counts[best_delimiter] == 0:
            # No candidate delimiter appears in the header at all:
            # treat as single-column (see docstring above), not as a
            # failure to detect.
            return ","
        return best_delimiter

    @classmethod
    def _find_ambiguous_type_columns(cls, dataframe: pd.DataFrame) -> list[str]:
        """Return names of columns containing a mix of numeric and non-numeric values.

        Thin delegation to
        :func:`~src.readers.type_inference.find_ambiguous_type_columns`.
        The detection logic itself — and the two-round debugging
        history behind it — now lives in that shared module rather
        than here, since :class:`~src.readers.sqlite_reader.SqliteReader`
        needed the identical check for a different but related reason
        (SQLite's dynamic typing) and importing this method privately
        across a module boundary would have repeated a private-import
        pattern already fixed twice earlier in this project. This
        wrapper is kept (rather than having every call site inside
        this class import and call the shared function directly) only
        for continuity with this class's existing internal call site
        above, in :meth:`read`.
        """
        return find_ambiguous_type_columns(dataframe)

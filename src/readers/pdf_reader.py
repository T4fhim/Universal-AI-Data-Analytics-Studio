# File: src/readers/pdf_reader.py
"""Extracts tables from PDF documents into a Dataset.

:class:`PdfReader` is a genuinely different kind of reader from every
one built in milestones 2a and 2b. Those readers all read a source
that either already is tabular (CSV, JSON, Excel, SQLite) or can be
represented as a single column of lines (TXT). A PDF is neither — it
is a page-layout format that may contain zero, one, or many tables
embedded among arbitrary prose, images, and other content. This
reader's job is table *extraction*, not simple parsing, and the
"zero tables found" case is a normal, valid outcome (a text-only PDF
is not a malformed file) rather than an error — see
:mod:`src.readers.base_reader`'s ``list_tables`` contract, and
:mod:`src.ui.main_window`'s ``_NO_TABLES_AVAILABLE`` handling, both
extended in this milestone specifically to accommodate this case
honestly.

Uses ``camelot-py`` rather than ``PyMuPDF`` (the library named in this
project's original technology list) — a deliberate deviation, made
because ``camelot`` is purpose-built for table extraction (which is
this reader's entire job) while ``PyMuPDF`` is a general-purpose PDF
toolkit with no dedicated table-detection logic of its own. Using
``PyMuPDF`` here would have meant either hand-rolling table-detection
heuristics on top of raw text extraction, or installing and using
``camelot`` anyway underneath a thinner wrapper — ``camelot`` was
already present in this project's environment, unprompted, and using
it directly is more honest than either alternative.

**Extraction strategy, and why**, found through real testing during
this milestone rather than assumed: ``camelot`` offers two extraction
backends, ``"lattice"`` (uses a PDF's visible grid lines to locate
table boundaries precisely; requires Ghostscript, a system-level
dependency this project does not assume is installed) and
``"stream"`` (infers table boundaries from whitespace alignment; no
Ghostscript dependency, but measurably less precise — testing during
this milestone found that ``"stream"`` mode can sweep nearby
non-tabular text, such as a document title sitting directly above a
table, into the extracted result as spurious rows, while
``"lattice"`` mode, tested against the identical document, extracted
only the genuine table content). This reader tries ``"lattice"``
first; if it finds nothing (either because the table genuinely has no
visible grid lines, or because Ghostscript is not installed and
``"lattice"`` cannot run at all), it falls back to ``"stream"``. A
PDF with gridded tables gets the more accurate extraction; a PDF
without them, or an environment without Ghostscript, still gets a
result via the less precise fallback rather than failing outright.

A significant, honestly-documented limitation: results from the
``"stream"`` fallback may include non-tabular text that happened to
be positioned near the extracted table (as observed in testing — see
above). Testing during this milestone also found a related, distinct
symptom of the same underlying cause: ``"stream"`` mode's
whitespace-based boundary detection can merge two genuinely separate
tables that are positioned close together on the same page into a
single extracted result, rather than recognizing them as two tables —
confirmed by comparing ``"stream"`` mode's output on a page with two
adjacent, individually-gridded tables against what ``"lattice"`` mode
correctly reported as zero tables (since neither table's grid touched
the other closely enough for ``"lattice"`` to misjudge them as one,
while ``"stream"`` had no such boundary information available at
all). This reader does not attempt to detect and split merged tables
automatically, for the same scope-boundary reasoning as the
prose-sweeping limitation above. A warning is recorded whenever the
``"stream"`` fallback is used, covering both symptoms generally rather
than attempting to distinguish which specific failure mode occurred
for a given table.

A third, more consequential finding from testing, which required an
actual code fix rather than only documentation: ``"stream"`` mode, run
against a genuinely prose-only PDF with no tabular content at all,
does not report zero tables the way ``"lattice"`` correctly does —
instead it returns a single-column pseudo-table with each paragraph as
a separate row, treating any block of left-aligned text as a
candidate table. Left unhandled, this would have made this reader's
entire "zero tables found" case (the reason
:mod:`src.ui.main_window`'s dataset-opening flow was extended with a
dedicated ``_NO_TABLES_AVAILABLE`` state — see that module) effectively
unreachable for any PDF containing ordinary paragraph text, which is
most PDFs. :meth:`_extract_tables` filters out single-column
``"stream"`` results specifically to close this gap — a genuine table
drawn from real tabular content almost always has more than one
column, so this filter is a reliable, low-risk way to distinguish a
real (if imprecisely extracted) table from prose being misidentified
as one.
"""

from __future__ import annotations

from pathlib import Path

import camelot
import pandas as pd

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_PDF_EXTENSIONS = {".pdf"}


class PdfReader(BaseReader):
    """Extracts tables from PDF documents, one table per read.

    Table names take the form ``"Page N, Table M"`` (1-indexed on
    both counts) rather than a name drawn from the PDF's own content,
    since — unlike an Excel sheet or a SQLite table — a table embedded
    in a PDF page has no inherent name of its own to use.

    A known inefficiency, documented rather than silently accepted:
    :meth:`list_tables` and :meth:`read` each independently re-run
    ``camelot``'s extraction (there is no caching between the two
    calls). Since :mod:`src.ui.main_window`'s dataset-opening flow
    always calls :meth:`list_tables` first and then :meth:`read`
    immediately after with the user's choice, this means a PDF's
    tables are effectively extracted twice per open. Every reader in
    this project is a stateless classmethod-only class with no
    instance to hold a cache across the two calls, and adding a
    module-level or file-path-keyed cache would introduce real
    complexity (invalidation, unbounded memory growth across a long
    session) to solve what is currently a "slower than ideal"
    problem, not a "broken" one. Worth revisiting if this proves to be
    a genuine, observed pain point on large PDFs, not before.
    """

    SUPPORTED_EXTENSIONS = _PDF_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _PDF_EXTENSIONS

    @classmethod
    def list_tables(cls, path: Path) -> list[str]:
        """Return names for each table found in the PDF at ``path``.

        Returns an empty list if the PDF genuinely contains no
        detectable tables — this is a normal, valid outcome for a
        prose-only document, not an error. See
        :meth:`~src.readers.base_reader.BaseReader.list_tables`'s own
        docstring for how callers (specifically
        :mod:`src.ui.main_window`) are expected to handle an empty
        result.

        Raises:
            ReaderError: If the file does not exist or cannot be
                opened as a PDF at all (corrupted file, wrong format
                despite the extension, password-protected with no
                password supplied).
        """
        if not path.exists():
            raise ReaderError(f"PDF file does not exist: {path}")

        tables = cls._extract_tables(path)
        return cls._build_table_names(tables)

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Extract one table from the PDF at ``path``.

        Args:
            path: The PDF to read.
            table_name: Which table to read, in the ``"Page N, Table
                M"`` format :meth:`list_tables` returns. If the PDF
                has exactly one detected table, ``None`` reads it
                directly. If it has more than one and ``table_name``
                is ``None``, this raises rather than guessing.

        Raises:
            ReaderError: If the file does not exist, cannot be opened,
                contains zero tables (call :meth:`list_tables` first
                to check — this method itself still raises if called
                directly with nothing to extract, since ``read`` is
                assumed to be called only after a caller has already
                established there is something to read), has more
                than one table but no ``table_name`` was given, or
                ``table_name`` does not match any extracted table.
        """
        if not path.exists():
            raise ReaderError(f"PDF file does not exist: {path}")

        extracted_tables = cls._extract_tables(path)

        if not extracted_tables:
            raise ReaderError(
                f"{path} contains no detectable tables. Check "
                f"list_tables() before calling read() to avoid this "
                f"error for documents with no tabular content."
            )

        available_names = cls._build_table_names(extracted_tables)

        if table_name is None:
            if len(extracted_tables) == 1:
                selected_index = 0
            else:
                raise ReaderError(
                    f"{path} contains {len(extracted_tables)} tables "
                    f"({', '.join(available_names)}); specify which "
                    f"one to read via the table_name argument."
                )
        elif table_name not in available_names:
            raise ReaderError(
                f"{path} has no table named '{table_name}'. Available "
                f"tables: {', '.join(available_names)}."
            )
        else:
            selected_index = available_names.index(table_name)

        selected_table = extracted_tables[selected_index]
        dataframe = cls._promote_header_row(selected_table.df)

        warnings: list[str] = []
        if getattr(selected_table, "_extraction_flavor_used", None) == "stream":
            warnings.append(
                "This table was extracted using the 'stream' method "
                "(no visible grid lines were detected, or the more "
                "precise 'lattice' method was unavailable in this "
                "environment). Rows near the table in the original "
                "PDF — such as a nearby title or caption — may have "
                "been included by mistake; review the extracted data "
                "for unexpected rows."
            )

        _logger.info(
            "Read PDF table '%s' from %s: %d rows, %d columns, " "%d warning(s).",
            available_names[selected_index],
            path,
            len(dataframe),
            len(dataframe.columns),
            len(warnings),
        )

        return Dataset(
            name=(
                f"{path.stem} — {available_names[selected_index]}"
                if len(extracted_tables) > 1
                else path.stem
            ),
            dataframe=dataframe,
            source_format="pdf",
            source_path=path,
            read_warnings=warnings,
        )

    @classmethod
    def _build_table_names(cls, tables: list) -> list[str]:
        """Build ``"Page N, Table M"`` names, numbering tables correctly within each page.

        This method exists because an earlier version of this reader
        had a real, found-by-testing bug here: it numbered every
        table using its position in the overall extraction result
        (``enumerate(tables)``) rather than its position within its
        own page, so the first table on page 2 would be incorrectly
        labeled "Table 2" instead of "Table 1" whenever page 1 also
        had a table before it. This version tracks a separate counter
        per page number, incrementing only within that page, so table
        numbering restarts correctly at 1 for each new page —
        matching what "Table 1" on a given page should intuitively
        mean to a user picking from the list, regardless of how many
        tables preceded it on earlier pages.

        Used identically by both :meth:`list_tables` and :meth:`read`
        (via a single shared implementation) so the two methods can
        never independently drift into disagreeing about what a given
        table's name is — a real risk if this logic were duplicated
        in both places instead.
        """
        counts_per_page: dict[int, int] = {}
        names = []
        for table in tables:
            page_number = table.page
            counts_per_page[page_number] = counts_per_page.get(page_number, 0) + 1
            table_number_on_this_page = counts_per_page[page_number]
            names.append(f"Page {page_number}, Table {table_number_on_this_page}")
        return names

    @classmethod
    def _extract_tables(cls, path: Path) -> list:
        """Run camelot's extraction, trying 'lattice' first and falling back to 'stream'.

        Returns camelot's own ``TableList`` (or an empty list-like
        object if extraction found nothing) — kept as camelot's native
        return type rather than converted to something else
        immediately, since both :meth:`list_tables` and :meth:`read`
        need different pieces of information from it (names only,
        versus full data).

        Each table object returned when the 'stream' fallback was
        used gets a ``_extraction_flavor_used`` attribute set to
        ``"stream"`` — a deliberate, minimal way to let :meth:`read`
        know which extraction path produced a given table (needed for
        the "may include nearby text" warning above) without
        threading a second return value through every call site.

        Raises:
            ReaderError: If camelot cannot open the file as a PDF at
                all (corrupted file, wrong format, encrypted with no
                password) — this is distinct from "opened
                successfully but found zero tables," which is not an
                error and returns an empty result instead.
        """
        try:
            lattice_tables = camelot.read_pdf(str(path), pages="all", flavor="lattice")
        except Exception as exc:
            raise ReaderError(f"Failed to open {path} as a PDF: {exc}") from exc

        if len(lattice_tables) > 0:
            return list(lattice_tables)

        try:
            stream_tables = camelot.read_pdf(str(path), pages="all", flavor="stream")
        except Exception as exc:
            raise ReaderError(f"Failed to open {path} as a PDF: {exc}") from exc

        # Filter out a real, found-by-testing failure mode: 'stream'
        # mode's whitespace-based detection treats any block of
        # left-aligned text as a candidate table, including ordinary
        # prose paragraphs with no tabular structure at all — tested
        # directly against a genuinely prose-only PDF, which
        # 'lattice' correctly reported as zero tables but 'stream'
        # reported as one single-column "table" (each paragraph
        # becoming a row). A single-column result is the reliable
        # signal for this specific failure: a genuine table drawn from
        # real tabular content almost always has more than one
        # column, since a single column of text is definitionally not
        # something 'lattice' or a human would call a table. Without
        # this filter, the zero-tables case this reader is built
        # around (see the module docstring) would be effectively
        # unreachable for any prose-containing PDF, since 'stream'
        # mode would always claim something.
        genuine_stream_tables = [t for t in stream_tables if t.df.shape[1] > 1]

        for table in genuine_stream_tables:
            table._extraction_flavor_used = "stream"

        return genuine_stream_tables

    @classmethod
    def _promote_header_row(cls, dataframe: pd.DataFrame) -> pd.DataFrame:
        """Use the extracted table's first row as column headers.

        ``camelot`` returns every extracted table with plain integer
        column labels (``0, 1, 2, ...``) — it does not attempt to
        distinguish a header row from a data row, since a PDF table's
        visual layout gives no explicit signal for this the way a
        CSV's first line or an Excel sheet's row 1 convention does.
        This method assumes the first extracted row is the header,
        matching the same row-1-is-header assumption
        :class:`~src.readers.excel_reader.ExcelReader` documents for
        the analogous reason — see that reader's module docstring for
        the fuller reasoning, which applies identically here.
        """
        if len(dataframe) == 0:
            return dataframe

        new_header = dataframe.iloc[0]
        remaining_rows = dataframe.iloc[1:].reset_index(drop=True)
        remaining_rows.columns = new_header
        return remaining_rows

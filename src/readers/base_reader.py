# File: src/readers/base_reader.py
"""The shared interface every format-specific reader implements.

:class:`BaseReader` defines the contract this package's readers all
follow: given a file path, produce a
:class:`~src.services.workspace_service.Dataset`, or raise a
:class:`~src.core.exceptions.ReaderError` with a message specific
enough that the UI layer can show the user something more useful than
"failed to read file."

Three methods:

* :meth:`can_read` — a fast, cheap check ("does this file's extension
  and/or a quick peek at its header match what I handle?") that a
  future format-auto-detection dispatcher can call across every
  registered reader to find the right one for a given file, without
  that dispatcher needing to hardcode a suffix-to-reader mapping
  itself. Deliberately cheap: it should not need to fully parse the
  file to answer, since it may be called across every reader just to
  find the one that matches.
* :meth:`list_tables` — added in milestone 2b, when Excel and SQLite
  readers introduced a real case milestone 2a's three readers never
  had: a single file that can contain more than one table (worksheets;
  database tables). Concrete here with a default implementation
  (return the file's own name as a single "table"), not declared
  ``abstract`` — milestone 2a's readers (CSV, JSON, TXT) have no
  concept of multiple tables at all, and forcing each of them to
  implement a method that would only ever return a one-item list
  purely to satisfy an interface requirement would be exactly the kind
  of unnecessary abstraction this project's own quality bar warns
  against. Only readers that genuinely have more than one table to
  offer (see :mod:`src.readers.excel_reader`,
  :mod:`src.readers.sqlite_reader`) override this method; every other
  reader inherits the single-table default unchanged.
* :meth:`read` — the actual work. Assumes ``can_read`` would have
  returned ``True`` for this path (callers are expected to check
  first, though ``read`` does not re-verify this itself — see that
  method's own docstring for why). Gained an optional ``table_name``
  parameter in milestone 2b, for the same multi-table reason as
  ``list_tables`` above — see that parameter's own documentation below
  for exactly how a reader is expected to behave when the source has
  more than one table and no ``table_name`` was given.

This module does not implement any concrete format. See
:mod:`src.readers.csv_reader`, :mod:`src.readers.json_reader`, and
:mod:`src.readers.text_reader` for milestone 2a's three single-table
readers; :mod:`src.readers.excel_reader` and
:mod:`src.readers.sqlite_reader` for milestone 2b's two multi-table
readers; and :mod:`src.readers.reader_registry` for the dispatcher
that ties all of them together.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.workspace_service import Dataset


class BaseReader(ABC):
    """Abstract base class every format-specific reader inherits from.

    Concrete readers are stateless — every method here is a
    ``classmethod``, so a reader never needs to be instantiated to be
    used. This mirrors how the readers are actually consumed (see
    :mod:`src.readers.reader_registry`, which holds reader *classes*,
    not instances) and avoids a pointless "construct an object with no
    meaningful state just to call one method on it" step at every call
    site.

    Every concrete reader must also define
    ``SUPPORTED_EXTENSIONS: set[str]`` as a class attribute — not
    declared as an abstract property here (Python's ``abc`` module
    supports abstract properties, but combining them cleanly with
    class-level, non-instance attributes adds complexity this
    two-line contract does not need) but relied upon by
    :mod:`src.readers.reader_registry` to build a useful "supported
    formats" error message without needing to import each reader
    module and inspect its internals by name. Declared here in the
    docstring, rather than silently assumed, so a new reader added in
    milestone 2b or 2c has a clear, written expectation to satisfy.
    """

    @classmethod
    @abstractmethod
    def can_read(cls, path: Path) -> bool:
        """Return whether this reader is likely able to read ``path``.

        Implementations should be fast — checking the file extension,
        and optionally peeking at the first few bytes for a format
        signature, is appropriate. Implementations must not raise;
        an unreadable or nonexistent path should return ``False``
        rather than propagate an exception, since callers (see
        :mod:`src.readers.reader_registry`) may call this across many
        readers just to find a match, and a raised exception from a
        mismatched reader would break that search rather than simply
        indicate "not mine."

        Args:
            path: The file to check.
        """
        raise NotImplementedError

    @classmethod
    def list_tables(cls, path: Path) -> list[str]:
        """Return the names of tables available in ``path``.

        Default implementation (inherited by every single-table
        reader — CSV, JSON, TXT — unchanged): returns a single name
        derived from the file itself (``path.stem``), since those
        formats have no concept of multiple tables to begin with. A
        caller can always call this method on any reader without
        needing to know in advance whether that reader supports
        multiple tables; a single-table reader answering "there is
        exactly one, and here is its name" is a fully correct and
        useful answer, not a degenerate case to special-case around.

        Readers that genuinely support multiple tables per file
        (:class:`~src.readers.excel_reader.ExcelReader`,
        :class:`~src.readers.sqlite_reader.SqliteReader`) override
        this to return the real list — sheet names, database table
        names — which a caller (typically the UI layer, prompting the
        user to pick one when there's more than one) uses to decide
        what to pass as :meth:`read`'s ``table_name`` argument.

        This default implementation does not verify that ``path``
        exists or is readable — it is a pure naming convenience for
        the single-table case, not an I/O operation. A genuinely
        unreadable path will still fail, correctly, when
        :meth:`read` is actually called on it.

        Args:
            path: The file to list tables for.
        """
        return [path.stem]

    @classmethod
    @abstractmethod
    def read(cls, path: Path, table_name: str | None = None) -> "Dataset":
        """Read ``path`` and return a populated :class:`~src.services.workspace_service.Dataset`.

        Callers are expected to have already established that this
        reader is appropriate for ``path`` (typically via
        :meth:`can_read`, or because the user explicitly chose this
        format). This method does not re-check ``can_read`` itself —
        requiring every reader to redundantly re-verify a check its
        caller most likely already made would be wasted work on every
        single read, and a reader given an inappropriate path should
        still fail loudly with a specific parse error rather than a
        generic "wrong reader" message, which is what would happen if
        this method deferred to ``can_read`` and got a false negative.

        Args:
            path: The file to read.
            table_name: For multi-table readers, which table (sheet
                name; database table name) to read. Ignored by
                single-table readers (CSV, JSON, TXT), which read the
                one table their format has regardless of what is
                passed here. For multi-table readers: if the source
                has exactly one table, ``None`` reads it directly
                (matching single-table readers' zero-argument
                simplicity for the common case of "just read the
                file"). If the source has more than one table and
                ``table_name`` is ``None``, the reader must raise
                :class:`~src.core.exceptions.ReaderError` naming the
                available tables (via :meth:`list_tables`) rather than
                silently guessing which one the caller wanted — a
                caller facing that error is expected to call
                :meth:`list_tables` and retry with an explicit name,
                not to have this method pick on its behalf.

        Raises:
            ReaderError: If the file cannot be read or parsed, or (for
                multi-table readers) if ``table_name`` is required but
                was not given, or names a table that does not exist in
                the source. See each concrete reader's own ``read``
                docstring for the specific conditions it distinguishes.
        """
        raise NotImplementedError

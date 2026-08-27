# File: src/readers/archive_reader.py
"""Reads a data file out of a ZIP or GZIP archive into a Dataset.

Not a format in its own right the way every other reader in this
package is — a ZIP or GZIP file's actual tabular content is whatever
format is *inside* it, so this reader's real job is decompressing to a
temporary file and then delegating to
:func:`~src.readers.reader_registry.get_reader_for_path` to find the
right reader for the decompressed content, rather than reimplementing
CSV/JSON/Excel/etc. parsing a second time. The two formats this class
handles are unified here (rather than split into ``ZipReader``/
``GzipReader``) because the plan groups them as one bullet and their
``can_read``/``read`` shapes are close enough (both wrap another
reader) that splitting them would mostly duplicate the delegation
logic below.

``get_reader_for_path`` is imported lazily, inside the methods that
need it, rather than at module level — :mod:`src.readers.
reader_registry` imports every built-in reader class (including this
one) to build ``_BUILTIN_READERS``, so a module-level import here would
be a circular import. This is the same "both sides need to reference
each other" situation :mod:`src.plugins.plugin_loader` and
:mod:`src.visualization.chart_registry` avoid by keeping the registry
itself free of reverse imports; delegating this narrow case at call
time is simpler than restructuring the registry solely to accommodate
one self-referential reader.

ZIP archives containing more than one file are multi-table (one
"table" per inner file this reader can find an appropriate reader for
— unreadable inner files, e.g. a ``.exe`` bundled alongside a
``.csv``, are silently excluded from :meth:`ArchiveReader.list_tables`
rather than causing the whole archive to fail). GZIP files are
single-table by construction — gzip compresses exactly one stream, so
there is nothing to enumerate.
"""

from __future__ import annotations

import gzip
import shutil
import tempfile
import zipfile
from pathlib import Path

from src.core.exceptions import ReaderError
from src.core.logger import get_logger
from src.readers.base_reader import BaseReader
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_ZIP_EXTENSIONS = {".zip"}
_GZIP_EXTENSIONS = {".gz", ".gzip"}
_ARCHIVE_EXTENSIONS = _ZIP_EXTENSIONS | _GZIP_EXTENSIONS


class ArchiveReader(BaseReader):
    """Decompresses a ZIP or GZIP archive and delegates to the appropriate reader for its content."""

    SUPPORTED_EXTENSIONS = _ARCHIVE_EXTENSIONS

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return path.suffix.lower() in _ARCHIVE_EXTENSIONS

    @classmethod
    def list_tables(cls, path: Path) -> list[str]:
        """Return the names of inner files this reader can find an appropriate reader for.

        For a GZIP file, always a single-item list (the decompressed
        file's own name). For a ZIP file, one entry per contained file
        whose extension a registered reader recognizes — entries this
        reader cannot dispatch to any reader are silently excluded, not
        listed as an error, since an archive legitimately containing a
        mix of data and non-data files is normal, not corrupted.

        Raises:
            ReaderError: If the file does not exist, is not a valid
                ZIP/GZIP archive, or (ZIP only) contains no file this
                reader can dispatch to any registered reader.
        """
        if not path.exists():
            raise ReaderError(f"Archive file does not exist: {path}")

        if path.suffix.lower() in _GZIP_EXTENSIONS:
            return [cls._gzip_inner_name(path)]

        try:
            with zipfile.ZipFile(path) as archive:
                names = [n for n in archive.namelist() if not n.endswith("/")]
        except zipfile.BadZipFile as exc:
            raise ReaderError(f"{path} is not a valid ZIP archive: {exc}") from exc

        readable_names = [
            name for name in names if cls._inner_reader_class(name) is not None
        ]
        if not readable_names:
            raise ReaderError(
                f"{path} contains no file this application has a reader for."
            )
        return readable_names

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        """Decompress the selected inner file from ``path`` and read it with the appropriate reader.

        Args:
            path: The ``.zip``/``.gz``/``.gzip`` archive to read.
            table_name: For a ZIP archive with more than one readable
                inner file, which one to read (by the name returned
                from :meth:`list_tables`). Ignored for GZIP (single
                inner stream) and for a ZIP with exactly one readable
                inner file.

        Raises:
            ReaderError: If the archive cannot be opened, has more than
                one readable inner file but no ``table_name`` was
                given, ``table_name`` does not match any readable inner
                file, or the decompressed content itself fails to read
                (propagated from whichever reader handled it).
        """
        if path.suffix.lower() in _GZIP_EXTENSIONS:
            return cls._read_gzip(path)
        return cls._read_zip(path, table_name)

    @classmethod
    def _read_gzip(cls, path: Path) -> Dataset:
        inner_name = cls._gzip_inner_name(path)
        extracted_dir = Path(tempfile.mkdtemp())
        inner_path = extracted_dir / inner_name

        try:
            with gzip.open(path, "rb") as source, open(inner_path, "wb") as destination:
                shutil.copyfileobj(source, destination)
        except OSError as exc:
            shutil.rmtree(extracted_dir, ignore_errors=True)
            raise ReaderError(f"Failed to decompress GZIP file {path}: {exc}") from exc

        try:
            dataset = cls._read_with_matching_reader(inner_path, inner_name)
        finally:
            shutil.rmtree(extracted_dir, ignore_errors=True)

        _logger.info("Read GZIP archive %s via inner file %s.", path, inner_name)
        return dataset

    @classmethod
    def _read_zip(cls, path: Path, table_name: str | None) -> Dataset:
        readable_names = cls.list_tables(path)

        if table_name is None:
            if len(readable_names) == 1:
                table_name = readable_names[0]
            else:
                raise ReaderError(
                    f"{path} contains {len(readable_names)} readable "
                    f"file(s) ({', '.join(readable_names)}); specify "
                    f"which one to read via the table_name argument."
                )
        elif table_name not in readable_names:
            raise ReaderError(
                f"{path} has no readable entry named '{table_name}'. "
                f"Available entries: {', '.join(readable_names)}."
            )

        try:
            with zipfile.ZipFile(path) as archive:
                extracted_dir = Path(tempfile.mkdtemp())
                extracted_path = Path(archive.extract(table_name, path=extracted_dir))
        except (zipfile.BadZipFile, OSError) as exc:
            raise ReaderError(
                f"Failed to extract '{table_name}' from {path}: {exc}"
            ) from exc

        try:
            dataset = cls._read_with_matching_reader(extracted_path, table_name)
        finally:
            shutil.rmtree(extracted_dir, ignore_errors=True)

        _logger.info("Read ZIP archive %s via inner file %s.", path, table_name)
        return dataset

    @classmethod
    def _gzip_inner_name(cls, path: Path) -> str:
        """Return the decompressed file's likely name, e.g. ``sales.csv.gz`` -> ``sales.csv``."""
        if path.suffix.lower() in _GZIP_EXTENSIONS:
            return path.stem
        return path.name

    @classmethod
    def _inner_reader_class(cls, inner_name: str):
        from src.readers.reader_registry import get_reader_for_path

        try:
            return get_reader_for_path(Path(inner_name))
        except ReaderError:
            return None

    @classmethod
    def _read_with_matching_reader(
        cls, extracted_path: Path, display_name: str
    ) -> Dataset:
        from src.readers.reader_registry import get_reader_for_path

        reader_class = get_reader_for_path(extracted_path)
        dataset = reader_class.read(extracted_path)
        # The extracted path is a temp file with no lasting meaning to
        # the user — restore the archive-relative name so the Dataset
        # Explorer shows "sales.csv" rather than an opaque temp path.
        dataset.name = Path(display_name).stem
        dataset.source_path = None
        return dataset

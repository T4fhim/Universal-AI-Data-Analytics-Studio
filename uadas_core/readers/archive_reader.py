# File: uadas_core/readers/archive_reader.py
"""Reads a data file out of a ZIP or GZIP archive into a Dataset.

Not a format in its own right the way every other reader in this
package is — a ZIP or GZIP file's actual tabular content is whatever
format is *inside* it, so this reader's real job is decompressing to a
temporary file and then delegating to
:func:`~uadas_core.readers.reader_registry.get_reader_for_path` to find the
right reader for the decompressed content, rather than reimplementing
CSV/JSON/Excel/etc. parsing a second time. The two formats this class
handles are unified here (rather than split into ``ZipReader``/
``GzipReader``) because the plan groups them as one bullet and their
``can_read``/``read`` shapes are close enough (both wrap another
reader) that splitting them would mostly duplicate the delegation
logic below.

``get_reader_for_path`` is imported lazily, inside the methods that
need it, rather than at module level — :mod:`uadas_core.readers.
reader_registry` imports every built-in reader class (including this
one) to build ``_BUILTIN_READERS``, so a module-level import here would
be a circular import. This is the same "both sides need to reference
each other" situation :mod:`uadas_core.plugins.plugin_loader` and
:mod:`uadas_core.visualization.chart_registry` avoid by keeping the registry
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
from pathlib import Path, PurePosixPath

from uadas_core.core.exceptions import ReaderError
from uadas_core.core.logger import get_logger
from uadas_core.readers.base_reader import BaseReader
from uadas_core.services.workspace_service import Dataset

_logger = get_logger(__name__)

_ZIP_EXTENSIONS = {".zip"}
_GZIP_EXTENSIONS = {".gz", ".gzip"}
_ARCHIVE_EXTENSIONS = _ZIP_EXTENSIONS | _GZIP_EXTENSIONS

# Unix file-type bits for a symlink, as stored in the high 16 bits of a
# ZIP entry's ``external_attr``. ``ZipInfo.is_symlink()`` only exists on
# newer CPython, so the mode is inspected directly to stay version-proof.
_S_IFLNK = 0o120000
_S_IFMT = 0o170000


def _zipinfo_is_symlink(info: zipfile.ZipInfo) -> bool:
    """True if this ZIP entry is a symlink rather than a regular file/dir."""
    return (info.external_attr >> 16) & _S_IFMT == _S_IFLNK


def _reject_unsafe_archive_member(name: str, *, is_symlink: bool = False) -> None:
    """Raise :class:`ReaderError` if ``name`` could write outside the extraction dir.

    A ZIP's entry names are attacker-controlled — a crafted archive can
    carry ``../../../etc/cron.d/x``, an absolute path, a Windows drive
    (``C:\\...``), or a symlink whose target escapes the sandbox
    ("zip-slip"). CPython's :meth:`zipfile.ZipFile.extract` sanitises
    ``..`` and leading slashes *silently* on modern versions, so without
    this guard a malicious entry is not blocked, merely quietly rewritten
    to land inside the temp dir and then parsed as data. Rejecting it
    outright — and refusing symlink entries, which ``extract`` does not
    neutralise consistently across platforms — is the defence the
    de-risking plan's Phase 1.8 calls for. Applied both when listing an
    archive's tables and again immediately before extraction.
    """
    if is_symlink:
        raise ReaderError(
            f"Refusing to read archive entry {name!r}: it is a symlink, "
            f"which could point outside the extraction directory."
        )
    normalised = name.replace("\\", "/")
    if (
        PurePosixPath(normalised).is_absolute()
        or ".." in PurePosixPath(normalised).parts
        or ":" in normalised.split("/", 1)[0]
    ):
        raise ReaderError(
            f"Refusing to read archive entry {name!r}: the path escapes "
            f"the extraction directory (absolute path, drive letter, or "
            f"'..' traversal component)."
        )


def _is_safe_archive_member(name: str) -> bool:
    """Boolean form of :func:`_reject_unsafe_archive_member` for list comprehensions.

    Used by :meth:`ArchiveReader.list_tables` to drop unsafe entries the
    same way it already drops entries no reader recognises — quietly,
    since a hostile entry alongside real data does not make the whole
    archive unreadable. :meth:`ArchiveReader.read` still calls the
    raising form so an explicit ``table_name`` request for such an entry
    gets a clear error rather than "no such entry".
    """
    try:
        _reject_unsafe_archive_member(name)
    except ReaderError:
        return False
    return True


def _is_within(child: Path, parent: Path) -> bool:
    """True if ``child`` resolves to a path inside ``parent`` (no escape via ``..``/symlink)."""
    try:
        return child.resolve().is_relative_to(parent.resolve())
    except OSError:
        return False


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
                names = [
                    info.filename
                    for info in archive.infolist()
                    if not info.is_dir()
                    and not _zipinfo_is_symlink(info)
                    and _is_safe_archive_member(info.filename)
                ]
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
        # Defence-in-depth: _gzip_inner_name only ever returns a single
        # path component (``path.stem``), so this cannot currently fire —
        # but it keeps the "an inner name is never trusted as a path"
        # rule uniform across both archive formats.
        _reject_unsafe_archive_member(inner_name)
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
        else:
            # An explicit request for a traversal/absolute/drive-letter
            # name gets this specific error rather than the generic "no
            # such entry" that list_tables()'s silent filtering (which
            # already dropped it from readable_names) would otherwise
            # produce.
            _reject_unsafe_archive_member(table_name)
            if table_name not in readable_names:
                raise ReaderError(
                    f"{path} has no readable entry named '{table_name}'. "
                    f"Available entries: {', '.join(readable_names)}."
                )

        try:
            with zipfile.ZipFile(path) as archive:
                # Re-check against the real ZipInfo now that we hold it:
                # the symlink bit is only visible here, and list_tables()
                # and this method open the file separately.
                _reject_unsafe_archive_member(
                    table_name,
                    is_symlink=_zipinfo_is_symlink(archive.getinfo(table_name)),
                )
                extracted_dir = Path(tempfile.mkdtemp())
                extracted_path = Path(archive.extract(table_name, path=extracted_dir))
        except (zipfile.BadZipFile, OSError) as exc:
            raise ReaderError(
                f"Failed to extract '{table_name}' from {path}: {exc}"
            ) from exc

        # Belt-and-suspenders: even if some future zipfile change let a
        # crafted name through the checks above, refuse to hand a path
        # outside the temp dir to a reader.
        if not _is_within(extracted_path, extracted_dir):
            shutil.rmtree(extracted_dir, ignore_errors=True)
            raise ReaderError(
                f"Refusing to read '{table_name}' from {path}: extraction "
                f"landed outside the temporary directory."
            )

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
        from uadas_core.readers.reader_registry import get_reader_for_path

        try:
            return get_reader_for_path(Path(inner_name))
        except ReaderError:
            return None

    @classmethod
    def _read_with_matching_reader(
        cls, extracted_path: Path, display_name: str
    ) -> Dataset:
        from uadas_core.readers.reader_registry import get_reader_for_path

        reader_class = get_reader_for_path(extracted_path)
        dataset = reader_class.read(extracted_path)
        # The extracted path is a temp file with no lasting meaning to
        # the user — restore the archive-relative name so the Dataset
        # Explorer shows "sales.csv" rather than an opaque temp path.
        dataset.name = Path(display_name).stem
        dataset.source_path = None
        return dataset

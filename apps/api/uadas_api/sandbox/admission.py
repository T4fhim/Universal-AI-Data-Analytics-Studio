# File: apps/api/uadas_api/sandbox/admission.py
"""File-type admission: the extension and the file's own bytes must agree, before any parse.

Why: the cheapest defence against a hostile upload is to refuse what is obviously not what it
claims, using nothing that could itself be exploited. This module therefore looks at (1) the
extension, (2) the first 8 KiB and last 8 bytes of the file against a small table of
signatures, (3) for zip-based formats the *central directory only* (entry count, declared
sizes, the member names that identify an office format). It never runs a reader and imports
no reader library; it is deliberately **not** ``python-magic``:
libmagic is itself a C parser of untrusted bytes (it would run in the web process, against the
rule this package exists to enforce) and has no wheel on Windows, so the same table behaves
identically on a laptop and in CI. Admission is a coarse filter -- the sandbox is the defence.

**The archive budgets are heuristics, not bounds.** A zip's central directory *declares* each
member's size, and the declaration is the attacker's to make: a file that lies passes the budget
and expands past it inside the reader. What actually bounds a decompression bomb is the child's
rlimits (``RLIMIT_AS`` for memory, ``RLIMIT_FSIZE`` for anything it writes, ``RLIMIT_CPU`` and
the parent's wall-clock kill), which hold whatever a header says. The budget exists to refuse the
honest, obvious bomb cheaply, before a child is started.

The extension set is not a second hand-kept list of readers: :data:`_RULES` is the API's
table of "what bytes does each extension need", and ``tests/test_sandbox_admission.py``
fails if its keys differ from the union of ``SUPPORTED_EXTENSIONS`` over the core's
``_BUILTIN_READERS`` in either direction (a reader added without a rule here, or a rule
without a reader).

Rejections raise :class:`~uadas_api.sandbox.errors.SandboxError` with a closed code
(``unsupported_type``, ``input_too_large``, ``decompression_bomb``) and never echo the file
name or any content.
"""

from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.sandbox.limits import MIB, SandboxLimits

_HEAD_BYTES = 8192
_TAIL_BYTES = 8
_PDF_WINDOW = 1024
# Below this much expanded data a high ratio alone is not suspicious (tiny files compress
# absurdly well); the absolute cap still applies.
_RATIO_FLOOR = 50 * MIB
_EOCD = b"PK\x05\x06"
_EOCD_SEARCH = 66_000  # a comment is at most 65535 bytes


class Family(StrEnum):
    """What a file's bytes say it is."""

    PDF = "pdf"
    ZIP = "zip"
    OLE = "ole"
    SQLITE = "sqlite"
    PARQUET = "parquet"
    FEATHER = "feather"
    PNG = "png"
    JPEG = "jpeg"
    BMP = "bmp"
    TIFF = "tiff"
    GZIP = "gzip"
    TEXT = "text"
    BINARY = "binary"


@dataclass(frozen=True)
class _Rule:
    families: frozenset[Family]
    # Extra check on the leading text: "json" | "xml" | "html" | "" (none).
    text_shape: str = ""
    # Extra check on a zip container: a member name, or "mimetype:<type>", or "" (any).
    container: str = ""
    # Whether the zip / gzip size budgets apply.
    archive: bool = False


_TEXT = frozenset({Family.TEXT})

# The one table. Keys are what the core's readers accept (lower case, with the dot).
_RULES: dict[str, _Rule] = {
    ".csv": _Rule(_TEXT),
    ".tsv": _Rule(_TEXT),
    ".txt": _Rule(_TEXT),
    ".json": _Rule(_TEXT, text_shape="json"),
    ".yaml": _Rule(_TEXT),
    ".yml": _Rule(_TEXT),
    ".xml": _Rule(_TEXT, text_shape="xml"),
    ".html": _Rule(_TEXT, text_shape="html"),
    ".htm": _Rule(_TEXT, text_shape="html"),
    ".pdf": _Rule(frozenset({Family.PDF})),
    ".xlsx": _Rule(frozenset({Family.ZIP}), container="xl/workbook.xml", archive=True),
    ".docx": _Rule(
        frozenset({Family.ZIP}), container="word/document.xml", archive=True
    ),
    ".pptx": _Rule(
        frozenset({Family.ZIP}), container="ppt/presentation.xml", archive=True
    ),
    ".ods": _Rule(
        frozenset({Family.ZIP}),
        container="mimetype:application/vnd.oasis.opendocument.spreadsheet",
        archive=True,
    ),
    ".zip": _Rule(frozenset({Family.ZIP}), archive=True),
    # ``.gz`` / ``.gzip`` are deliberately absent although the core's archive reader accepts them:
    # the sandbox names the input ``input<ext>``, so the reader sees an inner file called
    # ``input`` with no extension and can never pick a reader for it. Rather than admit a file that
    # always fails after being fetched and spooled, the API refuses it up front
    # (``NOT_ADMITTED_EXTENSIONS`` below, pinned by the parity test).
    ".xls": _Rule(frozenset({Family.OLE})),
    ".db": _Rule(frozenset({Family.SQLITE})),
    ".sqlite": _Rule(frozenset({Family.SQLITE})),
    ".sqlite3": _Rule(frozenset({Family.SQLITE})),
    ".parquet": _Rule(frozenset({Family.PARQUET})),
    ".feather": _Rule(frozenset({Family.FEATHER})),
    ".png": _Rule(frozenset({Family.PNG})),
    ".jpg": _Rule(frozenset({Family.JPEG})),
    ".jpeg": _Rule(frozenset({Family.JPEG})),
    ".bmp": _Rule(frozenset({Family.BMP})),
    ".tif": _Rule(frozenset({Family.TIFF})),
    ".tiff": _Rule(frozenset({Family.TIFF})),
}

# Signatures of binary formats that are *not* tables: recognised so that they are never
# mistaken for text, whatever their bytes look like.
# Each signature is long or specific enough that a CSV cannot plausibly start with it
# ("MZ" alone would be a legitimate first column header, so a DOS executable is recognised
# separately in :func:`detect_family`).
_OTHER_BINARY = (
    b"\x7fELF",
    b"\xca\xfe\xba\xbe",
    b"\xcf\xfa\xed\xfe",
    b"GIF87a",
    b"GIF89a",
    b"Rar!\x1a\x07",
    b"7z\xbc\xaf\x27\x1c",
    b"\xfd7zXZ\x00",
    b"OggS\x00",
    b"fLaC\x00",
)


# Extensions a core reader accepts that the API does not admit, and why (see ``_RULES``).
NOT_ADMITTED_EXTENSIONS: frozenset[str] = frozenset({".gz", ".gzip"})


def supported_extensions() -> frozenset[str]:
    """Every extension a file may be uploaded with (the readers' union; see the module docs)."""
    return frozenset(_RULES)


def check_extension(filename: str) -> str:
    """Return the lower-case extension of ``filename`` (``".csv"``) or refuse it.

    Only the last path component is considered (both separators: a client may send either),
    only its last suffix counts (``a.csv.exe`` is ``.exe``), and nothing is stripped (``a.pdf``
    followed by a space is not ``.pdf``). The name is not echoed in the refusal.
    """
    if not isinstance(filename, str):
        raise SandboxError(SandboxErrorCode.UNSUPPORTED_TYPE)
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, suffix = name.rpartition(".")
    if not dot or not stem or not suffix:
        raise SandboxError(SandboxErrorCode.UNSUPPORTED_TYPE)
    extension = f".{suffix.lower()}"
    if extension not in _RULES:
        raise SandboxError(SandboxErrorCode.UNSUPPORTED_TYPE)
    return extension


def _looks_like_text(head: bytes) -> bool:
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return len(head) % 2 == 0 or len(head) >= _HEAD_BYTES  # UTF-16 text
    if b"\x00" in head:
        return False
    suspicious = sum(
        1 for byte in head if byte < 9 or (13 < byte < 32 and byte != 27) or byte == 127
    )
    return suspicious * 50 <= len(head)  # at most 2 % control bytes


def detect_family(head: bytes, tail: bytes) -> Family:
    """Classify a file from its first bytes (``head``) and last bytes (``tail``)."""
    if b"%PDF-" in head[:_PDF_WINDOW]:
        return Family.PDF
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return Family.ZIP
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return Family.OLE
    if head.startswith(b"SQLite format 3\x00"):
        return Family.SQLITE
    if head.startswith(b"PAR1") and tail.endswith(b"PAR1"):
        return Family.PARQUET
    if head.startswith(b"ARROW1"):
        return Family.FEATHER
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Family.PNG
    if head.startswith(b"\xff\xd8\xff"):
        return Family.JPEG
    # "BM" is two ASCII letters; a text file may start with them. A bitmap's header has
    # four reserved zero bytes at offset 6.
    if head.startswith(b"BM") and head[6:10] == b"\x00\x00\x00\x00":
        return Family.BMP
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return Family.TIFF
    if head.startswith(b"\x1f\x8b"):
        return Family.GZIP
    if head.startswith(_OTHER_BINARY) or (
        head.startswith(b"MZ")
        and b"\x00" in head[2:64]  # a DOS/Windows executable header
    ):
        return Family.BINARY
    return Family.TEXT if _looks_like_text(head) else Family.BINARY


def _text_shape_ok(head: bytes, shape: str) -> bool:
    body = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if shape == "json":
        return (
            body[:1] in {b"{", b"[", b'"', b"-", b"t", b"f", b"n"} or body[:1].isdigit()
        )
    if shape == "xml":
        return body[:1] == b"<"
    if shape == "html":
        return b"<" in head
    return True


def _unsupported() -> SandboxError:
    return SandboxError(SandboxErrorCode.UNSUPPORTED_TYPE)


def _bomb() -> SandboxError:
    return SandboxError(SandboxErrorCode.DECOMPRESSION_BOMB)


def _check_budget(expanded: int, stored: int, limits: SandboxLimits) -> None:
    if expanded > limits.max_decompressed_bytes:
        raise _bomb()
    if expanded > _RATIO_FLOOR and expanded > limits.max_compression_ratio * max(
        stored, 1
    ):
        raise _bomb()


def _check_zip(path: Path, rule: _Rule, limits: SandboxLimits) -> None:
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(max(0, size - _EOCD_SEARCH))
        tail = handle.read()
    index = tail.rfind(_EOCD)
    if index < 0 or len(tail) < index + 22:
        raise _unsupported()
    (entries,) = struct.unpack_from("<H", tail, index + 10)
    # 0xFFFF marks a zip64 count we do not read; far above any sane office file either way.
    if entries == 0xFFFF or entries > limits.max_archive_entries:
        raise _bomb()
    if entries == 0:
        raise _unsupported()
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            _check_budget(sum(i.file_size for i in infos), size, limits)
            if rule.container.startswith("mimetype:"):
                wanted = rule.container.split(":", 1)[1].encode()
                try:
                    with archive.open("mimetype") as member:
                        declared = member.read(len(wanted) + 1)
                except KeyError:
                    raise _unsupported() from None
                if declared != wanted:
                    raise _unsupported()
            elif rule.container and rule.container not in {i.filename for i in infos}:
                raise _unsupported()
    except (zipfile.BadZipFile, EOFError, NotImplementedError, OSError, ValueError):
        raise _unsupported() from None


def check_content(path: Path, extension: str, limits: SandboxLimits) -> None:
    """Refuse the file at ``path`` unless its bytes match ``extension`` and its size is allowed.

    ``extension`` must come from :func:`check_extension`. Order: size first (a too-large file
    is never opened), then the signature, then the zip / gzip budgets. Raises
    :class:`~uadas_api.sandbox.errors.SandboxError`.
    """
    rule = _RULES.get(extension)
    if rule is None or path.is_symlink() or not path.is_file():
        raise _unsupported()
    size = path.stat().st_size
    if size == 0:
        raise _unsupported()
    if size > limits.max_input_bytes:
        raise SandboxError(SandboxErrorCode.INPUT_TOO_LARGE)
    with path.open("rb") as handle:
        head = handle.read(_HEAD_BYTES)
        handle.seek(max(0, size - _TAIL_BYTES))
        tail = handle.read(_TAIL_BYTES)
    family = detect_family(head, tail)
    if family not in rule.families:
        raise _unsupported()
    if family is Family.TEXT and not _text_shape_ok(head, rule.text_shape):
        raise _unsupported()
    if family is Family.ZIP:
        _check_zip(path, rule, limits)

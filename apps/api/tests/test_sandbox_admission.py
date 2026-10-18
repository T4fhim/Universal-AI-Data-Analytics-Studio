# File: apps/api/tests/test_sandbox_admission.py
"""File-type admission: extension AND content signature must agree, before anything is parsed.

Why: the sandbox contains a parser that goes wrong; admission keeps the obviously wrong
file from ever reaching it. A ``.csv`` that is really a PDF, a ``.pdf`` that is really text,
an executable renamed ``.xlsx`` and a zip that expands to a gigabyte are all stopped here,
by reading a few kilobytes and (for zip) the central directory -- never by running a reader.

Every rejection test has a positive twin below it (the same shape of file, correctly
named), so a guard that rejects everything cannot pass.

The extension set is not hand-maintained twice: ``test_supported_extensions_match_the_reader_registry``
imports the core's ``_BUILTIN_READERS`` (a test may; the web process may not) and fails when
the API's table and the registry disagree in either direction.
"""

from __future__ import annotations

import gzip
import io
import struct
import zipfile
from pathlib import Path

import pytest

from uadas_api.sandbox.admission import (
    NOT_ADMITTED_EXTENSIONS,
    check_content,
    check_extension,
    detect_family,
    supported_extensions,
)
from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.sandbox.limits import SandboxLimits

LIMITS = SandboxLimits()


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _zip(entries: dict[str, bytes], *, compress: bool = True) -> bytes:
    buffer = io.BytesIO()
    kind = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", kind) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _code(excinfo: pytest.ExceptionInfo[SandboxError]) -> SandboxErrorCode:
    return excinfo.value.code


# ------------------------------------------------------------ the registry parity


def test_supported_extensions_match_the_reader_registry() -> None:
    from uadas_core.readers.reader_registry import _BUILTIN_READERS

    registry = {
        ext.lower()
        for reader in _BUILTIN_READERS
        for ext in reader.SUPPORTED_EXTENSIONS
    }
    ours = set(supported_extensions())
    # What the registry reads and the API deliberately does not admit (listed, with the reason,
    # next to the rules table): both directions are still pinned.
    expected = registry - NOT_ADMITTED_EXTENSIONS
    assert ours == expected, (
        f"only in the API table: {sorted(ours - expected)}; "
        f"only in the registry: {sorted(expected - ours)}"
    )
    assert (
        registry >= NOT_ADMITTED_EXTENSIONS
    ), "a stale exclusion: the registry dropped it"
    assert not NOT_ADMITTED_EXTENSIONS & ours


def test_gzip_is_not_admitted_because_the_reader_could_never_pick_a_reader_for_input_dot_gz(
    tmp_path: Path,
) -> None:
    # Reject (the extension), with the positive twin: the same bytes inside a .zip are fine.
    for name in ("sales.csv.gz", "sales.gz", "sales.gzip"):
        with pytest.raises(SandboxError) as excinfo:
            check_extension(name)
        assert _code(excinfo) is SandboxErrorCode.UNSUPPORTED_TYPE
    assert check_extension("sales.zip") == ".zip"
    # And a gzip stream under an admitted extension is recognised as gzip, not as text.
    fake = _write(tmp_path, "g.csv", gzip.compress(b"a,b\n1,2\n"))
    with pytest.raises(SandboxError):
        check_content(fake, ".csv", SandboxLimits())


def test_every_extension_has_a_content_rule() -> None:
    # supported_extensions() is derived from the rules table, so this pins its shape.
    assert all(
        ext.startswith(".") and ext == ext.lower() for ext in supported_extensions()
    )


# ---------------------------------------------------------------- the extension


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("data.csv", ".csv"),
        ("DATA.CSV", ".csv"),
        ("report.final.xlsx", ".xlsx"),
        ("C:\\Users\\x\\table.tsv", ".tsv"),
        ("../../etc/archive.zip", ".zip"),
    ],
)
def test_a_listed_extension_is_admitted_whatever_the_path_around_it(
    filename: str, expected: str
) -> None:
    assert check_extension(filename) == expected


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "noextension",
        "x.exe",
        "x.csv.exe",
        "x.",
        ".csv.bak",
        "x.php",
        "x.pdf ",
        "x.sh",
    ],
)
def test_an_unlisted_or_missing_extension_is_refused(filename: str) -> None:
    with pytest.raises(SandboxError) as excinfo:
        check_extension(filename)
    assert _code(excinfo) is SandboxErrorCode.UNSUPPORTED_TYPE


def test_the_extension_check_never_echoes_the_filename() -> None:
    with pytest.raises(SandboxError) as excinfo:
        check_extension("secret-customer-name.exe")
    assert "secret" not in str(excinfo.value)


# ------------------------------------------------------------- family detection


@pytest.mark.parametrize(
    ("head", "family"),
    [
        (b"%PDF-1.7\n", "pdf"),
        (b"PK\x03\x04rest", "zip"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"),
        (b"SQLite format 3\x00", "sqlite"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xff\xd8\xff\xe0", "jpeg"),
        (b"\x1f\x8b\x08\x00", "gzip"),
        (b"a,b\n1,2\n", "text"),
        (b"MZ\x90\x00\x03\x00\x00\x00", "binary"),
        (b"\x7fELF\x02\x01\x01", "binary"),
    ],
)
def test_family_detection(head: bytes, family: str) -> None:
    assert detect_family(head, head).value == family


def test_text_that_merely_starts_with_bm_is_not_a_bitmap() -> None:
    assert detect_family(b"BMW,price\n1,2\n", b"").value == "text"


def test_a_bitmap_is_a_bitmap() -> None:
    header = b"BM" + struct.pack("<I", 100) + b"\x00\x00\x00\x00" + b"\x36\x00\x00\x00"
    assert detect_family(header, b"").value == "bmp"


def test_nul_bytes_make_text_binary() -> None:
    assert detect_family(b"a,b\x00\x00\x00\x00\x00,c\n", b"").value == "binary"


# ------------------------------------------------------- extension x content


def test_a_csv_that_is_a_pdf_is_refused_and_a_real_csv_is_admitted(
    tmp_path: Path,
) -> None:
    fake = _write(tmp_path, "a.csv", b"%PDF-1.4\n1 0 obj\n")
    with pytest.raises(SandboxError) as excinfo:
        check_content(fake, ".csv", LIMITS)
    assert _code(excinfo) is SandboxErrorCode.UNSUPPORTED_TYPE
    real = _write(tmp_path, "b.csv", b"a,b\n1,2\n")
    check_content(real, ".csv", LIMITS)


def test_a_pdf_that_is_text_is_refused_and_a_real_pdf_header_is_admitted(
    tmp_path: Path,
) -> None:
    fake = _write(tmp_path, "a.pdf", b"just some words\n")
    with pytest.raises(SandboxError) as excinfo:
        check_content(fake, ".pdf", LIMITS)
    assert _code(excinfo) is SandboxErrorCode.UNSUPPORTED_TYPE
    real = _write(tmp_path, "b.pdf", b"%PDF-1.4\n%garbage after a real header")
    check_content(real, ".pdf", LIMITS)


def test_a_pdf_header_within_the_first_kilobyte_is_admitted(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.pdf", b"\n" * 500 + b"%PDF-1.4\n")
    check_content(path, ".pdf", LIMITS)


def test_an_executable_renamed_xlsx_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.xlsx", b"MZ\x90\x00" + b"\x00" * 200)
    with pytest.raises(SandboxError) as excinfo:
        check_content(path, ".xlsx", LIMITS)
    assert _code(excinfo) is SandboxErrorCode.UNSUPPORTED_TYPE


def test_a_png_named_jpg_is_refused_and_a_jpeg_named_jpg_is_admitted(
    tmp_path: Path,
) -> None:
    wrong = _write(tmp_path, "a.jpg", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    with pytest.raises(SandboxError):
        check_content(wrong, ".jpg", LIMITS)
    right = _write(tmp_path, "b.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 32)
    check_content(right, ".jpg", LIMITS)


def test_json_and_xml_must_look_like_themselves(tmp_path: Path) -> None:
    check_content(_write(tmp_path, "a.json", b'{"a": [1, 2]}'), ".json", LIMITS)
    check_content(_write(tmp_path, "b.json", b"[1, 2]"), ".json", LIMITS)
    check_content(
        _write(tmp_path, "a.xml", b"<?xml version='1.0'?><r/>"), ".xml", LIMITS
    )
    check_content(_write(tmp_path, "b.xml", b"\xef\xbb\xbf<r/>"), ".xml", LIMITS)
    for name, ext in (("c.json", ".json"), ("c.xml", ".xml")):
        path = _write(tmp_path, name, b"plain words, not structured")
        with pytest.raises(SandboxError):
            check_content(path, ext, LIMITS)


def test_an_empty_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SandboxError) as excinfo:
        check_content(_write(tmp_path, "a.csv", b""), ".csv", LIMITS)
    assert _code(excinfo) is SandboxErrorCode.UNSUPPORTED_TYPE


def test_the_input_size_cap_is_checked_and_a_file_at_the_cap_is_admitted(
    tmp_path: Path,
) -> None:
    limits = SandboxLimits(max_input_bytes=64)
    ok = _write(tmp_path, "ok.csv", b"a,b\n" + b"1,2\n" * 15)  # exactly 64 bytes
    assert ok.stat().st_size == 64
    check_content(ok, ".csv", limits)
    big = _write(tmp_path, "big.csv", b"a,b\n" + b"1,2\n" * 16)
    with pytest.raises(SandboxError) as excinfo:
        check_content(big, ".csv", limits)
    assert _code(excinfo) is SandboxErrorCode.INPUT_TOO_LARGE


# ------------------------------------------------------------ zip containers


def test_xlsx_docx_pptx_ods_need_their_own_container_layout(tmp_path: Path) -> None:
    layouts = {
        ".xlsx": {"[Content_Types].xml": b"<x/>", "xl/workbook.xml": b"<x/>"},
        ".docx": {"[Content_Types].xml": b"<x/>", "word/document.xml": b"<x/>"},
        ".pptx": {"[Content_Types].xml": b"<x/>", "ppt/presentation.xml": b"<x/>"},
        ".ods": {
            "mimetype": b"application/vnd.oasis.opendocument.spreadsheet",
            "content.xml": b"<x/>",
        },
    }
    for ext, entries in layouts.items():
        good = _write(tmp_path, f"good{ext}", _zip(entries))
        check_content(good, ext, LIMITS)
    # the same zip under a different office extension is a mismatch
    wrong = _write(tmp_path, "wrong.docx", _zip(layouts[".xlsx"]))
    with pytest.raises(SandboxError) as excinfo:
        check_content(wrong, ".docx", LIMITS)
    assert _code(excinfo) is SandboxErrorCode.UNSUPPORTED_TYPE


def test_a_plain_zip_archive_is_admitted_and_a_truncated_zip_is_refused(
    tmp_path: Path,
) -> None:
    data = _zip({"inner.csv": b"a,b\n1,2\n"})
    check_content(_write(tmp_path, "ok.zip", data), ".zip", LIMITS)
    truncated = _write(tmp_path, "cut.zip", data[: len(data) // 2])
    with pytest.raises(SandboxError) as excinfo:
        check_content(truncated, ".zip", LIMITS)
    assert _code(excinfo) is SandboxErrorCode.UNSUPPORTED_TYPE


def test_a_zip_bomb_is_refused_by_declared_size_and_a_normal_archive_is_not(
    tmp_path: Path,
) -> None:
    limits = SandboxLimits(max_decompressed_bytes=10 * 1024 * 1024)
    bomb = _write(
        tmp_path,
        "bomb.xlsx",
        _zip(
            {
                "[Content_Types].xml": b"<x/>",
                "xl/workbook.xml": b"<x/>",
                "xl/worksheets/sheet1.xml": b"0" * (40 * 1024 * 1024),
            }
        ),
    )
    assert bomb.stat().st_size < 1024 * 1024  # a megabyte of zip, forty of content
    with pytest.raises(SandboxError) as excinfo:
        check_content(bomb, ".xlsx", limits)
    assert _code(excinfo) is SandboxErrorCode.DECOMPRESSION_BOMB
    modest = _write(
        tmp_path,
        "ok.xlsx",
        _zip(
            {
                "[Content_Types].xml": b"<x/>",
                "xl/workbook.xml": b"<x/>",
                "xl/worksheets/sheet1.xml": b"0" * (1024 * 1024),
            }
        ),
    )
    check_content(modest, ".xlsx", limits)


def test_a_high_ratio_inside_the_size_cap_is_still_a_bomb(tmp_path: Path) -> None:
    limits = SandboxLimits(max_decompressed_bytes=1024**3, max_compression_ratio=50)
    bomb = _write(tmp_path, "r.zip", _zip({"z.csv": b"0" * (60 * 1024 * 1024)}))
    with pytest.raises(SandboxError) as excinfo:
        check_content(bomb, ".zip", limits)
    assert _code(excinfo) is SandboxErrorCode.DECOMPRESSION_BOMB


def test_a_zip_with_too_many_entries_is_refused_without_listing_them(
    tmp_path: Path,
) -> None:
    limits = SandboxLimits(max_archive_entries=50)
    many = _write(tmp_path, "many.zip", _zip({f"f{i}.csv": b"a\n" for i in range(200)}))
    with pytest.raises(SandboxError) as excinfo:
        check_content(many, ".zip", limits)
    assert _code(excinfo) is SandboxErrorCode.DECOMPRESSION_BOMB
    few = _write(tmp_path, "few.zip", _zip({f"f{i}.csv": b"a\n" for i in range(10)}))
    check_content(few, ".zip", limits)


def test_a_zip_that_lies_about_its_sizes_passes_the_budget_which_is_why_it_is_only_a_heuristic(
    tmp_path: Path,
) -> None:
    # Said as a test, not just in a docstring: the budget reads declared sizes, and a file can
    # declare small and expand large. The real bound is the child's rlimits (test_sandbox_malformed
    # drives a memory bomb and a disk bomb through the real child).
    honest = _zip({"big.csv": b"0" * (6 * 1024 * 1024)})
    limits = SandboxLimits(max_decompressed_bytes=1 * 1024 * 1024)
    with pytest.raises(SandboxError):  # declared 6 MiB > 1 MiB: refused
        check_content(_write(tmp_path, "honest.zip", honest), ".zip", limits)
    # Rewrite the central-directory 'uncompressed size' of the single member to 100 bytes.
    forged = bytearray(honest)
    index = forged.rfind(b"PK\x01\x02")
    struct.pack_into("<I", forged, index + 24, 100)
    check_content(
        _write(tmp_path, "forged.zip", bytes(forged)), ".zip", limits
    )  # admitted


# ----------------------------------------------------- binary table formats


def test_sqlite_parquet_feather_ole_need_their_signatures(tmp_path: Path) -> None:
    good = {
        ".sqlite": b"SQLite format 3\x00" + b"\x00" * 100,
        ".db": b"SQLite format 3\x00" + b"\x00" * 100,
        ".parquet": b"PAR1" + b"\x00" * 20 + b"PAR1",
        ".feather": b"ARROW1\x00\x00" + b"\x00" * 20,
        ".xls": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,
    }
    for ext, data in good.items():
        check_content(_write(tmp_path, f"good{ext}", data), ext, LIMITS)
        with pytest.raises(SandboxError):
            check_content(
                _write(tmp_path, f"bad{ext}", b"text, not binary\n"), ext, LIMITS
            )


def test_a_parquet_without_its_trailing_magic_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, "cut.parquet", b"PAR1" + b"\x00" * 40)
    with pytest.raises(SandboxError):
        check_content(path, ".parquet", LIMITS)


# (That admission imports no reader library is proved in a fresh interpreter by
# test_sandbox_boundary.py: a check on this process's sys.modules would depend on which
# other tests ran first.)

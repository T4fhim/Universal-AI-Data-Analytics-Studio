# File: apps/api/tests/test_sandbox_malformed.py
"""The required malformed-file set, run against the real sandbox child.

Each case is a *file* that goes wrong in a different way, and each must fail safe, which is
checked the same way every time (:func:`assert_fails_safe`):

1. the parent (this process) survives and returns a :class:`SandboxError` with the *right*
   closed code, whose message is the fixed sentence for that code;
2. no private temp directory is left behind;
3. **a following good file still parses** -- the positive twin that proves the failure was the
   file's doing and the harness is healthy.

Two kinds of "bad file":

* Real files through the real readers (truncated PDF, XML entity bombs, XXE, a YAML alias
  bomb, an oversized table).
* Files that drive a *stand-in parser with a bug* (``sandbox_launcher.py``): there is no
  shipped reader that opens a socket, forks or allocates without bound on demand, so the
  launcher runs the production child with a reader whose behaviour is read from the input
  file. The guards, the classification and the supervision are all production code.

Memory, CPU, process and file-size limits are Linux-only guarantees (see ``guards.py``); those
cases skip locally on Windows with that reason and ``test_sandbox_ci_guard.py`` fails CI if
any of them skipped there. The timeout, socket, crash, output-size and every real-reader case
run on every platform.
"""

from __future__ import annotations

import io
import socket
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from sandbox_support import linux_only, needs_non_root

from uadas_api.sandbox.errors import MESSAGES, SandboxError, SandboxErrorCode
from uadas_api.sandbox.limits import GIB, MIB, SandboxLimits, limits_enforceable
from uadas_api.sandbox.runner import SandboxResult, SandboxWorkspace

HERE = Path(__file__).resolve().parent
LAUNCHER = [sys.executable, "-I", str(HERE / "sandbox_launcher.py")]


GOOD_CSV = b"name,qty\nwidget,3\ngadget,5\n"


@pytest.fixture
def work(tmp_path: Path) -> Path:
    root = tmp_path / "sandbox-work"
    root.mkdir()
    return root


def make_limits(work: Path, **overrides: Any) -> SandboxLimits:
    defaults: dict[str, Any] = {"tmp_root": str(work), "wall_seconds": 90.0}
    return SandboxLimits(**{**defaults, **overrides})


def parse(
    work: Path,
    extension: str,
    data: bytes,
    *,
    command: list[str] | None = None,
    **limit_overrides: Any,
) -> tuple[SandboxResult, bytes]:
    """Parse ``data``; return the result and the Parquet bytes (read before cleanup)."""
    workspace = SandboxWorkspace(
        make_limits(work, **limit_overrides), child_command=command
    )
    with workspace:
        workspace.input_path(extension).write_bytes(data)
        result = workspace.parse(extension)
        with result.open_output() as handle:
            return result, handle.read()


def frame_of(parquet: bytes) -> Any:
    import pandas as pd  # type: ignore[import-untyped]

    return pd.read_parquet(io.BytesIO(parquet))


def assert_fails_safe(
    work: Path,
    extension: str,
    data: bytes,
    expected: SandboxErrorCode | set[SandboxErrorCode],
    *,
    command: list[str] | None = None,
    **limit_overrides: Any,
) -> SandboxError:
    allowed = {expected} if isinstance(expected, SandboxErrorCode) else expected
    with pytest.raises(SandboxError) as excinfo:
        parse(work, extension, data, command=command, **limit_overrides)
    error = excinfo.value
    assert error.code in allowed, f"got {error.code}, expected one of {sorted(allowed)}"
    assert (
        str(error) == MESSAGES[error.code]
    )  # the fixed sentence, nothing from the file
    assert list(work.iterdir()) == [], "the sandbox left a temp directory behind"
    # The positive twin: the very next, good file parses.
    result, parquet = parse(work, ".csv", GOOD_CSV)
    assert (result.row_count, result.column_count) == (2, 2)
    assert frame_of(parquet)["name"].tolist() == ["widget", "gadget"]
    assert list(work.iterdir()) == []
    return error


# ------------------------------------------------------------------- good files


def test_a_good_csv_becomes_a_readable_parquet_table(work: Path) -> None:
    result, parquet = parse(work, ".csv", GOOD_CSV)
    frame = frame_of(parquet)
    assert frame.to_dict("list") == {"name": ["widget", "gadget"], "qty": [3, 5]}
    assert result.source_format == "csv"
    assert result.columns == (("name", "object"), ("qty", "int64"))
    assert result.sha256 and result.size == len(parquet)
    assert list(work.iterdir()) == []


def test_a_good_xlsx_parses(work: Path) -> None:
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["city", "pop"])
    sheet.append(["Oslo", 700])
    sheet.append(["Bergen", 290])
    buffer = io.BytesIO()
    book.save(buffer)
    result, parquet = parse(work, ".xlsx", buffer.getvalue())
    assert frame_of(parquet)["city"].tolist() == ["Oslo", "Bergen"]
    assert result.source_format == "xlsx"


def test_a_good_docx_table_parses(work: Path) -> None:
    import docx

    document = docx.Document()
    table = document.add_table(rows=3, cols=2)
    for row, (a, b) in enumerate([("k", "v"), ("x", "1"), ("y", "2")]):
        table.cell(row, 0).text = a
        table.cell(row, 1).text = b
    buffer = io.BytesIO()
    document.save(buffer)
    result, parquet = parse(work, ".docx", buffer.getvalue())
    assert result.row_count == 2
    assert frame_of(parquet).shape == (2, 2)


@pytest.mark.skipif(limits_enforceable(), reason="Windows/macOS honesty twin")
def test_where_limits_cannot_apply_the_result_says_so(work: Path) -> None:
    result, _ = parse(work, ".csv", GOOD_CSV)
    assert result.limits_enforced is False
    assert (
        result.enforcement["network_guard"] is True
    )  # the part that does work everywhere


@linux_only
def test_on_linux_the_limits_really_applied(work: Path) -> None:
    result, _ = parse(work, ".csv", GOOD_CSV)
    assert result.limits_enforced is True
    assert all(
        result.enforcement[k] for k in ("core", "memory", "cpu", "fsize", "nofile")
    )


# ------------------------------------------------------------ malformed documents


@pytest.mark.parametrize(
    "document",
    [
        b"%PDF-1.4\n",
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pa",
        b"%PDF-1.4\n"
        + b"\xff\xfe\x00junk" * 400
        + b"\ntrailer\n<< /Root 1 0 R >>\nstartxref\n9999\n%%EOF",
        b"%PDF-1.4\n1 0 obj\n<< /Length 99999999 >>\nstream\nabc",
    ],
    ids=[
        "header-only",
        "truncated-catalog",
        "junk-with-fake-trailer",
        "lying-stream-length",
    ],
)
def test_a_malformed_or_truncated_pdf_fails_safe(work: Path, document: bytes) -> None:
    assert_fails_safe(
        work,
        ".pdf",
        document,
        {SandboxErrorCode.PARSE_ERROR},
    )


def test_a_billion_laughs_xml_fails_safe_or_is_harmless(work: Path) -> None:
    levels = ['<!ENTITY lol0 "lol">']
    for n in range(1, 10):
        previous = f"&lol{n - 1};" * 10
        levels.append(f'<!ENTITY lol{n} "{previous}">')
    bomb = (
        "<?xml version='1.0'?><!DOCTYPE lolz [" + "".join(levels) + "]>"
        "<r><i><a>&lol9;</a></i><i><a>&lol9;</a></i></r>"
    ).encode()
    try:
        result, parquet = parse(
            work, ".xml", bomb, wall_seconds=60, memory_bytes=1 * GIB
        )
    except SandboxError as error:
        assert error.code in {
            SandboxErrorCode.PARSE_ERROR,
            SandboxErrorCode.MEMORY_LIMIT,
            SandboxErrorCode.TIMEOUT,
        }
        assert list(work.iterdir()) == []
    else:
        # The parser refused to expand it: nothing close to 10**9 characters came out.
        assert (
            max(len(str(v)) for v in frame_of(parquet).to_numpy().ravel()) < 1_000_000
        )
    result, _ = parse(work, ".csv", GOOD_CSV)  # the positive twin
    assert result.row_count == 2


def test_an_xxe_document_cannot_read_a_local_file(work: Path, tmp_path: Path) -> None:
    secret = tmp_path / "tenant-secret.txt"
    secret.write_text("TOP-SECRET-MARKER-4471")
    xxe = (
        f"<?xml version='1.0'?><!DOCTYPE r [<!ENTITY x SYSTEM '{secret.as_uri()}'>]>"
        "<r><i><a>&x;</a></i><i><a>&x;</a></i></r>"
    ).encode()
    try:
        _, parquet = parse(work, ".xml", xxe)
    except SandboxError as error:
        assert error.code is SandboxErrorCode.PARSE_ERROR
    else:
        assert b"TOP-SECRET-MARKER-4471" not in parquet
        assert "TOP-SECRET-MARKER-4471" not in frame_of(parquet).to_csv()
    # Positive twin: the same document without the entity reference is read normally, so the
    # absence of the secret above is the parser's refusal and not a broken harness.
    plain = b"<?xml version='1.0'?><r><i><a>fine</a></i><i><a>also</a></i></r>"
    _, parquet = parse(work, ".xml", plain)
    assert frame_of(parquet)["a"].tolist() == ["fine", "also"]


# ------------------------------------------------------------------- resource bombs


def test_a_slow_parse_is_stopped_by_the_wall_clock_and_the_next_file_parses(
    work: Path,
) -> None:
    assert_fails_safe(
        work,
        ".csv",
        b"spin",
        SandboxErrorCode.TIMEOUT,
        command=LAUNCHER,
        wall_seconds=3,
    )


def test_an_infinite_sleep_is_stopped_by_the_wall_clock(work: Path) -> None:
    assert_fails_safe(
        work,
        ".csv",
        b"sleep",
        SandboxErrorCode.TIMEOUT,
        command=LAUNCHER,
        wall_seconds=3,
    )


def test_a_benign_run_through_the_launcher_succeeds(work: Path) -> None:
    # The positive twin of every launcher-driven case below: the harness itself works.
    result, parquet = parse(work, ".csv", b"benign", command=LAUNCHER)
    assert result.row_count == 3
    assert frame_of(parquet)["b"].tolist() == ["x", "y", "z"]


@linux_only
def test_a_memory_bomb_hits_the_address_space_limit(work: Path) -> None:
    assert_fails_safe(
        work,
        ".csv",
        f"alloc {16 * GIB}".encode(),
        SandboxErrorCode.MEMORY_LIMIT,
        command=LAUNCHER,
        memory_bytes=1 * GIB,
    )
    # twin: a modest allocation under the same cap is fine
    result, _ = parse(
        work,
        ".csv",
        f"alloc {32 * MIB}".encode(),
        command=LAUNCHER,
        memory_bytes=1 * GIB,
    )
    assert result.row_count == 3


@linux_only
def test_a_yaml_alias_bomb_hits_a_resource_limit(work: Path) -> None:
    # Nine levels of ten-way aliases: a ~300-byte file that expands to 10**9 nodes.
    lines = ["a0: &a0 [x, x, x, x, x, x, x, x, x, x]"]
    for n in range(1, 10):
        refs = ", ".join([f"*a{n - 1}"] * 10)
        lines.append(f"a{n}: &a{n} [{refs}]")
    bomb = ("\n".join(lines) + "\n").encode()
    assert_fails_safe(
        work,
        ".yaml",
        bomb,
        {
            SandboxErrorCode.MEMORY_LIMIT,
            SandboxErrorCode.CPU_LIMIT,
            SandboxErrorCode.TIMEOUT,
            SandboxErrorCode.PARSE_ERROR,
        },
        memory_bytes=768 * MIB,
        cpu_seconds=20,
        wall_seconds=60,
    )


@linux_only
def test_a_cpu_hog_is_killed_by_the_cpu_limit(work: Path) -> None:
    assert_fails_safe(
        work,
        ".csv",
        b"spin",
        SandboxErrorCode.CPU_LIMIT,
        command=LAUNCHER,
        cpu_seconds=2,
        wall_seconds=60,
    )


def test_an_output_over_the_cap_is_refused_and_the_same_file_under_the_cap_is_fine(
    work: Path,
) -> None:
    big = b"id,payload\n" + b"".join(
        f"{i},{'x' * 40}\n".encode() for i in range(20_000)
    )
    assert_fails_safe(
        work, ".csv", big, SandboxErrorCode.OUTPUT_TOO_LARGE, max_output_bytes=4096
    )
    result, _ = parse(work, ".csv", big, max_output_bytes=64 * MIB)
    assert result.row_count == 20_000


def test_a_table_with_too_many_rows_or_columns_is_refused(work: Path) -> None:
    rows = b"a\n" + b"1\n" * 500
    assert_fails_safe(work, ".csv", rows, SandboxErrorCode.TOO_MANY_ROWS, max_rows=100)
    wide = (
        ",".join(f"c{i}" for i in range(50)).encode()
        + b"\n"
        + b",".join([b"1"] * 50)
        + b"\n"
    )
    assert_fails_safe(
        work, ".csv", wide, SandboxErrorCode.TOO_MANY_COLUMNS, max_columns=10
    )
    result, _ = parse(work, ".csv", rows, max_rows=500)  # exactly at the cap passes
    assert result.row_count == 500


# ------------------------------------------------------------- hostile behaviour


@pytest.fixture
def listener() -> Any:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    server.settimeout(0.5)
    yield server
    server.close()


def _nobody_connected(server: socket.socket) -> bool:
    try:
        server.accept()
    except TimeoutError:
        return True
    return False


def test_a_file_that_opens_a_network_socket_is_blocked(
    work: Path, listener: socket.socket
) -> None:
    port = listener.getsockname()[1]
    assert_fails_safe(
        work,
        ".csv",
        f"socket {port}".encode(),
        SandboxErrorCode.BLOCKED_OPERATION,
        command=LAUNCHER,
    )
    assert _nobody_connected(
        listener
    ), "the sandboxed reader reached the listening server"


def test_a_reader_that_swallows_the_blocked_socket_still_fails_the_parse(
    work: Path, listener: socket.socket
) -> None:
    port = listener.getsockname()[1]
    assert_fails_safe(
        work,
        ".csv",
        f"swallow_socket {port}".encode(),
        SandboxErrorCode.BLOCKED_OPERATION,
        command=LAUNCHER,
    )
    assert _nobody_connected(listener)


@pytest.mark.parametrize("verb", ["dns", "tcp_listen"])
def test_name_resolution_and_listening_are_blocked_too(work: Path, verb: str) -> None:
    assert_fails_safe(
        work,
        ".csv",
        verb.encode(),
        SandboxErrorCode.BLOCKED_OPERATION,
        command=LAUNCHER,
    )


@linux_only
@needs_non_root
def test_a_fork_attempt_is_limited_by_the_process_cap(work: Path) -> None:
    assert_fails_safe(
        work,
        ".csv",
        b"fork",
        SandboxErrorCode.RESOURCE_LIMIT,
        command=LAUNCHER,
        process_headroom=24,
        wall_seconds=60,
    )


def test_a_crashing_parser_is_reported_as_crashed(work: Path) -> None:
    assert_fails_safe(
        work, ".csv", b"crash", SandboxErrorCode.SANDBOX_CRASHED, command=LAUNCHER
    )


def test_a_parser_that_exits_without_replying_is_reported_as_crashed(
    work: Path,
) -> None:
    assert_fails_safe(
        work, ".csv", b"exit 7", SandboxErrorCode.SANDBOX_CRASHED, command=LAUNCHER
    )


def test_an_unexpected_parser_exception_is_a_parse_error_with_no_text(
    work: Path,
) -> None:
    error = assert_fails_safe(
        work, ".csv", b"nonsense-verb", SandboxErrorCode.PARSE_ERROR, command=LAUNCHER
    )
    assert "nonsense" not in str(error)


# --------------------------------------------------------- a zip that lies about size


def test_an_office_zip_is_still_parsed_inside_the_sandbox_when_admission_is_bypassed(
    work: Path,
) -> None:
    """The parser sees the file even without admission, and still fails safe.

    ``admission`` normally stops a zip bomb before any child exists; this calls the runner
    directly with a truncated workbook to show the sandbox is a second, independent line.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<x/>")
        archive.writestr("xl/workbook.xml", "<x/>")
        archive.writestr("xl/worksheets/sheet1.xml", "0" * 100_000)
    assert_fails_safe(
        work, ".xlsx", buffer.getvalue()[:-40], SandboxErrorCode.PARSE_ERROR
    )

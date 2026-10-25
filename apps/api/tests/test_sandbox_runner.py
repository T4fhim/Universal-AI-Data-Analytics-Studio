# File: apps/api/tests/test_sandbox_runner.py
"""The parent side of the sandbox: spawning, supervising, killing and verifying.

Why fake children: the runner's job is to survive a child that misbehaves -- hangs, spams,
crashes, lies, leaves grandchildren behind, plants a symlink -- and a real reader cannot be
made to do each of those on demand. ``child_command`` (an internal seam, not reachable from
settings or a request) swaps the real child for a small script so each failure is produced
deterministically. The real child, with real readers and real malformed files, is exercised in
``test_sandbox_malformed.py``.

Each failure test has a positive twin (the same fake, behaving), so the failure path cannot be
passing because the harness itself is broken.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.sandbox.limits import SandboxLimits
from uadas_api.sandbox.runner import SandboxWorkspace

PARQUET_BYTES = b"PAR1" + b"\x00" * 64 + b"PAR1"
GOOD_REPLY = (
    '{"ok": true, "source_format": "csv", "row_count": 3, "column_count": 2,'
    ' "columns": [["a", "int64"], ["b", "object"]], "warning_count": 0,'
    ' "enforcement": {"memory": true, "cpu": true, "fsize": true, "nproc": true,'
    ' "network_guard": true}}'
)

FakeChild = Callable[..., list[str]]


@pytest.fixture
def fake_child(tmp_path: Path) -> FakeChild:
    """Return ``make(body)``: a command that runs ``body`` (Python) as the 'child'."""
    counter = iter(range(1000))

    def make(body: str) -> list[str]:
        script = tmp_path / f"fake_child_{next(counter)}.py"
        script.write_text(
            "import json, os, sys, time\n" + textwrap.dedent(body), encoding="utf-8"
        )
        return [sys.executable, "-I", str(script)]

    return make


def _workspace(
    tmp_path: Path,
    command: list[str],
    *,
    limits: SandboxLimits | None = None,
    require_enforcement: bool = False,
) -> SandboxWorkspace:
    return SandboxWorkspace(
        limits or SandboxLimits(tmp_root=str(tmp_path / "work"), wall_seconds=20),
        child_command=command,
        require_enforcement=require_enforcement,
    )


@pytest.fixture(autouse=True)
def _work_root(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir()


def _leftovers(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in (tmp_path / "work").iterdir())


def _put_input(workspace: SandboxWorkspace, data: bytes = b"a,b\n1,2\n") -> None:
    workspace.input_path(".csv").write_bytes(data)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie (killed, not yet reaped by init) still answers signal 0.
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as handle:
            return handle.read().split(") ", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _code(excinfo: pytest.ExceptionInfo[SandboxError]) -> SandboxErrorCode:
    return excinfo.value.code


GOOD_BODY = f"""
sys.stdin.buffer.read()
open("out.parquet", "wb").write({PARQUET_BYTES!r})
print({GOOD_REPLY!r})
"""


# ---------------------------------------------------------------- the happy path


def test_a_well_behaved_child_yields_a_verified_result(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    with _workspace(tmp_path, fake_child(GOOD_BODY)) as workspace:
        _put_input(workspace)
        result = workspace.parse(".csv")
        assert (result.row_count, result.column_count) == (3, 2)
        assert result.source_format == "csv"
        assert result.columns == (("a", "int64"), ("b", "object"))
        assert result.size == len(PARQUET_BYTES)
        assert result.sha256 == hashlib.sha256(PARQUET_BYTES).hexdigest()
        with result.open_output() as handle:
            assert handle.read() == PARQUET_BYTES
    assert _leftovers(tmp_path) == []  # the temp dir is gone


def test_the_workspace_directory_is_private_and_starts_empty(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    with _workspace(tmp_path, fake_child(GOOD_BODY)) as workspace:
        assert list(workspace.path.iterdir()) == []
        assert workspace.path.parent == tmp_path / "work"
        if os.name == "posix":
            assert (workspace.path.stat().st_mode & 0o777) == 0o700


def test_the_child_runs_in_the_workspace_with_a_minimal_environment(
    tmp_path: Path,
    fake_child: FakeChild,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DJANGO_SECRET_KEY", "super-secret-value")
    monkeypatch.setenv("STORAGE_SECRET_ACCESS_KEY", "another-secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    body = f"""
    sys.stdin.buffer.read()
    report = {{"cwd": os.getcwd(), "env": sorted(os.environ)}}
    open("seen.json", "w").write(json.dumps(report))
    open("out.parquet", "wb").write({PARQUET_BYTES!r})
    print({GOOD_REPLY!r})
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        workspace.parse(".csv")
        import json

        seen = json.loads((workspace.path / "seen.json").read_text())
        assert os.path.samefile(seen["cwd"], workspace.path)
        env_names = set(seen["env"])
        assert not any(
            "SECRET" in name or name in {"DATABASE_URL", "DJANGO_SETTINGS_MODULE"}
            for name in env_names
        ), env_names
        # a positive twin: the variables it *should* have are there
        assert {"PATH", "TMPDIR", "TEMP", "TMP", "HOME"} <= {
            n.upper() for n in env_names
        }


def test_the_childs_temp_directory_is_its_own_workspace(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = f"""
    import tempfile
    sys.stdin.buffer.read()
    open("tmpdir.txt", "w").write(tempfile.gettempdir())
    open("out.parquet", "wb").write({PARQUET_BYTES!r})
    print({GOOD_REPLY!r})
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        workspace.parse(".csv")
        used = Path((workspace.path / "tmpdir.txt").read_text())
        assert os.path.samefile(used, workspace.path)


# ------------------------------------------------------------- misbehaving childs


def test_a_child_that_prints_garbage_is_a_protocol_error(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = """
    sys.stdin.buffer.read()
    print("this is not json at all")
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.PROTOCOL_ERROR
    assert _leftovers(tmp_path) == []


def test_a_child_that_exits_silently_is_a_protocol_error(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    with _workspace(tmp_path, fake_child("sys.stdin.buffer.read()\n")) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.PROTOCOL_ERROR


def test_a_child_that_crashes_is_reported_as_crashed_and_its_stderr_is_not_shown(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = """
    sys.stdin.buffer.read()
    sys.stderr.write("Traceback: C:/tenant-b/secrets/customers.csv row 7: Alice Smith\\n")
    os._exit(3)
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.SANDBOX_CRASHED
    for leaked in ("tenant-b", "Alice", "customers", "Traceback"):
        assert leaked not in str(excinfo.value)
        assert leaked not in repr(excinfo.value)


def test_a_reported_failure_keeps_its_code(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = """
    sys.stdin.buffer.read()
    print(json.dumps({"ok": False, "code": "memory_limit"}))
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.MEMORY_LIMIT


def test_a_made_up_failure_code_becomes_a_protocol_error(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = """
    sys.stdin.buffer.read()
    print(json.dumps({"ok": False, "code": "Traceback (most recent call last): secret"}))
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.PROTOCOL_ERROR
    assert "secret" not in str(excinfo.value)


def test_an_oversized_reply_is_cut_off_and_the_child_is_killed(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = """
    sys.stdin.buffer.read()
    chunk = "x" * 65536
    while True:
        sys.stdout.write(chunk)
        sys.stdout.flush()
    """
    limits = SandboxLimits(
        tmp_root=str(tmp_path / "work"), wall_seconds=30, max_response_bytes=64 * 1024
    )
    started = time.monotonic()
    with _workspace(tmp_path, fake_child(body), limits=limits) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.PROTOCOL_ERROR
    assert time.monotonic() - started < 15  # killed for spamming, not left to time out


def test_a_reply_exactly_at_the_cap_is_accepted(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    # Positive twin of the oversize test: the same cap, a reply that fits.
    limits = SandboxLimits(
        tmp_root=str(tmp_path / "work"),
        wall_seconds=20,
        max_response_bytes=len(GOOD_REPLY) + 2,
    )
    with _workspace(tmp_path, fake_child(GOOD_BODY), limits=limits) as workspace:
        _put_input(workspace)
        assert workspace.parse(".csv").row_count == 3


def test_a_hanging_child_is_killed_at_the_timeout_and_the_parent_survives(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = """
    sys.stdin.buffer.read()
    while True:
        time.sleep(0.1)
    """
    limits = SandboxLimits(tmp_root=str(tmp_path / "work"), wall_seconds=1.5)
    started = time.monotonic()
    with _workspace(tmp_path, fake_child(body), limits=limits) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    elapsed = time.monotonic() - started
    assert _code(excinfo) is SandboxErrorCode.TIMEOUT
    assert 1.4 <= elapsed < 12
    assert _leftovers(tmp_path) == []


def test_the_whole_process_tree_dies_with_a_timed_out_child(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    pid_file = tmp_path / "grandchild.pid"
    body = f"""
    import subprocess
    sys.stdin.buffer.read()
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    open({str(pid_file)!r}, "w").write(str(grandchild.pid))
    while True:
        time.sleep(0.1)
    """
    limits = SandboxLimits(tmp_root=str(tmp_path / "work"), wall_seconds=3)
    with _workspace(tmp_path, fake_child(body), limits=limits) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.TIMEOUT
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _pid_alive(pid), "a grandchild outlived the sandbox"


def test_grandchildren_are_also_killed_after_a_normal_exit(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    pid_file = tmp_path / "orphan.pid"
    body = f"""
    import subprocess
    sys.stdin.buffer.read()
    orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    open({str(pid_file)!r}, "w").write(str(orphan.pid))
    open("out.parquet", "wb").write({PARQUET_BYTES!r})
    print({GOOD_REPLY!r})
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        workspace.parse(".csv")
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _pid_alive(pid), "an orphaned grandchild survived a successful parse"


def test_a_missing_child_program_is_sandbox_unavailable(tmp_path: Path) -> None:
    command = [str(tmp_path / "no-such-python"), "-I", "x.py"]
    with _workspace(tmp_path, command) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.SANDBOX_UNAVAILABLE
    assert excinfo.value.retryable


# ------------------------------------------------------------ the output is checked


def test_a_claimed_success_without_an_output_file_is_a_protocol_error(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = f"""
    sys.stdin.buffer.read()
    print({GOOD_REPLY!r})
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.PROTOCOL_ERROR


def test_an_output_that_is_not_parquet_is_refused(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = f"""
    sys.stdin.buffer.read()
    open("out.parquet", "wb").write(b"#!/bin/sh\\nrm -rf /\\n")
    print({GOOD_REPLY!r})
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.PROTOCOL_ERROR


def test_an_output_over_the_cap_is_output_too_large_and_one_at_the_cap_is_fine(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = f"""
    sys.stdin.buffer.read()
    open("out.parquet", "wb").write({PARQUET_BYTES!r})
    print({GOOD_REPLY!r})
    """
    exact = SandboxLimits(
        tmp_root=str(tmp_path / "work"),
        wall_seconds=20,
        max_output_bytes=len(PARQUET_BYTES),
    )
    with _workspace(tmp_path, fake_child(body), limits=exact) as workspace:
        _put_input(workspace)
        assert workspace.parse(".csv").size == len(PARQUET_BYTES)
    tight = SandboxLimits(
        tmp_root=str(tmp_path / "work"),
        wall_seconds=20,
        max_output_bytes=len(PARQUET_BYTES) - 1,
    )
    with _workspace(tmp_path, fake_child(body), limits=tight) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.OUTPUT_TOO_LARGE


def test_claimed_row_and_column_counts_are_capped_and_counts_at_the_cap_pass(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    ok_limits = SandboxLimits(
        tmp_root=str(tmp_path / "work"), wall_seconds=20, max_rows=3, max_columns=2
    )
    with _workspace(tmp_path, fake_child(GOOD_BODY), limits=ok_limits) as workspace:
        _put_input(workspace)
        workspace.parse(".csv")
    for field, code in (
        ({"max_rows": 2, "max_columns": 2}, SandboxErrorCode.TOO_MANY_ROWS),
        ({"max_rows": 3, "max_columns": 1}, SandboxErrorCode.TOO_MANY_COLUMNS),
    ):
        limits = SandboxLimits(
            tmp_root=str(tmp_path / "work"),
            wall_seconds=20,
            max_rows=field["max_rows"],
            max_columns=field["max_columns"],
        )
        with _workspace(tmp_path, fake_child(GOOD_BODY), limits=limits) as workspace:
            _put_input(workspace)
            with pytest.raises(SandboxError) as excinfo:
                workspace.parse(".csv")
        assert _code(excinfo) is code


@pytest.mark.skipif(
    os.name != "posix", reason="O_NOFOLLOW / symlinks need POSIX privileges"
)
def test_an_output_symlinked_to_another_file_is_refused_not_followed(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    secret = tmp_path / "tenant-secret.bin"
    secret.write_bytes(
        PARQUET_BYTES
    )  # even a *valid-looking* target must not be followed
    body = f"""
    sys.stdin.buffer.read()
    os.symlink({str(secret)!r}, "out.parquet")
    print({GOOD_REPLY!r})
    """
    with _workspace(tmp_path, fake_child(body)) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.PROTOCOL_ERROR


def test_a_child_that_cannot_apply_its_limits_is_refused_when_enforcement_is_required(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    body = f"""
    sys.stdin.buffer.read()
    open("out.parquet", "wb").write({PARQUET_BYTES!r})
    print({GOOD_REPLY.replace('"memory": true', '"memory": false')!r})
    """
    with _workspace(tmp_path, fake_child(body), require_enforcement=True) as workspace:
        _put_input(workspace)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.SANDBOX_UNAVAILABLE
    # the positive twin: the same child with limits applied passes under the same requirement
    with _workspace(
        tmp_path, fake_child(GOOD_BODY), require_enforcement=True
    ) as workspace:
        _put_input(workspace)
        assert workspace.parse(".csv").limits_enforced is True


# ----------------------------------------------------------------- before spawning


def test_an_oversized_input_is_refused_before_any_child_is_started(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    marker = tmp_path / "spawned.txt"
    body = f"""
    open({str(marker)!r}, "w").write("started")
    sys.stdin.buffer.read()
    """
    limits = SandboxLimits(
        tmp_root=str(tmp_path / "work"), wall_seconds=20, max_input_bytes=16
    )
    with _workspace(tmp_path, fake_child(body), limits=limits) as workspace:
        workspace.input_path(".csv").write_bytes(b"x" * 17)
        with pytest.raises(SandboxError) as excinfo:
            workspace.parse(".csv")
    assert _code(excinfo) is SandboxErrorCode.INPUT_TOO_LARGE
    assert not marker.exists()


def test_the_extension_must_be_a_listed_one_to_name_an_input(tmp_path: Path) -> None:
    with _workspace(tmp_path, [sys.executable]) as workspace:
        for bad in (".exe", "csv", ".csv/../x", ""):
            with pytest.raises(SandboxError):
                workspace.input_path(bad)
        assert workspace.input_path(".csv").name == "input.csv"


def test_the_temp_directory_is_removed_when_the_body_raises(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    with (
        pytest.raises(RuntimeError),
        _workspace(tmp_path, fake_child(GOOD_BODY)) as workspace,
    ):
        _put_input(workspace)
        raise RuntimeError("boom")
    assert _leftovers(tmp_path) == []


def test_a_workspace_cannot_be_used_outside_its_with_block(
    tmp_path: Path, fake_child: FakeChild
) -> None:
    workspace = _workspace(tmp_path, fake_child(GOOD_BODY))
    with pytest.raises(RuntimeError):
        _ = workspace.path

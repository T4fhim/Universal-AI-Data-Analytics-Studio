# File: apps/api/tests/test_sandbox_guards.py
"""The child's process-level guards, exercised in real child interpreters.

Why subprocesses: ``setrlimit`` is irreversible and the socket shim patches the interpreter's
own ``socket`` module, so neither can be applied inside the pytest process. Each test starts
``python -I -c <script>`` -- the same isolated-mode interpreter the sandbox uses -- calls the
*production* guard function (``uadas_api.sandbox.guards``), then does the hostile thing and
reports what happened on stdout.

Every guard test has a positive twin: the same operation, un-guarded or within the limit,
succeeds. A guard test that only shows the refusal would also pass if the operation were
simply broken in the test environment.

The rlimit tests need Linux (the only platform where memory and CPU limits are enforceable;
see ``uadas_api.sandbox.limits.limits_enforceable``). Locally on Windows they skip with that
reason and a Windows-only test asserts the honest report instead; in CI
(``test_sandbox_ci_guard.py``) a skip of any of them is a failure.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import textwrap
from typing import Any

import pytest
from sandbox_support import linux_only, needs_non_root

from uadas_api.sandbox.limits import limits_enforceable

LIMITS: dict[str, int] = {
    "cpu_seconds": 60,
    "memory_bytes": 768 * 1024 * 1024,
    "max_output_bytes": 1024 * 1024,
    "max_rows": 1000,
    "max_columns": 100,
    "max_open_files": 64,
    "process_headroom": 32,
}


def run_child(
    script: str, *, limits: dict[str, int] | None = None, timeout: float = 60
) -> tuple[int, str]:
    """Run ``script`` in an isolated child with ``LIMITS`` (overridden by ``limits``) as argv[1]."""
    payload = json.dumps({**LIMITS, **(limits or {})})
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", textwrap.dedent(script), payload],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=os.name == "posix",
    )
    try:
        out, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(process)
        out, _ = process.communicate()
        raise AssertionError(f"child timed out; output so far: {out!r}") from None
    finally:
        _kill_group(process)
    return process.returncode, out.strip()


def _kill_group(process: subprocess.Popen[Any]) -> None:
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)


# Indented like the test bodies it is concatenated with, so one ``textwrap.dedent`` in
# ``run_child`` normalises the whole script.
PRELUDE = """
        import json, sys
        from uadas_api.sandbox import guards
        limits = json.loads(sys.argv[1])
"""


# ------------------------------------------------------------------- the network


@pytest.fixture
def listener() -> Any:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    yield server
    server.close()


def test_without_the_shim_a_child_can_reach_a_local_server(
    listener: socket.socket,
) -> None:
    port = listener.getsockname()[1]
    code, out = run_child(f"""
        import socket
        s = socket.create_connection(("127.0.0.1", {port}), timeout=5)
        print("connected")
        """)
    assert (code, out) == (0, "connected")


def test_with_the_shim_the_same_connection_is_blocked(listener: socket.socket) -> None:
    port = listener.getsockname()[1]
    code, out = run_child(PRELUDE + f"""
        guards.install_network_block()
        import socket
        try:
            socket.create_connection(("127.0.0.1", {port}), timeout=5)
            print("connected")
        except guards.SandboxViolation:
            print("blocked", guards.violation_kind())
        """)
    assert (code, out) == (0, "blocked create_connection")


@pytest.mark.parametrize(
    "attempt",
    [
        "socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
        "socket.socket()",
        "socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)",
        "socket.getaddrinfo('example.com', 80)",
        "socket.gethostbyname('example.com')",
        "_socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)",
        "socket.create_server(('127.0.0.1', 0))",
    ],
)
def test_every_route_to_a_network_socket_is_blocked(attempt: str) -> None:
    code, out = run_child(PRELUDE + f"""
        guards.install_network_block()
        import socket, _socket
        try:
            {attempt}
            print("allowed")
        except guards.SandboxViolation:
            print("blocked")
        """)
    assert (code, out) == (0, "blocked")


@pytest.mark.skipif(os.name != "posix", reason="AF_UNIX socketpair is POSIX")
def test_the_shim_leaves_local_socketpairs_alone() -> None:
    # Positive twin: blocking the network must not break interpreter-internal socketpairs.
    code, out = run_child(PRELUDE + """
        guards.install_network_block()
        import socket
        a, b = socket.socketpair()
        a.sendall(b"ok")
        print(b.recv(2).decode(), guards.violation_kind())
        """)
    assert (code, out) == (0, "ok None")


def test_a_blocked_attempt_is_remembered_even_if_the_caller_swallows_it() -> None:
    code, out = run_child(PRELUDE + """
        guards.install_network_block()
        import socket
        try:
            socket.socket()
        except Exception:
            pass
        print(guards.violation_kind())
        """)
    assert (code, out) == (0, "socket")


# ------------------------------------------------------------ the honest report


@pytest.mark.skipif(limits_enforceable(), reason="the Windows/macOS honesty test")
def test_where_limits_cannot_be_enforced_the_report_says_so() -> None:
    code, out = run_child(PRELUDE + """
        report = guards.apply_resource_limits(limits)
        print(json.dumps(report, sort_keys=True))
        """)
    assert code == 0
    report = json.loads(out)
    assert report["memory"] is False
    assert report["cpu"] is False


# --------------------------------------------------------------------- rlimits


@linux_only
def test_the_report_says_which_limits_were_applied() -> None:
    code, out = run_child(PRELUDE + """
        print(json.dumps(guards.apply_resource_limits(limits), sort_keys=True))
        """)
    assert code == 0
    report = json.loads(out)
    for name in ("core", "memory", "cpu", "fsize", "nofile"):
        assert report[name] is True, report


@linux_only
def test_core_dumps_are_disabled() -> None:
    code, out = run_child(PRELUDE + """
        guards.apply_resource_limits(limits)
        import resource
        print(resource.getrlimit(resource.RLIMIT_CORE))
        """)
    assert (code, out) == (0, "(0, 0)")


@linux_only
def test_memory_limit_stops_a_big_allocation_and_allows_a_small_one() -> None:
    code, out = run_child(PRELUDE + """
        guards.apply_resource_limits(limits)
        small = bytearray(64 * 1024 * 1024)
        print("small ok", len(small) // (1024 * 1024))
        try:
            big = bytearray(2 * 1024 * 1024 * 1024)
            print("big ok")
        except MemoryError:
            print("big refused")
        """)
    assert (code, out) == (0, "small ok 64\nbig refused")


@linux_only
def test_cpu_limit_kills_a_busy_loop_and_lets_short_work_finish() -> None:
    code, out = run_child(
        PRELUDE + """
        guards.apply_resource_limits(limits)
        total = 0
        for i in range(1000):
            total += i
        print("short ok", flush=True)  # the process is killed next: unflushed output is lost
        while True:
            pass
        """,
        limits={"cpu_seconds": 1},
        timeout=30,
    )
    assert "short ok" in out
    assert code == -signal.SIGXCPU


@linux_only
def test_file_size_limit_stops_an_oversized_write_and_allows_a_small_one(
    tmp_path: Any,
) -> None:
    target = tmp_path / "big.bin"
    code, out = run_child(
        PRELUDE + f"""
        guards.apply_resource_limits(limits)
        import errno
        with open({str(target)!r}, "wb") as small:
            small.write(b"x" * 1024)
        print("small ok")
        try:
            with open({str(target)!r}, "wb") as big:
                big.write(b"x" * (6 * 1024 * 1024))
                big.flush()
            print("big ok")
        except OSError as error:
            print("big refused", error.errno == errno.EFBIG)
        """,
        limits={"max_output_bytes": 1024 * 1024},
    )
    assert (code, out) == (0, "small ok\nbig refused True")


@linux_only
def test_open_file_limit_stops_a_descriptor_leak_and_allows_a_few() -> None:
    code, out = run_child(
        PRELUDE + """
        guards.apply_resource_limits(limits)
        import errno
        few = [open(__file__ if "__file__" in dir() else sys.executable, "rb") for _ in range(5)]
        print("few ok", len(few))
        many = []
        try:
            for _ in range(500):
                many.append(open(sys.executable, "rb"))
            print("many ok")
        except OSError as error:
            print("many refused", error.errno == errno.EMFILE)
        """,
        limits={"max_open_files": 64},
    )
    assert (code, out) == (0, "few ok 5\nmany refused True")


@linux_only
@needs_non_root
def test_process_limit_stops_a_fork_loop_and_allows_one_child() -> None:
    code, out = run_child(
        PRELUDE + """
        guards.apply_resource_limits(limits)
        import os, signal, time
        pids = []
        try:
            pid = os.fork()
            if pid == 0:
                time.sleep(30)
                os._exit(0)
            pids.append(pid)
            print("one fork ok")
            for _ in range(400):
                pid = os.fork()
                if pid == 0:
                    time.sleep(30)
                    os._exit(0)
                pids.append(pid)
            print("fork bomb allowed", len(pids))
        except BlockingIOError:
            print("fork refused after", len(pids) <= 100)
        finally:
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
                except OSError:
                    pass
        """,
        limits={"process_headroom": 16},
        timeout=60,
    )
    assert out.splitlines() == ["one fork ok", "fork refused after True"], out
    assert code == 0


@linux_only
@needs_non_root
def test_process_limit_can_be_switched_off_and_the_report_then_says_so() -> None:
    code, out = run_child(
        PRELUDE + """
        report = guards.apply_resource_limits(limits)
        print(report["nproc"])
        """,
        limits={"process_headroom": 0},
    )
    assert (code, out) == (0, "False")


@linux_only
def test_the_task_counter_sees_this_process() -> None:
    from uadas_api.sandbox.guards import count_user_tasks

    assert count_user_tasks() >= 1

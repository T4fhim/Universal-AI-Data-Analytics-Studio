# File: apps/api/tests/sandbox_launcher.py
"""A launcher that runs the *production* sandbox child with a hostile reader plugged in.

Why: the malformed-file tests need a "file" that makes a parser do something genuinely
dangerous -- open a socket, fork, allocate without bound, spin, crash the interpreter -- and
no shipped reader does any of those on demand. This script is started in place of
``python -I -m uadas_api.sandbox.child`` (through the runner's internal ``child_command``
seam) and does exactly what that does, except that ``get_reader_for_path`` returns
:class:`HostileReader`, whose behaviour is chosen by the **content of the input file**: the
file *is* the attack, just as with a real exploit of a real parser.

Everything that matters is production code: ``child.main()`` applies the rlimits, installs the
socket block, classifies the failure and writes the reply; the runner supervises and verifies.
This module is only the stand-in for "a parser with a bug". By default the pandas import and the
registry import happen *before* the guards (as the test's own code, not the parser's), which is
what the memory-limit tests need. With ``--lazy`` nothing heavy is imported before the guards
(the registry is replaced by a stub module and pandas is imported when the reader runs), exactly
like the production child: that is what the isolation tests use, because ``unshare(CLONE_NEWUSER)``
needs a single-threaded process and importing pandas starts a thread.

Verbs (first word of the input file; the rest are arguments)::

    benign                  return a 3-row frame
    socket PORT             connect to 127.0.0.1:PORT
    swallow_socket PORT     the same, but catch and ignore any exception, then carry on
    dns                     resolve a host name
    fork                    start sleeping children until fork fails (cleans them up)
    alloc BYTES             allocate that many bytes
    spin                    busy-loop forever
    sleep                   sleep forever
    crash                   segfault the interpreter
    exit CODE               exit the process with CODE, replying nothing
    tcp_listen              bind a listening socket
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from uadas_api.sandbox import child

LAZY = "--lazy" in sys.argv


def note(input_path: Path, text: str) -> None:
    """Leave the result of a probe in the job directory (the test reads it before cleanup)."""
    (input_path.parent / "probe.txt").write_text(text)


def _read_marker(target: str, marker: str) -> str:
    try:
        with open(target, "rb") as handle:
            data = handle.read()
    except OSError as error:
        return f"DENIED:{type(error).__name__}"
    return "READ:found" if marker.encode() in data else "READ:absent"


def _raw_connect(port: int) -> str:
    import socket

    # The shim replaces `socket.socket`; its real base class is still one attribute away.
    base = next(c for c in socket.socket.__mro__ if c.__module__ == "_socket")
    try:
        sock = base(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(("127.0.0.1", port))
        sock.close()
    except OSError as error:
        return f"FAILED:{type(error).__name__}"
    return "CONNECTED"


class HostileReader:
    """A reader whose 'bug' is whatever the input file says."""

    SUPPORTED_EXTENSIONS = {".csv"}

    @classmethod
    def can_read(cls, path: Path) -> bool:
        return True

    @classmethod
    def list_tables(cls, path: Path) -> list[str]:
        return [path.stem]

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Any:
        words = path.read_text().split()
        verb, args = words[0], words[1:]
        if verb == "socket":
            import socket

            socket.create_connection(("127.0.0.1", int(args[0])), timeout=5)
        elif verb == "swallow_socket":
            import socket

            try:
                socket.create_connection(("127.0.0.1", int(args[0])), timeout=5)
            except Exception:
                pass
        elif verb == "dns":
            import socket

            socket.gethostbyname("example.com")
        elif verb == "probe_parent_env":
            # Can this process read its parent's environment (the worker's secrets)?
            note(path, _read_marker(f"/proc/{os.getppid()}/environ", args[0]))
        elif verb == "probe_file":
            # Can this process read some other file (another job's input, the worker's code)?
            note(path, _read_marker(args[0], args[1]))
        elif verb == "probe_raw_socket":
            # The shim-bypass: the `_socket` base class reached through the class hierarchy.
            note(path, _raw_connect(int(args[0])))
        elif verb == "probe_identity":
            status = Path("/proc/self/status").read_text()
            caps = [line for line in status.splitlines() if line.startswith("CapEff")]
            note(path, f"uid={os.getuid()} gid={os.getgid()} {caps[0] if caps else ''}")
        elif verb == "write_pid_then_sleep":
            # A long-lived child whose pid the test knows (for the kill -9 of its parent).
            Path(args[0]).write_text(str(os.getpid()))
            import time

            while True:
                time.sleep(0.1)
        elif verb == "tcp_listen":
            import socket

            server = socket.socket()
            server.bind(("127.0.0.1", 0))
        elif verb == "fork":
            import signal
            import time

            pids: list[int] = []
            try:
                for _ in range(2000):
                    pid = os.fork()
                    if pid == 0:
                        time.sleep(60)
                        os._exit(0)
                    pids.append(pid)
            finally:
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                        os.waitpid(pid, 0)
                    except OSError:
                        pass
        elif verb == "alloc":
            blob = bytearray(int(args[0]))
            blob[0] = 1
        elif verb == "spin":
            while True:
                pass
        elif verb == "sleep":
            import time

            while True:
                time.sleep(0.1)
        elif verb == "crash":
            # A native crash no Python handler can catch (ctypes would turn a null read into
            # a Python exception on Windows, which is not the failure being modelled).
            os.abort()
        elif verb == "exit":
            os._exit(int(args[0]))
        elif verb != "benign":
            raise ValueError("unknown verb")
        import pandas as pd  # type: ignore[import-untyped]  # a no-op when already imported

        return SimpleNamespace(
            dataframe=pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}),
            source_format="csv",
            read_warnings=[],
        )


def _plug_in_the_hostile_reader() -> None:
    if LAZY:
        stub = ModuleType("uadas_core.readers.reader_registry")
        stub.get_reader_for_path = lambda path: HostileReader  # type: ignore[attr-defined]
        sys.modules["uadas_core.readers.reader_registry"] = stub
        return
    import pandas  # noqa: F401  (before the guards, like the original launcher)

    import uadas_core.readers.reader_registry as registry

    registry.get_reader_for_path = lambda path: HostileReader


_plug_in_the_hostile_reader()

if __name__ == "__main__":
    code = child.main()
    sys.stderr.flush()
    os._exit(code)

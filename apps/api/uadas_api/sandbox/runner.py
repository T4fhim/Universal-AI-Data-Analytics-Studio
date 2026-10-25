# File: apps/api/uadas_api/sandbox/runner.py
"""The parent side of the sandbox: give a file to a child, supervise it, verify what comes back.

Why a context manager over a private directory: the whole exchange happens inside one fresh,
empty temporary directory (``SandboxWorkspace``). The input is placed there under a name *the
parent* chose (``input.<ext>``: the user's file name never reaches the child), the child runs
with that directory as its working directory, temp directory and ``HOME``, writes
``out.parquet`` there, and the directory is deleted on the way out. **What the directory's mode
does and does not do:** it is created ``0700``, which separates it from *other users*; a child
that runs as the worker's own uid (the default) is the same user, so ``0700`` keeps nothing from
it, and neither does the stripped environment keep the worker's secrets from a process that can
open ``/proc/<ppid>/environ``. Real separation is :mod:`uadas_api.sandbox.isolation`'s job
(a non-dumpable worker, a dedicated child uid, a container) and is spelled out in
``plans/phase-3-5-jobs.md``.

What the parent does, in this order:

1. **Before spawning**: the input exists and is within the size cap (the file-type checks are
   ``admission``'s job, run by the caller just before), and the worker makes itself
   non-dumpable (:func:`~uadas_api.sandbox.isolation.harden_worker`).
2. **A minimal explicit environment** -- no inherited variable except ``PATH`` (and
   ``SYSTEMROOT`` on Windows, without which Python cannot start). The parser's *own* environment
   holds none of the worker's secrets; that is housekeeping, not a security boundary.
3. **A bounded wait**: a wall-clock timeout; the child's reply is read with a size cap and the
   child is killed the moment it exceeds it (an endless stream must not exhaust the parent).
   The child also arms its own alarm and a kill-with-parent signal (:mod:`guards`), so a worker
   that is itself killed does not leave it running.
4. **The process group dies**: ``killpg`` on POSIX (the child leads its own session), a Job
   Object plus ``taskkill /T /F`` on Windows -- on timeout *and* after a normal exit. A
   grandchild that calls ``setsid()`` leaves the group and survives; the bound on those is
   ``RLIMIT_NPROC`` and the deployment's cgroup ``pids_limit``, not this code.
5. **Nothing the child says is trusted**: the reply must match :mod:`protocol` exactly; an
   unknown error code, a claim beyond the row / column caps, a missing or non-Parquet output,
   an output over the size cap, or an output that is a symlink (opened with ``O_NOFOLLOW``, so
   a compromised child cannot make the parent upload some other file) all fail closed.
6. **Enforcement is measured**: the child reports which rlimits it really applied and whether it
   isolated its network. Where the platform can enforce them (``limits_enforceable``) and the
   child did not apply every one in :meth:`SandboxLimits.required_enforcement`, the result is
   refused (``sandbox_unavailable``) -- an unprotected parse is worse than none. The in-process
   socket shim is *not* in that list (it is bypassable, see :mod:`guards`).

This module never imports a reader or a reader library (``.importlinter``, and a fresh-
interpreter test). It does **not** parse the Parquet it receives: the footer is the child's
output and parsing it here would put a parser of attacker-influenced bytes in the parent. The
row / column counts are therefore the child's claim (capped), advisory metadata.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
import signal
import stat
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from uadas_api.sandbox._winjob import WindowsJob
from uadas_api.sandbox.admission import supported_extensions
from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.sandbox.isolation import (
    WORKSPACE_PREFIX,
    harden_worker,
    reap_stale_workspaces,
)
from uadas_api.sandbox.limits import SandboxLimits, limits_enforceable
from uadas_api.sandbox.protocol import (
    OUTPUT_NAME,
    Failure,
    ProtocolError,
    Success,
    decode_response,
    encode_request,
)

_logger = logging.getLogger(__name__)

_POLL_SECONDS = 0.05
_JOIN_SECONDS = 5.0
_CHUNK = 64 * 1024
_PARQUET_MAGIC = b"PAR1"
# A bound on what the child may *claim*; the real caps are compared separately so the failure
# is ``too_many_rows`` rather than a generic protocol error.
_CLAIM_CEILING = 2**53
_RMTREE_ATTEMPTS = 5


def default_child_command() -> list[str]:
    """The command that starts the real child: isolated mode, the child module, no cwd on the path."""
    return [sys.executable, "-I", "-X", "utf8", "-m", "uadas_api.sandbox.child"]


@dataclass(frozen=True)
class SandboxResult:
    """A parsed table, as verified by the parent. ``output_path`` lives in the workspace."""

    source_format: str
    row_count: int
    column_count: int
    columns: tuple[tuple[str, str], ...]
    warning_count: int
    enforcement: dict[str, bool]
    size: int
    sha256: str
    output_path: Path
    elapsed_seconds: float = 0.0
    # The operator acknowledged that the deployment isolates the network (a container with no
    # network): stated, not measured.
    network_acknowledged: bool = False

    @property
    def limits_enforced(self) -> bool:
        """Whether the child really applied its memory and CPU limits (measured, not assumed)."""
        return bool(self.enforcement.get("memory") and self.enforcement.get("cpu"))

    @property
    def network_isolated(self) -> bool:
        """Whether the child had no route out: a verified namespace, or an acknowledged container.

        The in-process socket shim does not count: it is reported as ``network_guard`` and is
        bypassable (see :mod:`uadas_api.sandbox.guards`).
        """
        return (
            bool(self.enforcement.get("network_isolated")) or self.network_acknowledged
        )

    def open_output(self) -> BinaryIO:
        """Open the verified Parquet file for reading (never through a symlink)."""
        handle, size = _open_regular(self.output_path)
        if size != self.size:
            handle.close()
            raise SandboxError(SandboxErrorCode.PROTOCOL_ERROR)
        return handle


def _open_regular(path: Path) -> tuple[BinaryIO, int]:
    """Open ``path`` read-only, refusing symlinks and anything that is not a regular file."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        if os.name == "nt":
            attributes = getattr(os.lstat(path), "st_file_attributes", 0)
            if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise SandboxError(SandboxErrorCode.PROTOCOL_ERROR)
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise SandboxError(SandboxErrorCode.PROTOCOL_ERROR) from None
    except OSError:  # ELOOP for a symlink, EACCES, ...
        raise SandboxError(SandboxErrorCode.PROTOCOL_ERROR) from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SandboxError(SandboxErrorCode.PROTOCOL_ERROR)
        return os.fdopen(descriptor, "rb"), info.st_size
    except BaseException:
        os.close(descriptor)
        raise


class _Collector(threading.Thread):
    """Reads a pipe to the end, keeping at most ``cap + 1`` bytes and flagging an overflow."""

    def __init__(self, stream: BinaryIO, cap: int | None) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._cap = cap
        self.data = bytearray()
        self.overflow = False

    def run(self) -> None:
        try:
            # os.read on the descriptor, not BufferedReader.read(n): the latter blocks until
            # n bytes or EOF, which would hold back a short reply until the pipe closes.
            descriptor = self._stream.fileno()
            while True:
                chunk = os.read(descriptor, _CHUNK)
                if not chunk:
                    return
                if self._cap is None:
                    continue  # drained and dropped (stderr is never shown to anyone)
                room = self._cap + 1 - len(self.data)
                if room > 0:
                    self.data += chunk[:room]
                if len(self.data) > self._cap:
                    self.overflow = True
        except (OSError, ValueError):
            return


def _child_environment(workspace: Path) -> dict[str, str]:
    """The child's whole environment: explicit, small, and free of the parent's secrets."""
    here = str(workspace)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "TMPDIR": here,
        "TEMP": here,
        "TMP": here,
        "HOME": here,
        "XDG_CACHE_HOME": here,
        "MPLCONFIGDIR": here,
        "LANG": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        # Keep native thread pools and allocators small: each extra thread counts against
        # RLIMIT_NPROC and each arena against RLIMIT_AS.
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "ARROW_DEFAULT_MEMORY_POOL": "system",
        "MALLOC_ARENA_MAX": "2",
    }
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return env


def _kill_tree(process: subprocess.Popen[bytes], job: WindowsJob | None = None) -> None:
    """Kill ``process`` and everything it started. Safe to call on an already-dead process."""
    if job is not None:
        job.terminate()  # reaches descendants even after the child itself has exited
    if os.name == "nt":
        # Fallback for the instant before the child joined the job: /T follows the
        # parent/child links Windows keeps; /F does not ask nicely.
        # An absolute path (no PATH lookup: a planted taskkill.exe must not be run).
        taskkill = os.path.join(
            os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "taskkill.exe"
        )
        subprocess.run(  # nosec B603
            [taskkill, "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            timeout=15,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)  # the child leads its own session
    with contextlib.suppress(OSError):
        process.kill()


def _exit_code(returncode: int) -> SandboxErrorCode:
    """Classify a child that exited without a usable reply."""
    if returncode < 0:
        signal_number = -returncode
        if signal_number == getattr(signal, "SIGXCPU", -1):
            return SandboxErrorCode.CPU_LIMIT
        if signal_number == getattr(signal, "SIGKILL", -1):
            return (
                SandboxErrorCode.RESOURCE_LIMIT
            )  # an external killer: OOM, CPU hard limit
    return SandboxErrorCode.SANDBOX_CRASHED


def _verify_output(path: Path, limits: SandboxLimits) -> tuple[int, str]:
    """Return ``(size, sha256)`` of the child's output after checking it is a plausible Parquet file."""
    handle, size = _open_regular(path)
    with handle:
        if size > limits.max_output_bytes:
            raise SandboxError(SandboxErrorCode.OUTPUT_TOO_LARGE)
        if size < 2 * len(_PARQUET_MAGIC):
            raise SandboxError(SandboxErrorCode.PROTOCOL_ERROR)
        digest = hashlib.sha256()
        head = handle.read(len(_PARQUET_MAGIC))
        digest.update(head)
        tail = head
        total = len(head)
        while chunk := handle.read(_CHUNK):
            total += len(chunk)
            if total > limits.max_output_bytes:  # it grew while we were reading
                raise SandboxError(SandboxErrorCode.OUTPUT_TOO_LARGE)
            digest.update(chunk)
            tail = (tail + chunk)[-len(_PARQUET_MAGIC) :]
        if head != _PARQUET_MAGIC or tail != _PARQUET_MAGIC or total != size:
            raise SandboxError(SandboxErrorCode.PROTOCOL_ERROR)
    return size, digest.hexdigest()


class SandboxWorkspace:
    """One job's private directory plus the ability to run the child inside it.

    Use as ``with SandboxWorkspace() as workspace:`` -- place the input at
    ``workspace.input_path(ext)``, call :meth:`parse`, stream the result out of
    ``result.open_output()`` *inside* the block. Leaving the block deletes the directory.

    ``child_command`` and ``require_enforcement`` are internal seams for the test-suite (a fake
    child; a platform without rlimits): no setting and no request can reach them.
    """

    def __init__(
        self,
        limits: SandboxLimits | None = None,
        *,
        child_command: Sequence[str] | None = None,
        require_enforcement: bool | None = None,
    ) -> None:
        self._limits = limits or SandboxLimits.from_settings()
        self._command = (
            list(child_command) if child_command else default_child_command()
        )
        self._require_enforcement = (
            limits_enforceable() if require_enforcement is None else require_enforcement
        )
        self._path: Path | None = None

    def __enter__(self) -> SandboxWorkspace:
        _reap_once_per_process(self._limits)
        root = self._limits.tmp_root or None
        try:
            self._path = Path(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX, dir=root))
            self._hand_to_child(self._path)
        except OSError:
            path, self._path = self._path, None
            if path is not None:
                _remove_tree(path)
            raise SandboxError(SandboxErrorCode.SANDBOX_UNAVAILABLE) from None
        return self

    def _hand_to_child(self, path: Path) -> None:
        """With a dedicated child uid, make the child the owner of ``path`` (and only it)."""
        uid, gid = self._limits.child_uid, self._limits.child_gid
        if uid is not None and gid is not None:
            _chown(path, uid, gid)  # needs root (or CAP_CHOWN): OSError otherwise
            os.chmod(path, 0o700)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        path, self._path = self._path, None
        if path is not None:
            _remove_tree(path)

    @property
    def path(self) -> Path:
        """The private directory (only inside the ``with`` block)."""
        if self._path is None:
            raise RuntimeError("the sandbox workspace is not open")
        return self._path

    def input_path(self, extension: str) -> Path:
        """Where to put the input for ``extension``: ``input<extension>``, a name the parent picks."""
        if extension not in supported_extensions():
            raise SandboxError(SandboxErrorCode.UNSUPPORTED_TYPE)
        return self.path / f"input{extension}"

    def parse(self, extension: str) -> SandboxResult:
        """Run the child over ``input<extension>`` and return the verified result.

        Raises :class:`~uadas_api.sandbox.errors.SandboxError` (closed codes, fixed messages)
        for every failure; never anything carrying text from the child.
        """
        limits = self._limits
        input_path = self.input_path(extension)
        try:
            size = input_path.stat().st_size
        except OSError:
            raise SandboxError(SandboxErrorCode.UNSUPPORTED_TYPE) from None
        if input_path.is_symlink() or size > limits.max_input_bytes:
            code = (
                SandboxErrorCode.INPUT_TOO_LARGE
                if size > limits.max_input_bytes
                else SandboxErrorCode.UNSUPPORTED_TYPE
            )
            raise SandboxError(code)
        if limits.child_uid is not None and limits.child_gid is not None:
            try:
                _chown(input_path, limits.child_uid, limits.child_gid)
            except OSError:
                raise SandboxError(SandboxErrorCode.SANDBOX_UNAVAILABLE) from None
        started = time.monotonic()
        try:
            reply = self._run_child(input_path.name)
        except SandboxError as error:
            _logger.warning("sandbox parse failed: %s", error.code.value)
            raise
        if isinstance(reply, Failure):
            raise SandboxError(reply.code)
        if self._require_enforcement:
            missing = [
                key
                for key in limits.required_enforcement()
                if not reply.enforcement.get(key)
            ]
            if missing:
                # Names of the protections, never anything from the file or the child's text.
                _logger.error("sandbox enforcement missing: %s", ",".join(missing))
                raise SandboxError(SandboxErrorCode.SANDBOX_UNAVAILABLE)
        if reply.row_count > limits.max_rows:
            raise SandboxError(SandboxErrorCode.TOO_MANY_ROWS)
        if reply.column_count > limits.max_columns:
            raise SandboxError(SandboxErrorCode.TOO_MANY_COLUMNS)
        output = self.path / OUTPUT_NAME
        out_size, digest = _verify_output(output, limits)
        return SandboxResult(
            source_format=reply.source_format,
            row_count=reply.row_count,
            column_count=reply.column_count,
            columns=reply.columns,
            warning_count=reply.warning_count,
            enforcement=reply.enforcement,
            size=out_size,
            sha256=digest,
            output_path=output,
            elapsed_seconds=time.monotonic() - started,
            network_acknowledged=limits.network_isolation == "container",
        )

    def _run_child(self, input_name: str) -> Success | Failure:
        limits = self._limits
        # Before the child exists: a same-uid child must not be able to read this process's
        # /proc entries (environment, memory). False off Linux; nothing to do there.
        harden_worker()
        request = encode_request(
            input_name, OUTPUT_NAME, limits.child_payload(parent_pid=os.getpid())
        )
        kwargs: dict[str, object] = {
            "cwd": self.path,
            "env": _child_environment(self.path),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "close_fds": True,
        }
        if limits.child_uid is not None and os.name != "posix":
            # A dedicated uid cannot be honoured here; refusing beats silently running as the worker.
            raise SandboxError(SandboxErrorCode.SANDBOX_UNAVAILABLE)
        job = WindowsJob.create()  # None off Windows
        if os.name == "posix":
            # Its own session and process group: killpg then reaches the group's members
            # (not a grandchild that calls setsid(); see the module docs).
            kwargs["start_new_session"] = True
            if limits.child_uid is not None and limits.child_gid is not None:
                # Applied by the interpreter between fork and exec (C code, not preexec_fn).
                kwargs["user"] = limits.child_uid
                kwargs["group"] = limits.child_gid
                kwargs["extra_groups"] = []
        else:
            kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            ) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            process = subprocess.Popen(self._command, **kwargs)  # type: ignore[call-overload]  # nosec B603
        except OSError:
            if job is not None:
                job.close()
            raise SandboxError(SandboxErrorCode.SANDBOX_UNAVAILABLE) from None
        if job is not None and not job.assign(process.pid):
            job.close()
            job = None  # taskkill /T is the fallback
        # PIPE was requested for all three, so none of these is None (B101 is skipped in CI).
        assert process.stdin is not None
        assert process.stdout is not None and process.stderr is not None  # nosec B101
        stdout = _Collector(process.stdout, limits.max_response_bytes)
        stderr = _Collector(process.stderr, None)
        stdout.start()
        stderr.start()
        outcome: SandboxErrorCode | None = None
        try:
            try:
                process.stdin.write(request)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass  # the child died before reading; its exit code explains it
            deadline = time.monotonic() + limits.wall_seconds
            while True:
                try:
                    process.wait(timeout=_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if stdout.overflow:
                    outcome = SandboxErrorCode.PROTOCOL_ERROR
                    break
                if time.monotonic() > deadline:
                    outcome = SandboxErrorCode.TIMEOUT
                    break
        finally:
            # Also after a clean exit: no grandchild may outlive the job.
            _kill_tree(process, job)
            # (A SIGKILLed process always exits; the suppress is for a stuck Windows handle.)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=_JOIN_SECONDS)
            stdout.join(_JOIN_SECONDS)
            stderr.join(_JOIN_SECONDS)
            if job is not None:
                job.close()
        if outcome is not None:
            raise SandboxError(outcome)
        if stdout.overflow:
            raise SandboxError(SandboxErrorCode.PROTOCOL_ERROR)
        if not stdout.data.strip():
            code = (
                _exit_code(process.returncode)
                if process.returncode != 0
                else SandboxErrorCode.PROTOCOL_ERROR
            )
            raise SandboxError(code)
        try:
            return decode_response(
                bytes(stdout.data), max_rows=_CLAIM_CEILING, max_columns=_CLAIM_CEILING
            )
        except ProtocolError:
            raise SandboxError(SandboxErrorCode.PROTOCOL_ERROR) from None


def _chown(path: Path, uid: int, gid: int) -> None:
    """``os.chown`` that fails as an ``OSError`` where there is no such call (Windows)."""
    chown = getattr(os, "chown", None)
    if chown is None:
        raise OSError("this platform cannot hand a directory to another user")
    chown(path, uid, gid)


def stale_workspace_age(limits: SandboxLimits) -> float:
    """How long a job directory must have been untouched before it counts as a dead worker's.

    Longer than any job may run: the Celery hard time limit (when Django settings are available)
    or the sandbox wall limit, plus a margin, and never under half an hour.
    """
    hard = 0
    try:
        from django.conf import settings

        hard = int(getattr(settings, "CELERY_TASK_TIME_LIMIT", 0) or 0)
    except Exception:  # noqa: BLE001 - unconfigured settings must not break a parse
        hard = 0
    return float(max(hard + 300, limits.wall_seconds * 2 + 300, 1800))


def reap_workspaces(limits: SandboxLimits | None = None) -> int:
    """Remove the job directories dead workers left behind (see :func:`reap_stale_workspaces`).

    Runs once when a process opens its first workspace and then every time the job sweeper runs.
    Owned-by-us only: this process's uid and, when configured, the dedicated child uid.
    """
    config = limits or SandboxLimits.from_settings()
    owners: set[int] | None = None
    if hasattr(os, "geteuid"):
        owners = {os.geteuid()}
        if config.child_uid is not None:
            owners.add(config.child_uid)
    return reap_stale_workspaces(
        config.tmp_root or None,
        older_than=stale_workspace_age(config),
        owner_uids=owners,
    )


_reaped_lock = threading.Lock()
_reaped_once = False


def _reap_once_per_process(limits: SandboxLimits) -> None:
    global _reaped_once
    with _reaped_lock:
        if _reaped_once:
            return
        _reaped_once = True
    try:
        reap_workspaces(limits)
    except OSError:  # housekeeping must never fail a parse
        _logger.warning("the startup sweep of stale sandbox workspaces failed")


def _remove_tree(path: Path) -> None:
    """Delete the workspace, retrying briefly (Windows holds files of a just-killed process)."""
    for attempt in range(_RMTREE_ATTEMPTS):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt + 1 == _RMTREE_ATTEMPTS:
                break
            time.sleep(0.1 * (attempt + 1))
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        # Class and nothing else: the path itself names a job directory, not tenant data, but
        # the rule is that nothing reaches a log from a parse.
        _logger.error("a sandbox workspace could not be removed")

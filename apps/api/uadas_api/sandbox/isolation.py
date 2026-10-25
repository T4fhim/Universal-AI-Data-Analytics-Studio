# File: apps/api/uadas_api/sandbox/isolation.py
"""Parent-side isolation: protect the worker from its child, and clean up after dead workers.

Why a module of its own: ``runner`` supervises a child, ``guards`` is what the child does to
itself; the things the *worker* must do so that a compromised child cannot reach it, and the
things that survive a worker that was killed, belong to neither. Everything here is best effort
that *reports* what it managed -- nothing claims a protection it did not establish.

The honest statement of what separates a child from its worker (details and the deployment
requirements are in ``plans/phase-3-5-jobs.md``):

* A child that runs as **the worker's own uid** can read ``/proc/<worker>/environ`` (the
  secrets), the worker's files and every other job's directory; ``0700`` and a stripped
  environment are meaningless between processes of one user. :func:`harden_worker` closes the
  ``/proc`` and ptrace routes by making the worker non-dumpable; nothing but a **different uid**
  (``SANDBOX_CHILD_UID``) or a **container** closes the file routes. That is why production
  settings require one of the two (or an explicit acknowledgement).
* Switching uid needs a worker that may (:func:`can_switch_identity`): root, or ``CAP_SETUID``,
  ``CAP_SETGID`` and ``CAP_CHOWN`` (the job directory is handed to the child's uid).
* Concurrent children of one dedicated uid can still read each other's directories. Separating
  those needs a uid per concurrent job or a container per job.
* A worker killed with SIGKILL cannot remove its job directory, and that directory holds a
  tenant's file: :func:`reap_stale_workspaces` removes what such workers left behind.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import time
from collections.abc import Collection
from pathlib import Path

_logger = logging.getLogger(__name__)

WORKSPACE_PREFIX = "uadas-sbx-"
_PR_SET_DUMPABLE = 4
_CAP_SETGID = 6
_CAP_SETUID = 7
_CAP_CHOWN = 0


def harden_worker() -> bool:
    """Make this process non-dumpable so a same-uid child cannot read its ``/proc`` entries.

    ``PR_SET_DUMPABLE=0`` turns ``/proc/<pid>/{environ,mem,maps,fd,...}`` root-owned and forbids
    ``ptrace`` by the same uid. Idempotent and cheap; the runner calls it before every spawn, and
    the Celery worker calls it when a worker process starts. ``False`` where there is nothing to do
    (not Linux) or the call failed; the caller reports it.
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        return bool(libc.prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) == 0)
    except (OSError, AttributeError):
        return False


def _effective_capabilities() -> int:
    try:
        with open("/proc/self/status", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("CapEff:"):
                    return int(line.split()[1], 16)
    except (OSError, ValueError, IndexError):
        pass
    return 0


def can_switch_identity() -> bool:
    """Whether this process may run a child under another uid/gid and hand it a directory."""
    if not hasattr(os, "geteuid"):
        return False
    if os.geteuid() == 0:
        return True
    caps = _effective_capabilities()
    needed = (1 << _CAP_SETUID) | (1 << _CAP_SETGID) | (1 << _CAP_CHOWN)
    return caps & needed == needed


def probe_network_isolation(timeout: float = 60.0) -> bool:
    """Whether a fresh sandbox child could unshare a network namespace on this host.

    Asks the same function the child uses, in the same kind of interpreter (``python -I``), so
    the answer is about the real code path and not about a guess at kernel settings. Used by the
    deploy check for ``SANDBOX_NETWORK_ISOLATION=unshare``.
    """
    code = (
        "import sys; from uadas_api.sandbox import guards; "
        "sys.exit(0 if guards.isolate_network() else 3)"
    )
    try:
        completed = subprocess.run(  # nosec B603
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            timeout=timeout,
            check=False,
            env={"PATH": os.environ.get("PATH", "")},
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def reap_stale_workspaces(
    root: str | Path | None,
    *,
    older_than: float,
    owner_uids: Collection[int] | None = None,
    now: float | None = None,
) -> int:
    """Delete job directories a dead worker left behind; return how many were removed.

    A directory is removed only if **all** of these hold: it is a real directory (never a symlink)
    directly under ``root`` (``None`` = the system temp dir), its name starts with
    :data:`WORKSPACE_PREFIX`, it is owned by one of ``owner_uids`` (default: this process's
    effective uid; pass the child's uid too when one is configured), and its modification time
    (set when the input and the output are written) is at least ``older_than`` seconds old. The age is how a live job's directory is told from a dead one's:
    callers pass more than the longest a job may run (the Celery hard time limit plus a margin),
    so a directory that old belongs to a worker that no longer exists. Never raises.
    """
    base = Path(root) if root else Path(tempfile.gettempdir())
    owners = (
        set(owner_uids)
        if owner_uids is not None
        else ({os.geteuid()} if hasattr(os, "geteuid") else None)
    )
    moment = time.time() if now is None else now
    removed = 0
    try:
        entries = list(os.scandir(base))
    except OSError:
        return 0
    for entry in entries:
        try:
            if not entry.name.startswith(WORKSPACE_PREFIX):
                continue
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            info = entry.stat(follow_symlinks=False)
            if owners is not None and info.st_uid not in owners:
                continue
            if moment - info.st_mtime < older_than:
                continue
            shutil.rmtree(entry.path)
            removed += 1
        except OSError:
            # Class only: the name is a job directory, but the rule is nothing reaches a log from a parse.
            _logger.warning("a stale sandbox workspace could not be removed")
            with contextlib.suppress(OSError):
                shutil.rmtree(entry.path, ignore_errors=True)
    if removed:
        _logger.info("reaped %d stale sandbox workspace(s)", removed)
    return removed

# File: apps/api/tests/sandbox_support.py
"""The one definition of "when do the Linux-only sandbox tests skip", shared by the tests and the CI guard.

Why a module: ``test_sandbox_ci_guard.py`` fails a CI run whose Linux-only tests would skip, and
for that to mean anything it must ask the *same question* as the ``skipif`` markers on those
tests. A local copy of the predicate in the guard could drift (someone changes a marker's reason or
condition and the guard keeps passing); here the markers are built from :func:`skip_conditions`
and the guard reads the conditions back out of the markers themselves (``mark.args[0]``).

Three marks, by what a test needs:

* :data:`linux_only` -- memory/CPU/file-size/descriptor/process limits need Linux.
* :data:`needs_non_root` -- ``RLIMIT_NPROC`` is not enforced for root, so the fork-bomb tests need
  an unprivileged user.
* :data:`needs_root` -- the dedicated-uid tests (``SANDBOX_CHILD_UID``) need a worker that may
  switch identity. They skip in CI (the runner is unprivileged) and run in the root container; the
  skip is counted in the budget in ``ci.yml``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from uadas_api.sandbox.limits import SandboxLimits, limits_enforceable
from uadas_api.sandbox.runner import SandboxResult, SandboxWorkspace

HERE = Path(__file__).resolve().parent
LAUNCHER = [sys.executable, "-I", str(HERE / "sandbox_launcher.py")]
# Imports nothing heavy before the guards, like the production child (see sandbox_launcher.py).
LAZY_LAUNCHER = [*LAUNCHER, "--lazy"]


def current_euid() -> int | None:
    """The effective uid, or ``None`` where there is no such thing (Windows)."""
    return os.geteuid() if hasattr(os, "geteuid") else None


def skip_conditions(enforceable: bool, euid: int | None) -> tuple[bool, bool, bool]:
    """``(linux_only, needs_non_root, needs_root)``: whether each class of test skips."""
    return (not enforceable, euid == 0, not enforceable or euid != 0)


_LINUX_ONLY, _NEEDS_NON_ROOT, _NEEDS_ROOT = skip_conditions(
    limits_enforceable(), current_euid()
)

linux_only = pytest.mark.skipif(
    _LINUX_ONLY,
    reason="rlimits are enforceable only on Linux (the platform the sandbox is gated on)",
)
needs_non_root = pytest.mark.skipif(
    _NEEDS_NON_ROOT,
    reason="RLIMIT_NPROC is not enforced for root; run as an unprivileged user",
)
needs_root = pytest.mark.skipif(
    _NEEDS_ROOT,
    reason="the dedicated-uid tests need a root worker on Linux (CI runs unprivileged; "
    "the root container run covers them)",
)
windows_twin = pytest.mark.skipif(
    limits_enforceable(),
    reason="the Windows/macOS honesty twin: asserts what a platform WITHOUT rlimits reports",
)

LINUX_ONLY_MARKS = (linux_only, needs_non_root)


def marks_would_skip(*marks: pytest.MarkDecorator) -> bool:
    """Whether any of the given ``skipif`` marks would skip (read from the marks themselves)."""
    return any(bool(mark.mark.args[0]) for mark in marks)


def make_limits(work: Path, **overrides: Any) -> SandboxLimits:
    """Limits with a private temp root and a generous wall clock (tests that need less pass it)."""
    defaults: dict[str, Any] = {"tmp_root": str(work), "wall_seconds": 90.0}
    return SandboxLimits(**{**defaults, **overrides})


def run_probe(
    work: Path,
    line: str,
    *,
    require_enforcement: bool = False,
    **limit_overrides: Any,
) -> tuple[str, SandboxResult]:
    """Run the real child with the hostile reader on ``line``; return its note and the result.

    ``line`` is the content of the input file: a probe verb of ``sandbox_launcher.py`` and its
    arguments. The note is what the probe left in the job directory.
    """
    workspace = SandboxWorkspace(
        make_limits(work, **limit_overrides),
        child_command=LAZY_LAUNCHER,
        require_enforcement=require_enforcement,
    )
    with workspace:
        workspace.input_path(".csv").write_text(line)
        result = workspace.parse(".csv")
        probe = workspace.path / "probe.txt"
        return (probe.read_text() if probe.exists() else ""), result

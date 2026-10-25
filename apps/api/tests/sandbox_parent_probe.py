# File: apps/api/tests/sandbox_parent_probe.py
"""A stand-in 'worker': parses one file whose reader sleeps forever, so the test can kill -9 it.

Why a separate script: the property under test is what happens to the *child* and to the job
directory when the *parent is killed without warning* (Celery's hard time limit, the OOM killer).
That cannot be observed from inside the process that is killed. The test starts this script,
learns the child's pid and the job directory from the files it writes, SIGKILLs this process and
then looks at what is left.

Usage: ``python sandbox_parent_probe.py ROOT PIDFILE INFOFILE``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sandbox_support import LAZY_LAUNCHER, make_limits

from uadas_api.sandbox.runner import SandboxWorkspace

root, pidfile, info = (Path(argument) for argument in sys.argv[1:4])
workspace = SandboxWorkspace(
    make_limits(root, wall_seconds=120),
    child_command=LAZY_LAUNCHER,
    require_enforcement=False,
)
with workspace:
    workspace.input_path(".csv").write_text(f"write_pid_then_sleep {pidfile}")
    info.write_text(str(workspace.path))
    workspace.parse(".csv")

# File: apps/api/uadas_api/web/runtime.py
"""Process-level defaults the API needs before the core's analysis stack is imported.

Why: importing the core's tool registry (the stage catalog and every stage job) pulls in pmdarima
and, through it, matplotlib. Matplotlib reads a per-user config directory at import and, when the
environment gives it no ``MPLCONFIGDIR`` and no ``HOME`` (a container user without a home
directory, a worker started with a minimal environment), raises ``RuntimeError: Could not
determine home directory`` -- which would take down every process that merely imports the API's
URL configuration, including a Celery worker. A server also has no display, so the backend is the
non-interactive ``Agg``. Both are ``setdefault``: an operator's own value always wins.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def headless_plotting_defaults() -> None:
    """Make importing matplotlib safe and display-free in a minimal server environment."""
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault(
        "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "uadas-matplotlib")
    )

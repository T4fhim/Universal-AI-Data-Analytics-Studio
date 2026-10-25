# File: apps/api/tests/test_web_runtime.py
"""The API's URL configuration imports in a minimal environment (no HOME, no display).

Why: since 3.6 the URL configuration imports the core's tool registry, which imports matplotlib;
matplotlib raised ``Could not determine home directory`` in an environment with no ``HOME`` --
a real Celery worker started with a scrubbed environment died at its first system check (found by
``test_jobs_integration``). ``uadas_api/web/runtime.py`` sets the headless defaults first; this
test runs the import in a fresh interpreter whose environment holds only what Python needs, and
shows the defaults an operator's own values override.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - a fixed interpreter and a fixed program, no user input
import sys
from pathlib import Path

import pytest

from uadas_api.web.runtime import headless_plotting_defaults

API_ROOT = Path(__file__).resolve().parents[1]
_CODE = (
    "import django, os\n"
    "django.setup()\n"
    "import uadas_api.urls\n"
    "print(os.environ['MPLBACKEND'], bool(os.environ['MPLCONFIGDIR']))\n"
)


def _minimal_env(**extra: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "DJANGO_SETTINGS_MODULE": "uadas_api.settings.test",
    }
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return {**env, **extra}


def test_the_urlconf_imports_without_a_home_directory_or_a_display() -> None:
    result = subprocess.run(  # nosec B603
        [sys.executable, "-c", _CODE],
        cwd=API_ROOT,
        env=_minimal_env(),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-600:]
    assert result.stdout.split() == ["Agg", "True"]


def test_an_operators_own_matplotlib_settings_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MPLBACKEND", "svg")
    monkeypatch.setenv("MPLCONFIGDIR", "/somewhere/else")
    headless_plotting_defaults()
    assert os.environ["MPLBACKEND"] == "svg"
    assert os.environ["MPLCONFIGDIR"] == "/somewhere/else"

# File: apps/api/tests/test_hermetic_env.py
"""The in-process test run ignores a developer's OAuth credentials.

Why: ``settings/base.py`` reads ``GITHUB_CLIENT_ID`` / ``GOOGLE_CLIENT_ID`` (and secrets) from
the environment when Django's settings are first loaded. A developer who has them exported for
local sign-in would otherwise (a) get a provider installed in every test run, failing the tests
that expect none, and (b) crash *every* test at settings import if only one half of a pair is
set. ``uadas_api.pytest_env`` scrubs them, and it only works if it runs *before* pytest-django
reads the settings -- which a conftest cannot do (conftests load after pytest-django's setup),
hence a ``-p`` plugin named in ``addopts``. These tests start a real child pytest with the
variables exported to prove it. ``test_oauth_runtime.py`` is unaffected: it sets credentials
inside its own subprocesses, which do not go through this plugin.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
EnvBuilder = Callable[..., dict[str, str]]

# Asserts the live (in-process) settings have no provider: exactly what a leaked credential breaks.
TARGET = "tests/test_auth_flow.py::test_config_endpoint_bootstraps_the_csrf_cookie"


def _run_child_pytest(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", TARGET, "-q", "-p", "no:cacheprovider"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_control_the_child_run_passes_with_a_clean_environment(
    subprocess_env: EnvBuilder,
) -> None:
    result = _run_child_pytest(subprocess_env())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


@pytest.mark.parametrize(
    "leaked",
    [
        {"GITHUB_CLIENT_ID": "leaked-id", "GITHUB_CLIENT_SECRET": "leaked-secret"},
        {"GOOGLE_CLIENT_ID": "leaked-id", "GOOGLE_CLIENT_SECRET": "leaked-secret"},
        {"GITHUB_CLIENT_ID": "half-set-only-the-id"},
        {"GOOGLE_CLIENT_SECRET": "half-set-only-the-secret"},
    ],
    ids=["github-pair", "google-pair", "github-half", "google-half"],
)
def test_exported_oauth_credentials_do_not_leak_into_the_suite(
    subprocess_env: EnvBuilder, leaked: dict[str, str]
) -> None:
    result = _run_child_pytest(subprocess_env(**leaked))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout

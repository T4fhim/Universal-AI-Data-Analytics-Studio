# File: apps/api/tests/test_checks.py
"""Django's own system checks pass, including the deployment checklist for prod.

Why: ``manage.py check --deploy`` is the cheapest guard against shipping a weak
security configuration, so Phase 3.1 pins it green with *valid* production env vars
and CI repeats it in the ``api-test`` job. The ``--deploy`` run is a real child process
so it sees exactly what a container would: no pytest, no test settings, no leaked
module state.
"""

from __future__ import annotations

import secrets
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from django.core.management import call_command

API_ROOT = Path(__file__).resolve().parents[1]
EnvBuilder = Callable[..., dict[str, str]]


def _manage(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.django_db  # JSONField checks (3.2 models) consult the DB connection's features
def test_check_passes_under_test_settings() -> None:
    call_command("check")


def test_check_deploy_passes_with_valid_prod_environment(
    subprocess_env: EnvBuilder,
) -> None:
    env = subprocess_env(
        DJANGO_SETTINGS_MODULE="uadas_api.settings.prod",
        DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
        DJANGO_ALLOWED_HOSTS="api.example.com",
        DATABASE_URL="sqlite://:memory:",
        # Required since 3.3 (shared cache, mail relay, SPA address):
        REDIS_URL="redis://localhost:6379/0",
        DEFAULT_FROM_EMAIL="UADAS <no-reply@example.com>",
        EMAIL_HOST="smtp.example.com",
        FRONTEND_BASE_URL="https://app.example.com",
    )
    result = _manage(["check", "--deploy", "--fail-level", "WARNING"], env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no issues" in result.stdout


def test_manage_py_defaults_to_dev_settings(subprocess_env: EnvBuilder) -> None:
    result = _manage(["check"], subprocess_env())
    assert result.returncode == 0, result.stdout + result.stderr


def test_manage_py_with_prod_settings_and_no_env_refuses_to_start(
    subprocess_env: EnvBuilder,
) -> None:
    env = subprocess_env(DJANGO_SETTINGS_MODULE="uadas_api.settings.prod")
    result = _manage(["check"], env)
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr

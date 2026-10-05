# File: apps/api/tests/test_entrypoints.py
"""``wsgi`` / ``asgi`` fail closed: a production server must never start on dev settings.

Why: both modules default ``DJANGO_SETTINGS_MODULE`` to ``uadas_api.settings.prod`` (only
``manage.py`` defaults to dev). That default is the one thing standing between a container
started without configuration and a process running with ``DEBUG`` on, so it is pinned
here in a real child process with a scrubbed environment -- importing the module must
refuse without configuration and must select the prod settings with it.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
EnvBuilder = Callable[..., dict[str, str]]

VALID_PROD_ENV = {
    "DJANGO_SECRET_KEY": "k" * 60,
    "DJANGO_ALLOWED_HOSTS": "api.example.com",
    "DATABASE_URL": "sqlite://:memory:",
    "REDIS_URL": "redis://localhost:6379/0",
    "DEFAULT_FROM_EMAIL": "UADAS <no-reply@example.com>",
    "EMAIL_HOST": "smtp.example.com",
    "FRONTEND_BASE_URL": "https://app.example.com",
}


def _import(module: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    code = (
        f"import {module}\n"
        "from django.conf import settings\n"
        "print(settings.SETTINGS_MODULE, settings.DEBUG)\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("module", ["uadas_api.wsgi", "uadas_api.asgi"])
def test_entrypoint_refuses_to_start_unconfigured(
    subprocess_env: EnvBuilder, module: str
) -> None:
    result = _import(module, subprocess_env())
    assert result.returncode != 0, result.stdout
    assert "ImproperlyConfigured" in result.stderr


@pytest.mark.parametrize("module", ["uadas_api.wsgi", "uadas_api.asgi"])
def test_entrypoint_selects_prod_settings_with_debug_off(
    subprocess_env: EnvBuilder, module: str
) -> None:
    result = _import(module, subprocess_env(**VALID_PROD_ENV))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["uadas_api.settings.prod", "False"]

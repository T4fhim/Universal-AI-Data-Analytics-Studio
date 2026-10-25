# File: apps/api/uadas_api/settings/_env.py
"""Tiny environment-variable readers shared by the settings modules.

Why hand-rolled instead of ``django-environ``: the backend needs exactly four value
shapes (string, bool, comma list, int) and every extra dependency is one more thing in
the server image. Parsing is deliberately forgiving about whitespace but strict about
integers -- a typo such as ``DJANGO_SECURE_HSTS_SECONDS=a-lot`` must stop the process
at start-up (``ImproperlyConfigured``), not silently fall back to a weaker default.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def get_str(name: str, default: str = "") -> str:
    """Return the variable stripped of surrounding whitespace, or ``default``."""
    return os.environ.get(name, default).strip()


def get_bool(name: str, default: bool = False) -> bool:
    """Parse ``1/true/yes/on`` as True and ``0/false/no/off`` as False (any case).

    Unset or empty means ``default``. Anything else raises: a typo such as ``flase`` must
    not be read as False, which would silently switch a security flag (the HTTPS
    redirect) off.
    """
    raw = get_str(name)
    if not raw:
        return default
    value = raw.lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    raise ImproperlyConfigured(
        f"{name} must be one of 1/true/yes/on or 0/false/no/off, got {raw!r}."
    )


def get_list(name: str) -> list[str]:
    """Split a comma-separated variable, dropping blanks (unset gives ``[]``)."""
    return [item.strip() for item in get_str(name).split(",") if item.strip()]


def get_choice(name: str, choices: tuple[str, ...], default: str) -> str:
    """Return the variable upper-cased if it is one of ``choices``; unset gives ``default``.

    Anything else raises, for the same reason :func:`get_bool` does: a typo such as
    ``UADAS_CORE_LOG_LEVEL=verbose`` must stop start-up, not silently pick a level.
    """
    raw = get_str(name)
    if not raw:
        return default
    value = raw.upper()
    if value not in choices:
        raise ImproperlyConfigured(
            f"{name} must be one of {', '.join(choices)}, got {raw!r}."
        )
    return value


def get_int(name: str, default: int) -> int:
    """Parse an integer variable; unset or empty gives ``default``, junk raises."""
    raw = get_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be an integer, got {raw!r}.") from None

# File: apps/api/uadas_api/accounts/signals.py
"""Audit login and logout.

Why Django's ``user_logged_in`` / ``user_logged_out`` signals and not allauth's own: they
fire for every way a session begins or ends (allauth's headless login, an email-verification
login, a social login, ``Client.force_login`` in tests), so no path can log in unaudited.
The receivers only call :func:`~uadas_api.accounts.services.record_user_event`, which files
the event under the user's oldest organization and records ids only (no address, no IP, no
user agent). Connected from ``AccountsConfig.ready``.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from uadas_api.accounts.models import User
from uadas_api.accounts.services import record_user_event


@receiver(user_logged_in, dispatch_uid="uadas_audit_login")
def audit_login(sender: Any, user: Any, **kwargs: Any) -> None:
    if isinstance(user, User):
        record_user_event(user, "user.logged_in")


@receiver(user_logged_out, dispatch_uid="uadas_audit_logout")
def audit_logout(sender: Any, user: Any, **kwargs: Any) -> None:
    # `user` is None when an anonymous session is logged out: nothing to attribute.
    if isinstance(user, User):
        record_user_event(user, "user.logged_out")

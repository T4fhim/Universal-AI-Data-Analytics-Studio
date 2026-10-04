# File: apps/api/uadas_api/accounts/__init__.py
"""Accounts app: users and authentication (custom user model and allauth arrive in 3.2/3.3).

Why it exists empty: its label (``accounts``) is what ``AUTH_USER_MODEL`` will point at,
so the app is registered now, before any migration can reference it.
"""

from __future__ import annotations

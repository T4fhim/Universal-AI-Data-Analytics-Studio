# File: apps/api/uadas_api/__init__.py
"""``uadas_api`` -- the Django + Django Ninja backend (Phase 3 of the web transition).

Why this package exists: ``uadas_core`` is a framework-free library (an import-linter
contract forbids it from importing Django); everything web-shaped -- HTTP routing,
authentication, the database models of tenancy, background tasks -- lives here and
depends on the core, never the other way round. ``.importlinter`` enforces both
directions, and also keeps this package off ``uadas_core.plugins`` / ``.jobs``.
"""

from __future__ import annotations

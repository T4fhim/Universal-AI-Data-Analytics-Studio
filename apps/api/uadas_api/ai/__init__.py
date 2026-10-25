# File: apps/api/uadas_api/ai/__init__.py
"""AI assistant app: per-tenant assistant sessions over ``uadas_core.ai`` (later 3.x).

Why it exists empty: the assistant needs its own quotas and key handling (server-side,
env-only secrets), so it is a separate app from the start.
"""

from __future__ import annotations

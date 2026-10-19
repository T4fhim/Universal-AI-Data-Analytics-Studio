# File: apps/api/uadas_api/web/throttle.py
"""A small cache-backed throttle for the heavy endpoints (upload, stage run, chart render, report).

Why hand-rolled and not Ninja's ``throttle=`` classes: Ninja's throttles run *before* the path is
parsed, so they cannot key on the organization, and their read-modify-write of a timestamp list is
not atomic. The key here is ``user + organization + scope`` (one tenant's burst never spends
another's budget, and one user cannot drain a colleague's), and the counter is a *fixed window*:
``cache.add`` creates it with the window as its time-to-live and ``cache.incr`` is atomic on both
the local-memory and Redis caches. A fixed window admits up to twice the rate across a window
boundary; that is the accepted trade for atomicity and one cache round trip.

What this is not: a quota. Per-tenant row, storage, job-minute and token quotas are 3.8. The
limits live in :mod:`uadas_api.web.config` (``DEFAULT_THROTTLES``); a throttled request is the
standard ``429`` envelope (no ``Retry-After`` header: the SPA backs off on the error code).
"""

from __future__ import annotations

import uuid

from django.core.cache import cache

from uadas_api.web.config import api_config
from uadas_api.web.errors import ApiError

_PREFIX = "uadas:throttle"


def _parse(rate: str) -> tuple[int, int]:
    count, _, window = rate.partition("/")
    return int(count), int(window)


def _key(scope: str, user_id: uuid.UUID | str, org_id: uuid.UUID | str) -> str:
    return f"{_PREFIX}:{scope}:{user_id}:{org_id}"


def enforce(scope: str, user_id: uuid.UUID | str, org_id: uuid.UUID | str) -> None:
    """Count one call of ``scope`` for this user in this organization; ``429`` past the rate."""
    limit, window = _parse(api_config().rate_for(scope))
    key = _key(scope, user_id, org_id)
    cache.add(key, 0, timeout=window)  # no-op while the window is open
    try:
        used = cache.incr(key)
    except ValueError:  # the window expired between add and incr: start a new one
        cache.add(key, 1, timeout=window)
        used = 1
    if used > limit:
        raise ApiError(429, "Too many requests; please slow down.")

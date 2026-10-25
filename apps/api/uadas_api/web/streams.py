# File: apps/api/uadas_api/web/streams.py
"""Concurrent-stream caps and the database hygiene a long-lived response needs (3.7).

Why caps: an SSE stream holds a connection, a task and (while it polls) a few queries for as long
as it is open, so an unbounded number of them is a denial of service by one user or one tenant.
:func:`acquire` counts open streams in the shared cache -- per user *and* per organization, per
kind (``job`` / ``assistant``) -- and refuses past the cap with the standard ``429`` envelope.

The counters are **leases**, released on every exit path: the stream generator's ``finally`` (a
normal end, an error, a client disconnect, which Django delivers as cancellation) and the
response's ``close`` (a client that vanished before the first chunk, when the generator never
ran). :meth:`StreamLease.release` is idempotent, so doing both is correct. A process that is
killed outright cannot release; each counter carries a time-to-live of twice the longest stream
plus a minute, so a leaked count heals itself, and an expiry can only make a cap briefly looser,
never wedge it shut. They are the same fixed-window ``cache.add`` / atomic ``cache.incr`` idiom as
:mod:`uadas_api.web.throttle` (which counts *requests*; this counts *open streams*).

:func:`release_connections` exists because Django opens a database connection per request thread
and keeps it for ``CONN_MAX_AGE`` -- fine for a request that lasts milliseconds, a leak for one that
lasts fifteen minutes. A stream calls it after every burst of queries, so nothing is held across a
sleep (and no transaction ever is: the queries are single autocommit statements).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from django.core.cache import cache
from django.db import connections

from uadas_api.web.errors import ApiError

_logger = logging.getLogger(__name__)
_PREFIX = "uadas:streams"


def _bump(key: str, ttl: int) -> int:
    cache.add(key, 0, timeout=ttl)  # no-op while the counter exists
    try:
        used = int(cache.incr(key))
    except ValueError:  # expired between add and incr: start over
        cache.add(key, 1, timeout=ttl)
        return 1
    # ``add`` never extends a live counter, so without this the counter would expire ``ttl`` seconds
    # after its creation even while streams are open, and later releases would corrupt a new one.
    cache.touch(key, ttl)
    return used


@dataclass
class StreamLease:
    """One held slot per counter key; :meth:`release` gives them all back, once."""

    keys: tuple[str, ...]
    _released: bool = field(default=False, repr=False)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        for key in self.keys:
            try:
                cache.decr(key)
            except ValueError:  # the counter expired: nothing to give back
                continue
            except Exception as error:  # noqa: BLE001
                # a cache outage must not break a close path
                _logger.warning(
                    "a stream cap could not be released (%s)", type(error).__name__
                )


def acquire(
    kind: str,
    user_id: uuid.UUID | str,
    org_id: uuid.UUID | str,
    *,
    user_cap: int,
    org_cap: int,
    max_seconds: float,
) -> StreamLease:
    """Take one slot for ``user_id`` and one for ``org_id``, or raise ``429`` (nothing held).

    A cache outage is a ``503``, not a bypass: a cap that cannot be counted is not a cap.
    """
    ttl = int(max_seconds * 2) + 60
    user_key = f"{_PREFIX}:{kind}:user:{org_id}:{user_id}"
    org_key = f"{_PREFIX}:{kind}:org:{org_id}"
    taken: list[str] = []
    try:
        for key, cap in ((user_key, user_cap), (org_key, org_cap)):
            used = _bump(key, ttl)
            taken.append(key)
            if used > cap:
                StreamLease(tuple(taken)).release()
                raise ApiError(429, "Too many open streams; close one and retry.")
    except ApiError:
        raise
    except Exception as error:  # noqa: BLE001
        # any cache failure is a refusal, never a bypass
        StreamLease(tuple(taken)).release()
        _logger.warning("the stream caps are unavailable (%s)", type(error).__name__)
        raise ApiError(503, "Streaming is temporarily unavailable.") from None
    return StreamLease((user_key, org_key))


def release_connections() -> None:
    """Close this thread's database connections unless a transaction is open on them."""
    for connection in connections.all(initialized_only=True):
        if not connection.in_atomic_block:
            connection.close()

# File: apps/api/uadas_api/jobs/config.py
"""The queue's runtime knobs, read from ``settings.UADAS_JOBS`` at call time.

Why a typed snapshot and a function (not module-level constants): the values come from the
environment through ``settings/_jobs.py`` and must be readable from tests that
``override_settings`` them, so they are looked up each call. A frozen dataclass keeps callers
from reaching into the raw mapping by string key (a typo there is a ``KeyError`` in a worker at
three in the morning).

:func:`retry_delay` is the one place the backoff is computed: exponential from
``retry_backoff_base``, capped at ``retry_backoff_max`` (which ``settings/_jobs.py`` guarantees
is shorter than the broker's visibility timeout minus the time limit, so a retry countdown can
never outlive the message's invisibility), with jitter so that a Redis blip does not send every
failed job back at the same instant.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, replace

from django.conf import settings


@dataclass(frozen=True)
class JobsConfig:
    """Everything the job code needs from settings."""

    queue: str
    max_attempts: int
    stale_after_seconds: int
    retry_backoff_base: int
    retry_backoff_max: int
    requeue_after_seconds: int
    progress_interval_ms: int
    eager: bool
    # How often a running job's heartbeat thread beats (a fraction of ``stale_after_seconds``).
    heartbeat_interval_seconds: float = 30.0


def heartbeat_interval(config: JobsConfig) -> float:
    """Seconds between heartbeats: a quarter of the stale window, between 1 and 60 seconds.

    A quarter so that three consecutive beats can fail (a database blip, a long GC pause) before a
    healthy worker looks dead; at most a minute so the load is negligible; at least a second.
    """
    return float(max(1.0, min(60.0, config.stale_after_seconds / 4)))


def get_config() -> JobsConfig:
    """Snapshot ``settings.UADAS_JOBS`` (see ``settings/_jobs.py`` for what each means)."""
    raw = settings.UADAS_JOBS
    config = JobsConfig(
        queue=str(raw["queue"]),
        max_attempts=int(raw["max_attempts"]),
        stale_after_seconds=int(raw["stale_after_seconds"]),
        retry_backoff_base=int(raw["retry_backoff_base"]),
        retry_backoff_max=int(raw["retry_backoff_max"]),
        requeue_after_seconds=int(raw["requeue_after_seconds"]),
        progress_interval_ms=int(raw["progress_interval_ms"]),
        eager=bool(raw["eager"]),
    )
    return replace(config, heartbeat_interval_seconds=heartbeat_interval(config))


def retry_delay(
    attempt: int,
    config: JobsConfig | None = None,
    *,
    jitter: Callable[[], float] = random.random,
) -> float:
    """Seconds to wait before attempt ``attempt + 1``, after ``attempt`` failed (1-based).

    ``base * 2**(attempt - 1)``, capped at the maximum, then scaled into 50-100 % of itself by
    ``jitter()`` (a function returning 0..1, injectable for tests). Never negative, never above
    ``retry_backoff_max``.
    """
    cfg = config or get_config()
    raw = cfg.retry_backoff_base * (2 ** max(attempt - 1, 0))
    capped = min(raw, cfg.retry_backoff_max)
    return float(capped) * (0.5 + 0.5 * jitter())

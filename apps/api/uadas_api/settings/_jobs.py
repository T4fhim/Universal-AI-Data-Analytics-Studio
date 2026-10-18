# File: apps/api/uadas_api/settings/_jobs.py
"""Job-queue and parser-sandbox settings: strict parsing, safe defaults, fail-closed production.

Why beside the settings and not in ``uadas_api.jobs``: these are *configuration* rules (what the
environment may say), evaluated at import time before the app registry exists. The runtime
halves are :mod:`uadas_api.jobs` and :mod:`uadas_api.sandbox`.

What is enforced, and why each exists:

* **JSON only, always.** Celery can deserialize pickle; a pickle in a broker message is remote
  code execution for anyone who can write to the broker. ``accept_content`` is ``["json"]`` and
  nothing here can change it.
* **Late acknowledgement, bounded redelivery.** A task is acknowledged after it finishes, so a
  worker that dies mid-task has its message redelivered; ``reject_on_worker_lost`` extends that
  to a worker killed by the OOM killer or a hard time limit. A poison task that keeps killing
  its worker is stopped by the *database* attempt counter (``JOBS_MAX_ATTEMPTS``), not by the
  broker.
* **The visibility timeout is longer than any task can run.** Redis redelivers an unacknowledged
  message after ``visibility_timeout`` seconds -- including a task that is merely still running,
  and including one waiting out a retry countdown. So it must exceed the hard time limit plus the
  longest backoff; the parser refuses a configuration where it does not.
* **A broker is required in production, eager mode is not allowed there.** Eager mode runs a
  task inline in the calling process; it exists so the test suite is hermetic and a laptop works
  without Redis, and it would silently put a job into a web request.
* **The sandbox's limits must be enforceable in production** (``validate_for_production``).
  Memory and CPU rlimits exist only on POSIX and are meaningful on Linux; a deployment that
  cannot enforce them would parse hostile files unprotected, so it does not start.
* **Production must say what isolates the parser child.** A child of the worker's own uid reads
  the worker's files, so a dedicated uid (``SANDBOX_CHILD_UID``/``GID``) or the operator's
  statement that a container does the separating is required, as is an explicit answer to how the
  child's network is cut off (``SANDBOX_NETWORK_ISOLATION``): the in-process socket guard is
  bypassable and is never counted as enforcement.
* **The timeouts nest** (``validate_consistency``): the sandbox's wall clock is shorter than the
  heartbeat window and than the Celery hard limit (by more than a minute), or a valid long parse
  is requeued mid-run or killed before the sandbox can report its own timeout.
* **The queue does not share the cache's Redis database**: ``cache.clear()`` flushes a whole
  database, queued messages included. ``REDIS_URL`` alone is moved to another database number and
  production refuses a collision.

Values come from the environment as plain names (documented in ``apps/api/README.md``); an
unknown or malformed value raises :class:`~django.core.exceptions.ImproperlyConfigured` naming
the variable, never silently picking a default. The functions take the environment as an
argument so tests need not touch ``os.environ``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from django.core.exceptions import ImproperlyConfigured

from uadas_api.sandbox.limits import (
    KIB,
    MIB,
    NETWORK_ISOLATION_MODES,
    SandboxLimits,
)

# The sandbox's wall clock, the job's staleness window and the Celery hard limit are one
# chain: a job must be allowed to run (and be seen alive) for longer than the parse it contains.
TIMEOUT_MARGIN_SECONDS = 60

SWEEP_INTERVAL_SECONDS = 60.0
SWEEP_TASK_NAME = "uadas.jobs.sweep"

_QUEUE_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}")
_BROKER_SCHEMES = ("redis://", "rediss://", "memory://")
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def _text(env: Mapping[str, str], name: str, default: str = "") -> str:
    return env.get(name, default).strip()


def _int(
    env: Mapping[str, str], name: str, default: int, *, low: int, high: int
) -> int:
    raw = _text(env, name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be an integer, got {raw!r}.") from None
    if not low <= value <= high:
        raise ImproperlyConfigured(
            f"{name} must be between {low} and {high}, got {value}."
        )
    return value


def _flag(env: Mapping[str, str], name: str) -> bool:
    raw = _text(env, name).lower()
    if not raw:
        return False
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    raise ImproperlyConfigured(
        f"{name} must be one of 1/true/yes/on or 0/false/no/off."
    )


def _redis_db(parts: SplitResult) -> int:
    path = parts.path.strip("/")
    return int(path) if path.isdigit() else 0


def distinct_broker_url(redis_url: str) -> str:
    """A broker URL on the same Redis server as ``redis_url`` but a different database number.

    Why: Django's cache backend honours ``cache.clear()`` (and a dev's ``FLUSHDB``) by wiping
    the whole Redis *database*; if the queue shared it, one ``clear()`` would silently delete every
    queued job message. Database 1 unless the cache is on 1 (then 2). Credentials, host, port,
    scheme and query are kept.
    """
    parts = urlsplit(redis_url)
    database = 1 if _redis_db(parts) != 1 else 2
    return urlunsplit(parts._replace(path=f"/{database}"))


def redis_namespaces_collide(cache_url: str, broker_url: str) -> bool:
    """Whether the cache and the broker would share one Redis database (same server, same number)."""
    cache, broker = urlsplit(cache_url), urlsplit(broker_url)
    if not (cache.hostname and broker.hostname):
        return False
    same_server = (cache.hostname.lower(), cache.port or 6379) == (
        broker.hostname.lower(),
        broker.port or 6379,
    )
    return same_server and _redis_db(cache) == _redis_db(broker)


def parse_jobs(
    env: Mapping[str, str], *, broker_default: str = "", eager: bool | None = None
) -> dict[str, Any]:
    """Read the queue settings into the ``UADAS_JOBS`` mapping.

    The broker is ``CELERY_BROKER_URL``, else ``REDIS_URL`` moved to a *different database
    number* (:func:`distinct_broker_url`: the queue must not share a Redis database with the
    cache, whose ``clear()`` would flush it), else ``broker_default`` (only ``dev`` passes one),
    else empty -- "no broker configured", which production refuses. ``eager`` overrides
    ``JOBS_EAGER`` (the ``test`` settings force ``True``).
    """
    redis_url = _text(env, "REDIS_URL")
    broker = (
        _text(env, "CELERY_BROKER_URL")
        or (distinct_broker_url(redis_url) if redis_url else "")
        or broker_default
    )
    if broker and not broker.startswith(_BROKER_SCHEMES):
        # Deliberately not echoed: a broker URL may carry a password.
        raise ImproperlyConfigured(
            "CELERY_BROKER_URL must be a redis:// or rediss:// URL (memory:// for tests)."
        )
    max_attempts = _int(env, "JOBS_MAX_ATTEMPTS", 3, low=1, high=10)
    # Must exceed the sandbox's wall clock plus a margin (``validate_consistency``); the worker
    # also heartbeats from a thread for the whole run, so this is the window for a *dead* worker.
    stale_after = _int(env, "JOBS_STALE_AFTER_SECONDS", 300, low=30, high=3600)
    soft = _int(env, "JOBS_SOFT_TIME_LIMIT_SECONDS", 600, low=10, high=86_400)
    hard = _int(env, "JOBS_TIME_LIMIT_SECONDS", soft + 60, low=11, high=90_000)
    if hard <= soft:
        raise ImproperlyConfigured(
            "JOBS_TIME_LIMIT_SECONDS must be greater than JOBS_SOFT_TIME_LIMIT_SECONDS."
        )
    backoff_base = _int(env, "JOBS_RETRY_BACKOFF_BASE_SECONDS", 5, low=1, high=300)
    backoff_max = _int(env, "JOBS_RETRY_BACKOFF_MAX_SECONDS", 120, low=1, high=900)
    # Redis redelivers anything unacknowledged for this long, a retry countdown included.
    visibility = _int(
        env,
        "JOBS_VISIBILITY_TIMEOUT_SECONDS",
        max(1800, hard + backoff_max + 600),
        low=60,
        high=7 * 86_400,
    )
    if visibility <= hard + backoff_max:
        raise ImproperlyConfigured(
            "JOBS_VISIBILITY_TIMEOUT_SECONDS must exceed JOBS_TIME_LIMIT_SECONDS plus "
            "JOBS_RETRY_BACKOFF_MAX_SECONDS, or Redis redelivers tasks that are still running."
        )
    queue = _text(env, "JOBS_QUEUE", "uadas-jobs")
    if _QUEUE_NAME.fullmatch(queue) is None:
        raise ImproperlyConfigured(
            "JOBS_QUEUE must be 1-64 letters, digits, '.', '_' or '-'."
        )
    return {
        "broker_url": broker,
        "eager": _flag(env, "JOBS_EAGER") if eager is None else eager,
        "queue": queue,
        "max_attempts": max_attempts,
        "stale_after_seconds": stale_after,
        "soft_time_limit": soft,
        "time_limit": hard,
        "retry_backoff_base": backoff_base,
        "retry_backoff_max": backoff_max,
        "visibility_timeout": visibility,
        "requeue_after_seconds": _int(
            env, "JOBS_REQUEUE_AFTER_SECONDS", 300, low=30, high=86_400
        ),
        "progress_interval_ms": _int(
            env, "JOBS_PROGRESS_INTERVAL_MS", 1000, low=0, high=60_000
        ),
    }


def hermetic_jobs() -> dict[str, Any]:
    """The mapping the ``test`` settings use: eager, in-memory broker, never the environment."""
    jobs = parse_jobs({}, broker_default="memory://", eager=True)
    jobs["progress_interval_ms"] = 0  # tests assert on every write; no clock in the way
    return jobs


def celery_settings(jobs: Mapping[str, Any]) -> dict[str, Any]:
    """The ``CELERY_*`` Django settings (``namespace="CELERY"``) for a parsed ``jobs`` mapping."""
    return {
        "CELERY_BROKER_URL": jobs["broker_url"],
        "CELERY_RESULT_BACKEND": None,  # job state is the database row, not a result store
        "CELERY_TASK_IGNORE_RESULT": True,
        "CELERY_ACCEPT_CONTENT": ["json"],
        "CELERY_TASK_SERIALIZER": "json",
        "CELERY_RESULT_SERIALIZER": "json",
        "CELERY_EVENT_SERIALIZER": "json",
        "CELERY_TASK_ACKS_LATE": True,
        "CELERY_TASK_REJECT_ON_WORKER_LOST": True,
        "CELERY_WORKER_PREFETCH_MULTIPLIER": 1,
        "CELERY_WORKER_MAX_TASKS_PER_CHILD": 100,
        "CELERY_WORKER_HIJACK_ROOT_LOGGER": False,
        "CELERY_TASK_SOFT_TIME_LIMIT": jobs["soft_time_limit"],
        "CELERY_TASK_TIME_LIMIT": jobs["time_limit"],
        "CELERY_TASK_DEFAULT_QUEUE": jobs["queue"],
        "CELERY_TASK_ALWAYS_EAGER": jobs["eager"],
        # Off even when eager: with it on, Celery re-raises its own ``Retry`` out of an eager
        # call instead of re-running the task inline, which breaks the retry path under test.
        # A bug cannot hide: ``execute_job`` turns every handler exception into a failed job.
        "CELERY_TASK_EAGER_PROPAGATES": False,
        "CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP": True,
        "CELERY_BROKER_TRANSPORT_OPTIONS": {
            "visibility_timeout": jobs["visibility_timeout"],
            "socket_timeout": 30,
            "socket_connect_timeout": 10,
            "health_check_interval": 30,
        },
        "CELERY_BEAT_SCHEDULE": {
            "uadas-sweep-stale-jobs": {
                "task": SWEEP_TASK_NAME,
                "schedule": SWEEP_INTERVAL_SECONDS,
            }
        },
    }


def _megabytes(
    env: Mapping[str, str], name: str, default_mb: int, *, low: int, high: int
) -> int:
    return _int(env, name, default_mb, low=low, high=high) * MIB


def _choice(
    env: Mapping[str, str], name: str, allowed: tuple[str, ...], default: str = ""
) -> str:
    value = _text(env, name).lower() or default
    if value not in allowed:
        choices = ", ".join(repr(a) for a in allowed if a)
        raise ImproperlyConfigured(f"{name} must be one of {choices} (or unset).")
    return value


def _parse_isolation(env: Mapping[str, str]) -> dict[str, Any]:
    """``SANDBOX_CHILD_UID/GID``, ``SANDBOX_NETWORK_ISOLATION``, ``SANDBOX_ISOLATION_ACKNOWLEDGED``.

    The uid and gid travel together (a dedicated user needs both) and may not be root.
    """
    raw_uid, raw_gid = _text(env, "SANDBOX_CHILD_UID"), _text(env, "SANDBOX_CHILD_GID")
    if bool(raw_uid) != bool(raw_gid):
        raise ImproperlyConfigured(
            "SANDBOX_CHILD_UID and SANDBOX_CHILD_GID must be set together (or not at all)."
        )
    child_uid = child_gid = None
    if raw_uid:
        child_uid = _int(env, "SANDBOX_CHILD_UID", 0, low=1, high=2**31 - 1)
        child_gid = _int(env, "SANDBOX_CHILD_GID", 0, low=1, high=2**31 - 1)
    return {
        "child_uid": child_uid,
        "child_gid": child_gid,
        "network_isolation": _choice(
            env, "SANDBOX_NETWORK_ISOLATION", NETWORK_ISOLATION_MODES
        ),
        "isolation_acknowledged": _choice(
            env, "SANDBOX_ISOLATION_ACKNOWLEDGED", ("", "container")
        ),
    }


def validate_consistency(jobs: Mapping[str, Any], sandbox: Mapping[str, Any]) -> None:
    """Refuse timeouts that cannot hold together (every environment, not only production).

    A job's heartbeat window and the Celery hard time limit must both exceed the sandbox's wall
    clock by a margin: otherwise a *valid* parse that is still within its limit is declared dead
    (requeued and run twice) or killed by the worker framework before the sandbox's own timeout
    can report it.
    """
    wall = float(sandbox["wall_seconds"])
    if jobs["stale_after_seconds"] <= wall + TIMEOUT_MARGIN_SECONDS:
        raise ImproperlyConfigured(
            "JOBS_STALE_AFTER_SECONDS must exceed SANDBOX_WALL_SECONDS by more than "
            f"{TIMEOUT_MARGIN_SECONDS} seconds, or a long valid parse is requeued mid-run."
        )
    if jobs["time_limit"] <= wall + TIMEOUT_MARGIN_SECONDS:
        raise ImproperlyConfigured(
            "JOBS_TIME_LIMIT_SECONDS must exceed SANDBOX_WALL_SECONDS by more than "
            f"{TIMEOUT_MARGIN_SECONDS} seconds, or the worker is killed before the sandbox "
            "can time its own child out."
        )


def parse_sandbox(env: Mapping[str, str]) -> dict[str, Any]:
    """Read ``SANDBOX_*`` into the ``UADAS_SANDBOX`` mapping (the fields of :class:`SandboxLimits`)."""
    root = _text(env, "SANDBOX_TMP_ROOT")
    if root and not (
        PurePosixPath(root).is_absolute() or PureWindowsPath(root).is_absolute()
    ):
        raise ImproperlyConfigured(
            "SANDBOX_TMP_ROOT must be an absolute path (or unset)."
        )
    config: dict[str, Any] = {
        "wall_seconds": float(_int(env, "SANDBOX_WALL_SECONDS", 120, low=1, high=3600)),
        "cpu_seconds": _int(env, "SANDBOX_CPU_SECONDS", 120, low=1, high=3600),
        "memory_bytes": _megabytes(
            env, "SANDBOX_MEMORY_MB", 4096, low=256, high=262_144
        ),
        "max_input_bytes": _megabytes(
            env, "SANDBOX_MAX_INPUT_MB", 100, low=1, high=10_240
        ),
        "max_output_bytes": _megabytes(
            env, "SANDBOX_MAX_OUTPUT_MB", 512, low=1, high=10_240
        ),
        "max_rows": _int(
            env, "SANDBOX_MAX_ROWS", 10_000_000, low=1, high=2_000_000_000
        ),
        "max_columns": _int(env, "SANDBOX_MAX_COLUMNS", 5000, low=1, high=100_000),
        "max_response_bytes": 256 * KIB,
        "max_open_files": 256,
        "process_headroom": _int(env, "SANDBOX_PROCESS_HEADROOM", 64, low=0, high=4096),
        "max_archive_entries": _int(
            env, "SANDBOX_MAX_ARCHIVE_ENTRIES", 10_000, low=1, high=1_000_000
        ),
        "max_decompressed_bytes": _megabytes(
            env, "SANDBOX_MAX_DECOMPRESSED_MB", 1024, low=1, high=102_400
        ),
        "max_compression_ratio": _int(
            env, "SANDBOX_MAX_COMPRESSION_RATIO", 200, low=2, high=10_000
        ),
        "tmp_root": root,
        **_parse_isolation(env),
    }
    if config["max_input_bytes"] > config["max_decompressed_bytes"]:
        raise ImproperlyConfigured(
            "SANDBOX_MAX_INPUT_MB must not exceed SANDBOX_MAX_DECOMPRESSED_MB."
        )
    SandboxLimits.from_mapping(
        config
    )  # one more check, by the type that will use the numbers
    return config


def validate_for_production(
    jobs: Mapping[str, Any],
    sandbox: Mapping[str, Any],
    *,
    enforceable: bool,
    cache_url: str = "",
) -> None:
    """Refuse a production configuration without a real broker, or where the sandbox is toothless.

    ``enforceable`` is :func:`uadas_api.sandbox.limits.limits_enforceable` (passed in so the
    check is testable on any platform); ``cache_url`` is the cache's Redis URL (the queue must
    not share its database). Beyond the platform, production demands an *explicit* answer to the
    two isolation questions the code cannot answer for itself:

    * what separates the parser child from the worker and from other jobs -- a dedicated uid
      (``SANDBOX_CHILD_UID``/``GID``) or the operator's statement that a container does
      (``SANDBOX_ISOLATION_ACKNOWLEDGED=container``);
    * what gives it no network -- ``SANDBOX_NETWORK_ISOLATION`` = ``unshare`` (refuse a parse
      whose child could not isolate), ``container`` (the deployment gives the worker no network)
      or ``none-acknowledged`` (the operator accepts the bypassable in-process shim alone).
    """
    broker = str(jobs["broker_url"])
    if not broker:
        raise ImproperlyConfigured(
            "CELERY_BROKER_URL (or REDIS_URL) must be set for production: background jobs "
            "need a durable queue."
        )
    if broker.startswith("memory://"):
        raise ImproperlyConfigured(
            "CELERY_BROKER_URL must be a real Redis URL in production, not memory://."
        )
    if jobs["eager"]:
        raise ImproperlyConfigured(
            "JOBS_EAGER is not allowed in production: it would run jobs inside web requests."
        )
    if not enforceable:
        raise ImproperlyConfigured(
            "The parser sandbox cannot enforce memory and CPU limits on this platform "
            "(it needs Linux); refusing to start. Run the API and its workers on Linux."
        )
    if cache_url and redis_namespaces_collide(cache_url, broker):
        raise ImproperlyConfigured(
            "The job queue and the cache must use different Redis databases: the cache's "
            "clear() flushes its whole database, queued jobs included. Set CELERY_BROKER_URL "
            "to another database number (REDIS_URL alone is moved to one automatically)."
        )
    if (
        sandbox.get("child_uid") is None
        and sandbox.get("isolation_acknowledged") != "container"
    ):
        raise ImproperlyConfigured(
            "Production needs the parser child separated from the worker: set "
            "SANDBOX_CHILD_UID and SANDBOX_CHILD_GID (a dedicated, unprivileged user; the worker "
            "then needs root or CAP_SETUID/SETGID/CHOWN), or SANDBOX_ISOLATION_ACKNOWLEDGED="
            "container if the worker runs in a container that does the separating. A child "
            "running as the worker's own user can read the worker's files and other jobs'."
        )
    if not sandbox.get("network_isolation"):
        raise ImproperlyConfigured(
            "Production needs an explicit SANDBOX_NETWORK_ISOLATION: 'unshare' (refuse a parse "
            "whose child could not unshare a network namespace), 'container' (the worker has no "
            "route out) or 'none-acknowledged' (accept the bypassable in-process socket guard)."
        )

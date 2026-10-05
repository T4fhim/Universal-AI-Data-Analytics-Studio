# File: apps/api/uadas_api/core_bridge.py
"""The API's one doorway to the framework-free core's per-user sessions.

Why: ``uadas_core`` can serve many tenants from one process only if its process half is
built exactly once, in *server mode*, and every request then gets a session of its own
(plans/phase-3-session-seam.md). This module owns both halves of that contract so no
view, task or service ever calls ``bootstrap_process`` / ``build_session`` itself:

* :func:`get_process_context` -- lazy, cached and thread-safe. Server mode means plugins
  are never loaded (the plugin package is not even imported), no YAML is read or written,
  logging goes to stderr and the process-global job-runner bridge is not installed.
* :func:`new_session` -- a fresh child container per call, holding the stateful per-user
  services (workspace, settings, analysis log, ...). Two sessions share nothing mutable.

Deliberately **not** here: any endpoint, and any storage/persistence wiring. A session
built here is empty; loading a tenant's datasets into it from object storage is 3.4. The
job runner is reached only as ``get_process_context().job_runner`` -- ``uadas_api`` must
not import ``uadas_core.jobs`` or ``uadas_core.plugins`` (``.importlinter``, contract
``api-avoids-plugins-and-jobs``), and the static import chain through ``uadas_core.
bootstrap`` is the one narrow, documented exception to that contract's indirect check.
"""

from __future__ import annotations

import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from uadas_core.bootstrap import ProcessContext, bootstrap_process, build_session
from uadas_core.core.config import AppConfig
from uadas_core.core.dependency_container import DependencyContainer

# Guards the build-once. A lock rather than ``functools.cache``: the build has side
# effects (logging, a thread pool) that must happen exactly once even if two requests
# arrive together on a cold worker, and ``reset_process_context`` needs to clear it.
_lock = threading.Lock()
_process: ProcessContext | None = None


def build_core_config() -> AppConfig:
    """Return the core's configuration, built from Django settings -- never from a file.

    Starts from the core's in-code defaults (:meth:`AppConfig.defaults`) and overlays the
    values the API owns. Server mode normalises the rest (plugins off, no desktop
    ``recent_projects`` / saved database profiles).
    """
    level: str = settings.UADAS_CORE_LOG_LEVEL
    # DEBUG is where the core logs per-state-change detail from every tenant's session
    # into one shared stream. It is a development aid, so it needs Django's DEBUG too
    # (checked here, against the *final* settings, so it holds for every settings module;
    # prod additionally refuses it at start-up).
    if level == "DEBUG" and not settings.DEBUG:
        raise ImproperlyConfigured(
            "UADAS_CORE_LOG_LEVEL=DEBUG is only allowed when Django DEBUG is on: core "
            "debug logs are shared by every tenant's session."
        )
    data = AppConfig.defaults().to_dict()
    data["logging"]["level"] = level
    return AppConfig.from_dict(data)


def get_process_context() -> ProcessContext:
    """Return the process-wide core context, building it (once) on first use."""
    global _process
    process = _process
    if process is not None:  # fast path: no lock once built
        return process
    with _lock:
        if _process is None:
            _process = bootstrap_process(server_mode=True, config=build_core_config())
        return _process


def new_session() -> DependencyContainer:
    """Return a fresh, empty per-user session container (a child of the process one)."""
    return build_session(get_process_context())


def reset_process_context() -> None:
    """Close and forget the cached process context. For tests and clean shutdown only.

    A new :func:`get_process_context` call rebuilds it. Sessions already handed out keep
    working for their own services but lose the (closed) shared runner.
    """
    global _process
    with _lock:
        if _process is not None:
            _process.close()
            _process = None

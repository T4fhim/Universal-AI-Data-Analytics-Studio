# File: apps/api/uadas_api/web/config.py
"""The API surface's tunable limits, in one frozen record read from ``settings.UADAS_API``.

Why one record: page sizes, body caps, the preview/render row caps and the per-route throttles
are the numbers a reviewer wants to see together and a test wants to override in one place
(``settings.UADAS_API = {...}``). Nothing here is read from the environment on purpose: these
are product limits, not deployment secrets, and an operator who needs different ones sets the
Django setting in a settings module (full per-tenant quotas are 3.8, not here).

Throttle rates are ``"<count>/<window seconds>"`` per **user and organization** (see
:mod:`uadas_api.web.throttle`); only the heavy endpoints have one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

MIB = 1024 * 1024

DEFAULT_THROTTLES: dict[str, str] = {
    "upload": "30/3600",  # 30 uploads per hour
    "run": "120/3600",  # 120 stage runs per hour
    "render": "600/3600",  # 600 synchronous chart renders per hour
    "report": "30/3600",  # 30 report builds per hour
    # Preview pages and column summaries each copy and hash the whole Parquet object from the
    # store: generous for a scrolling grid (2 a second), bounded for a loop.
    "preview": "120/60",
    "assistant": "60/3600",  # 60 assistant turns per hour per user+organization (3.7)
    "assistant_user": "120/3600",  # ... and 120 per user across all their organizations
}


@dataclass(frozen=True)
class ApiConfig:
    """Every cap the API surface applies."""

    max_page_size: int = 200
    default_page_size: int = 50
    max_offset: int = 1_000_000
    # (The JSON body cap is Django's DATA_UPLOAD_MAX_MEMORY_SIZE, 1 MiB, in settings/base.py: one
    # number, also used for the declared size of any multipart body on a non-upload route.)
    # Preview: the page-size cap, and the biggest frame a *sorted* page will read a column of.
    preview_max_rows: int = 200
    preview_max_sort_rows: int = 2_000_000
    # A synchronous chart render looks at no more than this many rows (below the core's
    # 5,000-row plotly-resampler threshold) and returns no more than this many bytes of JSON.
    render_max_rows: int = 5_000
    render_max_figure_bytes: int = 2 * MIB
    # A stage job refuses a frame with more rows than this (it loads the frame into pandas).
    stage_max_rows: int = 2_000_000
    # A stage result stored on the job row (tables are capped by the renderers; figures here).
    stage_max_result_bytes: int = 4 * MIB
    max_parameters_bytes: int = 16 * 1024
    # --- streaming (3.7): see plans/phase-3-7-streaming.md -----------------------------------
    # Job-progress stream: DB poll cadence (jittered, backing off while nothing changes), the
    # comment-frame interval that keeps proxies from closing an idle stream, the reconnect delay
    # the browser is told to use, a hard ceiling on one stream's life, how often membership is
    # re-checked while it is open, and the cap on one event's encoded size.
    sse_poll_seconds: float = 1.0
    sse_poll_max_seconds: float = 5.0
    sse_heartbeat_seconds: float = 15.0
    sse_retry_ms: int = 3000
    sse_max_seconds: float = 900.0
    sse_recheck_seconds: float = 30.0
    sse_max_event_bytes: int = 16 * 1024
    # Concurrent open job streams, per user (within one organization) and per organization.
    stream_user_cap: int = 5
    stream_org_cap: int = 50
    # Assistant turn: bounds on what a client may send and how long one provider call may take.
    assistant_max_message_chars: int = 8_000
    assistant_max_history: int = 20
    assistant_max_history_chars: int = 32_000
    assistant_turn_seconds: float = 90.0
    # One provider call's own time limit (SDK timeout, no SDK retries), and the process-wide number of
    # provider calls that may be in flight (each holds a thread until the call really ends).
    assistant_provider_seconds: float = 60.0
    assistant_max_inflight: int = 8
    assistant_max_event_bytes: int = 64 * 1024
    assistant_user_cap: int = 2
    assistant_org_cap: int = 10
    # Overrides only; ``rate_for`` falls back to DEFAULT_THROTTLES per scope.
    throttles: Mapping[str, str] = field(default_factory=dict)

    def rate_for(self, scope: str) -> str:
        """The ``"count/seconds"`` rate of ``scope`` (an unknown scope is a bug: KeyError)."""
        return {**DEFAULT_THROTTLES, **self.throttles}[scope]


def api_config() -> ApiConfig:
    """The active configuration: defaults overlaid with ``settings.UADAS_API`` (if set)."""
    overrides: Mapping[str, Any] = getattr(settings, "UADAS_API", {}) or {}
    return ApiConfig(**dict(overrides))

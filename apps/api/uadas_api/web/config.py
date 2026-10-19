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
}


@dataclass(frozen=True)
class ApiConfig:
    """Every cap the API surface applies."""

    max_page_size: int = 200
    default_page_size: int = 50
    max_offset: int = 1_000_000
    # The largest JSON request body (multipart file parts are capped separately, below).
    max_body_bytes: int = 1 * MIB
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
    # Overrides only; ``rate_for`` falls back to DEFAULT_THROTTLES per scope.
    throttles: Mapping[str, str] = field(default_factory=dict)

    def rate_for(self, scope: str) -> str:
        """The ``"count/seconds"`` rate of ``scope`` (an unknown scope is a bug: KeyError)."""
        return {**DEFAULT_THROTTLES, **self.throttles}[scope]


def api_config() -> ApiConfig:
    """The active configuration: defaults overlaid with ``settings.UADAS_API`` (if set)."""
    overrides: Mapping[str, Any] = getattr(settings, "UADAS_API", {}) or {}
    return ApiConfig(**dict(overrides))

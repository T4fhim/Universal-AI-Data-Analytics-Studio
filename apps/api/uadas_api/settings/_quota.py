# File: apps/api/uadas_api/settings/_quota.py
"""Per-tenant quota limits: strict parsing, unlimited in dev/test, explicit in production (3.8).

Why the limits are settings and not rows: a limit is the *operator's* statement about what one
organization may consume, so it comes from the deployment environment (like every other
operational knob) and is the default for every organization. A row in ``quotas.OrganizationQuota``
overrides it for one organization (a paid plan, a trial), and the database is never the only
place a limit exists -- an empty table still enforces the deployment's numbers.

Four resources, two window shapes:

* **Standing totals** (what the organization holds right now; released when the thing is deleted):
  ``QUOTA_MAX_ROWS`` (rows across the datasets it has ingested) and ``QUOTA_MAX_STORAGE_MB``
  (bytes of uploaded originals).
* **Calendar-month windows** (what it spent this UTC month; the counter simply starts again):
  ``QUOTA_MAX_JOB_MINUTES`` (wall-clock minutes of background-job runs) and
  ``QUOTA_MAX_LLM_TOKENS`` (input plus output tokens the assistant's provider reported).

Unset means *unlimited* in ``dev`` and ``test`` -- a laptop and the suite need no ceiling -- but
production refuses to start unless every limit is stated or the operator says, explicitly, that
unlimited is intended (``QUOTA_UNLIMITED_ACKNOWLEDGED=true``): an unmetered multi-tenant server is
a decision, never an omission (same shape as the sandbox's isolation statement). A malformed or
out-of-range value raises :class:`~django.core.exceptions.ImproperlyConfigured` naming the
variable, never silently picking a default and never echoing a value.

The parsed mapping keeps the *internal* units (bytes, seconds) so no consumer converts again;
``None`` is "no limit".
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from uadas_api.sandbox.limits import MIB

from ._jobs import _flag, _int, _text

_MAX_ROWS = 10**13
_MAX_MEGABYTES = 10**9
_MAX_MINUTES = 10**8
_MAX_TOKENS = 10**15

# env name -> key of the parsed mapping; the order is the order production reports a gap in.
LIMIT_VARIABLES: dict[str, str] = {
    "QUOTA_MAX_ROWS": "max_rows",
    "QUOTA_MAX_STORAGE_MB": "max_storage_bytes",
    "QUOTA_MAX_JOB_MINUTES": "max_job_seconds",
    "QUOTA_MAX_LLM_TOKENS": "max_llm_tokens",
}


def _optional(
    env: Mapping[str, str], name: str, *, high: int, scale: int = 1
) -> int | None:
    """The variable as a positive integer times ``scale``; unset or empty is ``None`` (unlimited)."""
    if not _text(env, name):
        return None
    return _int(env, name, 1, low=1, high=high) * scale


def parse_quota(env: Mapping[str, str]) -> dict[str, Any]:
    """Read ``QUOTA_*`` into the ``UADAS_QUOTA`` mapping (``None`` = unlimited)."""
    return {
        "max_rows": _optional(env, "QUOTA_MAX_ROWS", high=_MAX_ROWS),
        "max_storage_bytes": _optional(
            env, "QUOTA_MAX_STORAGE_MB", high=_MAX_MEGABYTES, scale=MIB
        ),
        "max_job_seconds": _optional(
            env, "QUOTA_MAX_JOB_MINUTES", high=_MAX_MINUTES, scale=60
        ),
        "max_llm_tokens": _optional(env, "QUOTA_MAX_LLM_TOKENS", high=_MAX_TOKENS),
        "unlimited_acknowledged": _flag(env, "QUOTA_UNLIMITED_ACKNOWLEDGED"),
    }


def validate_for_production(quota: Mapping[str, Any]) -> None:
    """Refuse a production configuration that leaves a resource unmetered without saying so.

    Every limit must be set, or ``QUOTA_UNLIMITED_ACKNOWLEDGED`` must be on (then an unset
    limit means unlimited, on purpose). The message names the variables that are missing.
    """
    if quota.get("unlimited_acknowledged"):
        return
    missing = [name for name, key in LIMIT_VARIABLES.items() if quota.get(key) is None]
    if missing:
        raise ImproperlyConfigured(
            "Production needs a per-organization quota for every resource: set "
            f"{', '.join(missing)}, or QUOTA_UNLIMITED_ACKNOWLEDGED=true to run "
            "deliberately unmetered."
        )

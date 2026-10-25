# File: apps/api/uadas_api/quotas/choices.py
"""The closed set of metered resources, and the window each is counted in.

Why a closed enum and not free-form strings: a ``kind`` selects a counter row, a limit field
(``OrganizationQuota.max_<kind>`` / ``settings.UADAS_QUOTA["max_<kind>"]``) and a window, and a typo
in any one of them would silently meter nothing. ``tests/test_quotas_models.py`` fails if a kind has
no matching limit field or setting.

Two window shapes, because the two families of resource behave differently:

* **Standing** (``rows``, ``storage_bytes``): what the organization *holds*. It goes up when data
  arrives and comes back down when the data is deleted, so there is one counter that never rolls
  over (``period_start`` is the fixed :data:`STANDING_PERIOD`).
* **Monthly** (``job_seconds``, ``llm_tokens``): what it *spent* this UTC calendar month. Spending
  cannot be un-spent, so the counter is per month and a new month starts at zero on its own -- no
  reset job exists to forget to run.
"""

from __future__ import annotations

import datetime
from enum import StrEnum

from django.db import models

# A fixed, never-reached "month" for the standing counters (so one unique constraint serves both).
STANDING_PERIOD = datetime.date(1970, 1, 1)


class UsageKind(models.TextChoices):
    """What is metered."""

    ROWS = "rows", "Rows"
    STORAGE_BYTES = "storage_bytes", "Stored bytes"
    JOB_SECONDS = "job_seconds", "Job seconds"
    LLM_TOKENS = "llm_tokens", "LLM tokens"


class Window(StrEnum):
    """How a kind's usage is counted over time."""

    STANDING = "standing"
    MONTHLY = "monthly"


WINDOW_OF: dict[str, Window] = {
    UsageKind.ROWS.value: Window.STANDING,
    UsageKind.STORAGE_BYTES.value: Window.STANDING,
    UsageKind.JOB_SECONDS.value: Window.MONTHLY,
    UsageKind.LLM_TOKENS.value: Window.MONTHLY,
}

# The sentence a refusal carries (fixed: it never holds a number, a key or an organization).
REFUSAL: dict[str, str] = {
    UsageKind.ROWS.value: "Your organization has reached its row quota.",
    UsageKind.STORAGE_BYTES.value: "Your organization has reached its storage quota.",
    UsageKind.JOB_SECONDS.value: "Your organization has used its background-job time for this month.",
    UsageKind.LLM_TOKENS.value: "Your organization has used its assistant tokens for this month.",
}


def period_start(kind: str, now: datetime.datetime) -> datetime.date:
    """The ``period_start`` that ``kind``'s usage falls in at ``now`` (UTC)."""
    if WINDOW_OF[kind] is Window.STANDING:
        return STANDING_PERIOD
    moment = now.astimezone(datetime.UTC)
    return datetime.date(moment.year, moment.month, 1)

# File: apps/api/uadas_api/quotas/errors.py
"""The quota refusal: one exception, a closed ``kind``, a fixed sentence.

Why it carries no numbers: the web layer turns this into ``429 quota_exceeded`` and the message
reaches the client (and a log line) as-is, so it holds neither the limit, the usage, the amount
asked for, nor the source key -- only which resource ran out, from the closed
:class:`~uadas_api.quotas.choices.UsageKind` set.
"""

from __future__ import annotations

from uadas_api.quotas.choices import REFUSAL


class QuotaExceededError(Exception):
    """A charge would take an organization over its limit for ``kind`` (or it is already at it)."""

    def __init__(self, kind: str) -> None:
        super().__init__(REFUSAL[kind])
        self.kind = kind

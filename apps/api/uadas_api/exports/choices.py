# File: apps/api/uadas_api/exports/choices.py
"""Report formats and lifecycle states, with the formats pinned to the core by a parity test.

Why ``ReportFormat`` mirrors the core: the formats a report can be generated in are the
keys of ``uadas_core.services.report_service`` ``_EXPORTERS`` (exposed as
``available_formats()``). Models must not import the core at runtime, so the values are
copied here and ``tests/test_choices_parity.py`` fails if the two ever disagree.

``ReportStatus`` is API-owned (the core generates a report synchronously and has no
lifecycle); it exists because report generation becomes a background job in 3.5.
"""

from __future__ import annotations

from django.db import models


class ReportFormat(models.TextChoices):
    """The file formats the core's report service can export."""

    PDF = "pdf", "PDF"
    HTML = "html", "HTML"
    DOCX = "docx", "Word"
    XLSX = "xlsx", "Excel"


class ReportStatus(models.TextChoices):
    """Where a report is in its generation lifecycle."""

    PENDING = "pending", "Pending"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"

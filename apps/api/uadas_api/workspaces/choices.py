# File: apps/api/uadas_api/workspaces/choices.py
"""Closed value sets for the workspace models, pinned to the core by a parity test.

Why defined here and not imported from ``uadas_core``: models must not import the core at
runtime (a migration that imports application code is a migration that breaks when that
code moves, and the core is a separate distribution). Why a *test* pins them anyway:
these lists mirror things the core owns -- the ``source_format`` string each reader stamps
on a dataset, and the chart names in the chart registry -- and a hand-copied list drifts
silently when the core adds a reader or a chart (CLAUDE.md, "Multi-file touchpoints").
``tests/test_choices_parity.py`` imports the core and fails the moment the two disagree.

Changing a value set is a migration-visible event (the choices are part of model state),
so a core change that trips the parity test needs a deliberate follow-up here.
"""

from __future__ import annotations

from django.db import models


class SourceFormat(models.TextChoices):
    """What a dataset was read from -- the ``Dataset.source_format`` a core reader sets."""

    CSV = "csv", "CSV"
    JSON = "json", "JSON"
    TXT = "txt", "Text"
    XLSX = "xlsx", "Excel (.xlsx)"
    XLS = "xls", "Excel (.xls)"
    SQLITE = "sqlite", "SQLite"
    PDF = "pdf", "PDF"
    DOCX = "docx", "Word"
    XML = "xml", "XML"
    IMAGE_OCR = "image_ocr", "Image (OCR)"
    ODS = "ods", "OpenDocument spreadsheet"
    YAML = "yaml", "YAML"
    PARQUET = "parquet", "Parquet"
    FEATHER = "feather", "Feather"
    PPTX = "pptx", "PowerPoint"
    HTML = "html", "HTML"


class ChartType(models.TextChoices):
    """The built-in chart names in the core's chart registry (``list_charts()``)."""

    BAR = "bar", "Bar"
    PIE = "pie", "Pie"
    LINE = "line", "Line"
    SCATTER = "scatter", "Scatter"
    HISTOGRAM = "histogram", "Histogram"
    BOX_PLOT = "box_plot", "Box plot"
    HEATMAP = "heatmap", "Heatmap"
    BUBBLE = "bubble", "Bubble"
    TREEMAP = "treemap", "Treemap"
    RADAR = "radar", "Radar"
    WATERFALL = "waterfall", "Waterfall"
    FUNNEL = "funnel", "Funnel"

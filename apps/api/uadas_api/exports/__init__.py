# File: apps/api/uadas_api/exports/__init__.py
"""Exports app: report, chart and dataset export jobs and their download links (later 3.x).

Why it exists empty: exports are long-running and produce stored artefacts, so they get
their own app (and job type) rather than living inside ``pipeline``.
"""

from __future__ import annotations

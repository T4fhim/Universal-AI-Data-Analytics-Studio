# File: apps/api/uadas_api/pipeline/__init__.py
"""Pipeline app: import, clean, analyse and forecast endpoints plus their jobs (3.5/3.6).

Why it exists empty: it is the web-side home of the work ``uadas_core`` already does;
keeping it a separate app keeps that HTTP/job glue out of the tenancy models.
"""

from __future__ import annotations

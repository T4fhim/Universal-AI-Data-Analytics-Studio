# File: uadas_core/cleaning/__init__.py
"""Data cleaning operations, each producing a new, lineage-tracked Dataset.

Depends on ``uadas_core.core`` and ``uadas_core.services`` (for ``Dataset`` and its
milestone 3a lineage fields) but nothing in either of those packages
depends back on this one — cleaning sits above both, alongside
``uadas_core.readers`` and ``src.ui``, in this project's layered
architecture.
"""

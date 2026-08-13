# File: src/cleaning/__init__.py
"""Data cleaning operations, each producing a new, lineage-tracked Dataset.

Depends on ``src.core`` and ``src.services`` (for ``Dataset`` and its
milestone 3a lineage fields) but nothing in either of those packages
depends back on this one — cleaning sits above both, alongside
``src.readers`` and ``src.ui``, in this project's layered
architecture.
"""

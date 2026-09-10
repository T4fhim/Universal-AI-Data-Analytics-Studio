# File: uadas_core/readers/__init__.py
"""Format-specific file readers, producing Dataset instances for WorkspaceService.

Depends on ``uadas_core.core`` and ``uadas_core.services`` (specifically,
``Dataset`` from ``uadas_core.services.workspace_service``) but nothing in
either of those packages depends back on this one — readers sit above
both in this project's layered architecture, alongside ``src.ui``.

Milestone 2a provides three readers: CSV/TSV, JSON, and plain text
(``uadas_core.readers.csv_reader``, ``uadas_core.readers.json_reader``,
``uadas_core.readers.text_reader``). Use
``uadas_core.readers.reader_registry.get_reader_for_path`` to find the right
reader for a given file rather than importing a specific reader
directly, unless the format is already known for certain.
"""

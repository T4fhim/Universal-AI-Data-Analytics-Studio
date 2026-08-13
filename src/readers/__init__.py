# File: src/readers/__init__.py
"""Format-specific file readers, producing Dataset instances for WorkspaceService.

Depends on ``src.core`` and ``src.services`` (specifically,
``Dataset`` from ``src.services.workspace_service``) but nothing in
either of those packages depends back on this one — readers sit above
both in this project's layered architecture, alongside ``src.ui``.

Milestone 2a provides three readers: CSV/TSV, JSON, and plain text
(``src.readers.csv_reader``, ``src.readers.json_reader``,
``src.readers.text_reader``). Use
``src.readers.reader_registry.get_reader_for_path`` to find the right
reader for a given file rather than importing a specific reader
directly, unless the format is already known for certain.
"""

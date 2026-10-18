# File: apps/api/uadas_api/sandbox/__init__.py
"""The parser sandbox (Phase 3.5/3.8): the only place untrusted files are ever parsed.

Why this package exists: ``uadas_core``'s readers feed untrusted PDF / Word / Excel / image /
XML / ZIP uploads to camelot, PyMuPDF, pdfplumber, python-docx, openpyxl, lxml, OpenCV and
Tesseract -- a large, well-known CVE surface. A reader therefore never runs in a web process
or in a job worker's own interpreter. It runs in a **child process** this package launches
with a minimal environment, resource limits, a network namespace where the kernel allows one, a
(bypassable, and therefore uncounted) socket guard and a wall-clock timeout, and the parent only
ever sees what the child chose to write: a Parquet file and a small JSON summary, both verified
before anything is trusted. What separates the child from the *worker* is a question of uid or
container, not of environment variables; see :mod:`~uadas_api.sandbox.isolation`.

The modules, and which side of the process boundary each is on:

* parent side (may import Django, must NEVER import a reader or a reader library):
  :mod:`~uadas_api.sandbox.admission` (extension + content signature before any parse),
  :mod:`~uadas_api.sandbox.runner` (spawn, supervise, kill the tree, verify the output),
  :mod:`~uadas_api.sandbox.limits`, :mod:`~uadas_api.sandbox.errors`,
  :mod:`~uadas_api.sandbox.isolation` (worker hardening, identity switch, stale-directory reaper).
* both sides, standard library only: :mod:`~uadas_api.sandbox.protocol`.
* child side: :mod:`~uadas_api.sandbox.guards` (hardening, rlimits, network namespace, socket guard;
  standard library only)
  and :mod:`~uadas_api.sandbox.child` (the one module that imports ``uadas_core.readers``).

``.importlinter`` (contract ``readers-only-in-the-sandbox-child``) fails the build if any
other ``uadas_api`` module imports ``uadas_core.readers`` or a reader library, and
``tests/test_sandbox_boundary.py`` proves in a fresh interpreter that importing the parent
side loads none of them. This ``__init__`` imports nothing on purpose: the child starts with
``python -I -m uadas_api.sandbox.child`` and must not load Django.
"""

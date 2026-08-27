# File: src/workers/__init__.py
"""Background-execution infrastructure (milestone 6).

Fills the previously-empty ``src/workers/`` package. Every later
milestone that streams AI responses, reads large files, or generates
reports needs the UI thread free while that work runs — this package
is the one place that threading concern is solved, so nothing
downstream re-implements its own ``QThread``/``QRunnable`` plumbing.

See :mod:`src.workers.base_worker` for the actual ``BaseWorker`` /
``WorkerSignals`` pair.
"""

from __future__ import annotations

from src.workers.base_worker import BaseWorker, WorkerSignals

__all__ = ["BaseWorker", "WorkerSignals"]

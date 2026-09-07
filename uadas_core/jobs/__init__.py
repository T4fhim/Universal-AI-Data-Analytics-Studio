# File: uadas_core/jobs/__init__.py
"""Qt-free background-job execution — the headless replacement for ``QThreadPool``.

Web-transition Phase 1.2 lifts the *policy* of "run this callable off the
calling thread and deliver its outcome through callbacks" out of
:mod:`src.workers.base_worker` (which is welded to ``QThread``/``QRunnable``
and dies with the desktop shell in Phase 2) and into this package, where it
carries no GUI-toolkit dependency. The ``.importlinter`` contract forbids
anything under :mod:`uadas_core` — this package included — from importing
PySide6/PyQt/Django.

The subsystem is deliberately shaped like Phase 3's ``django.tasks``: a
:class:`~uadas_core.jobs.job_runner.JobRunner` protocol with an in-process
:class:`~uadas_core.jobs.thread_pool_executor_job_runner.ThreadPoolExecutorJobRunner`
implementation now, and room for a ``DjangoTasksJobRunner`` (running ``fn``
in another *process*, posting results back over HTTP) later without a
breaking change — which is why the contract is callback-based rather than
handing back an in-process ``Future``.

See ``plans/phase-1-2-jobrunner-design.md`` for the full design rationale
and the scope fence (no cancellation, job history, or telemetry in 1.2).
"""

from __future__ import annotations

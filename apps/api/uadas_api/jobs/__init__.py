# File: apps/api/uadas_api/jobs/__init__.py
"""Durable background jobs (Phase 3.5): a database row is the truth, Celery is the courier.

Why a package, and why it imports nothing: it is a Django app (it owns the ``Job`` table), and
Django loads app modules before the model registry is ready. Use the submodules:

* :mod:`uadas_api.jobs.models` -- :class:`Job`, a tenant-owned row holding the state machine,
  progress, result, sanitized error and heartbeat. It is also the cross-process **progress
  sink**: a worker writes it, the API (and 3.7's SSE stream) reads it.
* :mod:`uadas_api.jobs.services` -- create (idempotent, authorized, enqueue-after-commit),
  cancel, the conditional state transitions, the stale-job sweeper.
* :mod:`uadas_api.jobs.execution` -- :func:`execute_job`: claim, re-check ownership, run the
  kind's handler, commit success atomically, classify failures. Celery-free.
* :mod:`uadas_api.jobs.queue`, :mod:`uadas_api.jobs.celery_app`, :mod:`uadas_api.jobs.tasks` --
  the only modules that import Celery. Everything else calls :func:`queue.enqueue`.
* :mod:`uadas_api.jobs.progress`, :mod:`uadas_api.jobs.errors`, :mod:`uadas_api.jobs.choices`,
  :mod:`uadas_api.jobs.registry`.

The design is in ``plans/phase-3-5-jobs.md``.
"""

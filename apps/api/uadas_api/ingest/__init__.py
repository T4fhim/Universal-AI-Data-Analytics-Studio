# File: apps/api/uadas_api/ingest/__init__.py
"""Dataset ingest (Phase 3.5): a stored original upload becomes a ``DatasetRecord`` and a frame.

Why a package of its own and not part of ``workspaces``: ingest is the one place the API turns
untrusted bytes into structured data, so it is where the sandbox, the storage layer and the job
machinery meet, and it has to be read as one story. It is **not** a Django app (no models of its
own): the row it creates is :class:`~uadas_api.workspaces.models.DatasetRecord`, the state it
tracks is :class:`~uadas_api.jobs.models.Job`.

* :mod:`uadas_api.ingest.service` -- :func:`request_ingest` (create the job),
  :func:`validate_params`, and the job's handler (:data:`~uadas_api.ingest.service.HANDLER`).

There is deliberately no HTTP endpoint here (the upload endpoint is 3.6): this is "an already-
stored original object plus its declared file name", exactly what that endpoint will hand over.
"""

# File: apps/api/uadas_api/storage/__init__.py
"""Tenant-scoped object storage (Phase 3.4): the only code allowed to touch the bucket.

Deliberately imports nothing: this package is a Django app (it owns two tenant tables) and
Django loads app modules before the model registry is ready, so importing models or the
tenancy base here would fail. Use the submodules:

* :mod:`uadas_api.storage.store` -- :func:`get_store` and :class:`TenantObjectStore`, the
  facade every other module uses.
* :mod:`uadas_api.storage.keys` -- the one place object keys are built and validated.
* :mod:`uadas_api.storage.workspace` -- :class:`StorageBackedPersistence`, the Phase 2.7
  atomic-save property over object storage.
* :mod:`uadas_api.storage.lifecycle` -- row <-> object lifecycle (orphan queue, reconciliation).

``boto3``, ``botocore`` and ``django-storages`` are imported by :mod:`uadas_api.storage.s3`
only; a test (``tests/test_storage_boundary.py``) fails if anything else imports them.
"""

# File: apps/api/uadas_api/jobs/celery_app.py
"""The Celery application: configuration only, one of three modules that import Celery.

Start a worker with ``celery -A uadas_api.jobs.celery_app worker`` and the beat scheduler with
``celery -A uadas_api.jobs.celery_app beat`` (``DJANGO_SETTINGS_MODULE`` must be set; the worker
deliberately does not default to dev settings: a worker that forgot to choose should fail, like
``wsgi``). On Windows use ``--pool=solo`` (the prefork pool does not exist there; solo also
does not enforce Celery's time limits, which is one more reason production is Linux).

Everything configurable arrives through Django settings with the ``CELERY_`` prefix, built by
``settings/_jobs.py`` from one parsed mapping: JSON-only serialization, late acknowledgement with
reject-on-worker-lost, prefetch 1 (a long job must not sit behind another in a worker's local
buffer), soft and hard time limits, a broker visibility timeout longer than any task, no result
backend (job state is the database row). ``uadas_api.jobs.checks`` fails ``manage.py check`` if
any of that is overridden unsafely.

This module imports no model: Celery imports it before Django's app registry is ready in a
worker process, and the task bodies (``tasks.py``) import models lazily.
"""

from __future__ import annotations

from celery import Celery

app = Celery("uadas_api")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["uadas_api.jobs"])

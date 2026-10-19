# File: apps/api/uadas_api/web/idempotency.py
"""The optional ``Idempotency-Key`` request header of the create-with-a-job routes.

Why: a client that times out on an upload or a report request cannot know whether it arrived; with
a key it resends the same request and gets the same job (and dataset / report) back instead of a
second one. The key is validated by charset and length (at most 56 characters, so the stored job key
``report-<key>`` still fits the 64 of :data:`uadas_api.jobs.models.validate_idempotency_key`) and is
scoped by the job table's own uniqueness: ``(organization, kind, key)`` -- another organization's
identical key is a different request, and the same key reused for a different body or project is a
``409``, never a silent reuse.
"""

from __future__ import annotations

from typing import Annotated

from ninja import Header
from pydantic import StringConstraints

IdempotencyKeyValue = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,56}$")
]
# The parameter as a route declares it: the hyphenated header name is the wire (and OpenAPI) name.
IdempotencyKeyHeader = Annotated[
    IdempotencyKeyValue | None, Header(alias="Idempotency-Key")
]

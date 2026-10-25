# File: apps/api/uadas_api/storage/backend.py
"""The raw object-store contract that :class:`~uadas_api.storage.store.TenantObjectStore` wraps.

Why a protocol: the facade's guarantees (tenant prefix, caps, integrity, no overwrite) must
hold whatever stores the bytes, and the hermetic test suite needs a fake that behaves like
the real thing. :class:`~uadas_api.storage.s3.S3Backend` (boto3, via django-storages) and
:class:`~uadas_api.storage.memory.InMemoryBackend` implement it, and
``tests/test_storage_store.py`` runs the same facade tests against both.

**Backends are not tenant-aware and not for application code.** They take whole keys and do
exactly what they are told; the facade has already validated every key against the caller's
organization. A module that imports a backend directly has bypassed isolation, which is why
``tests/test_storage_boundary.py`` pins who may import this package.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class ObjectInfo:
    """What a store reports about one object.

    ``metadata`` is the user metadata exactly as stored (lower-case keys, ASCII values);
    a *listing* does not carry it (``content_type`` is then ``""`` and ``metadata`` empty),
    so anything that needs the hash calls ``head``.
    """

    key: str
    size: int
    etag: str
    last_modified: datetime
    content_type: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    encryption: str = ""


class ObjectBackend(Protocol):
    """Whole-key object operations. Failures surface as :mod:`uadas_api.storage.errors`."""

    def put(
        self,
        key: str,
        fileobj: BinaryIO,
        *,
        size: int,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        """Store ``size`` bytes read from the start of ``fileobj`` (replacing any object)."""
        ...

    def head(self, key: str) -> ObjectInfo | None:
        """Return the object's description, or ``None`` if there is no such object."""
        ...

    def download(self, key: str, fileobj: BinaryIO) -> None:
        """Write the object's bytes to ``fileobj`` (raises ``ObjectNotFoundError`` if absent)."""
        ...

    def delete_many(self, keys: Sequence[str]) -> list[str]:
        """Delete ``keys`` (an absent key is not a failure); return the keys that failed."""
        ...

    def list(self, prefix: str) -> Iterator[ObjectInfo]:
        """Yield every object whose key starts with ``prefix``, in key order."""
        ...

    def copy(self, source: str, destination: str) -> None:
        """Copy ``source`` to ``destination`` keeping content, type and user metadata."""
        ...

    def presign_get(
        self, key: str, *, expires_in: int, content_disposition: str | None = None
    ) -> str:
        """Return a time-limited GET URL for ``key``."""
        ...

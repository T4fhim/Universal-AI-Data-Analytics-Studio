# File: apps/api/uadas_api/storage/memory.py
"""An in-memory :class:`~uadas_api.storage.backend.ObjectBackend` for hermetic tests.

Why: the default API suite must run with no network and no credentials, so ``test`` settings
select this backend. It is a *faithful* fake, not a mock: bytes are copied in and out, a
``put`` replaces silently (like S3), a delete of a missing key succeeds, a listing is in key
order, a missing object is :class:`ObjectNotFoundError`. ``tests/test_storage_store.py``
runs the facade tests against it and, when ``STORAGE_INTEGRATION=1``, against real MinIO, so
the two are held to the same behaviour.

It is also shipped (not under ``tests/``) because ``settings/test.py`` names it; it is never
selected outside the ``test`` settings (``prod`` refuses any other backend than ``s3``).
Thread-safe: one lock around a dict.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import BinaryIO
from urllib.parse import quote

from uadas_api.storage.backend import ObjectInfo
from uadas_api.storage.errors import ObjectNotFoundError, StorageError


class InMemoryBackend:
    """A dict of objects behind a lock."""

    def __init__(self, *, server_side_encryption: str = "") -> None:
        self._lock = threading.Lock()
        self._objects: dict[str, tuple[bytes, ObjectInfo]] = {}
        self._encryption = server_side_encryption

    def put(
        self,
        key: str,
        fileobj: BinaryIO,
        *,
        size: int,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        fileobj.seek(0)
        data = fileobj.read()
        if len(data) != size:
            raise StorageError("declared size does not match the bytes supplied")
        info = ObjectInfo(
            key=key,
            size=size,
            etag=hashlib.md5(data, usedforsecurity=False).hexdigest(),
            last_modified=datetime.now(UTC),
            content_type=content_type,
            metadata={k.lower(): v for k, v in metadata.items()},
            encryption=self._encryption,
        )
        with self._lock:
            self._objects[key] = (data, info)

    def head(self, key: str) -> ObjectInfo | None:
        with self._lock:
            entry = self._objects.get(key)
        return entry[1] if entry else None

    def download(self, key: str, fileobj: BinaryIO) -> None:
        with self._lock:
            entry = self._objects.get(key)
        if entry is None:
            raise ObjectNotFoundError("no such object")
        fileobj.write(entry[0])

    def delete_many(self, keys: Sequence[str]) -> list[str]:
        with self._lock:
            for key in keys:
                self._objects.pop(key, None)
        return []

    def list(self, prefix: str) -> Iterator[ObjectInfo]:
        with self._lock:
            snapshot = sorted(
                (
                    ObjectInfo(
                        key=key,
                        size=info.size,
                        etag=info.etag,
                        last_modified=info.last_modified,
                    )
                    for key, (_, info) in self._objects.items()
                    if key.startswith(prefix)
                ),
                key=lambda info: info.key,
            )
        return iter(snapshot)

    def copy(self, source: str, destination: str) -> None:
        with self._lock:
            entry = self._objects.get(source)
            if entry is None:
                raise ObjectNotFoundError("no such object")
            data, info = entry
            self._objects[destination] = (
                data,
                ObjectInfo(
                    key=destination,
                    size=info.size,
                    etag=info.etag,
                    last_modified=datetime.now(UTC),
                    content_type=info.content_type,
                    metadata=dict(info.metadata),
                    encryption=self._encryption,
                ),
            )

    def presign_get(
        self, key: str, *, expires_in: int, content_disposition: str | None = None
    ) -> str:
        query = f"expires_in={expires_in}"
        if content_disposition:
            query += (
                f"&response-content-disposition={quote(content_disposition, safe='')}"
            )
        return f"memory://uadas-test/{key}?{query}"

    # --- test conveniences (not part of the backend contract) -----------------------

    def keys(self) -> Sequence[str]:
        """Every stored key, sorted: for assertions about what a failed save left behind."""
        with self._lock:
            return sorted(self._objects)

    def set_last_modified(self, key: str, when: datetime) -> None:
        """Pretend ``key`` was written at ``when`` (tests: age an object without waiting)."""
        with self._lock:
            data, info = self._objects[key]
            self._objects[key] = (data, replace(info, last_modified=when))

    def clear(self) -> None:
        with self._lock:
            self._objects.clear()

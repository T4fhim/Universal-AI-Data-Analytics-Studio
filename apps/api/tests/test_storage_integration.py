# File: apps/api/tests/test_storage_integration.py
"""Properties that only a real S3-compatible store can show (3.4); opt in with STORAGE_INTEGRATION=1.

Why: the hermetic suite proves the facade against a faithful fake and the request shapes
against a spy. What neither can prove is how a *real* store behaves: that a presigned URL
works and then stops working, that an anonymous request is refused (the bucket is not
public), that the store itself rejects an upload that does not match its SHA-256, and that a
multipart upload round-trips with its hash intact. ``test_storage_store.py`` and
``test_storage_workspace.py`` already run in full against the same store when this is on.

Skipped unless ``STORAGE_INTEGRATION=1`` and ``STORAGE_ENDPOINT_URL``, ``STORAGE_BUCKET``,
``STORAGE_ACCESS_KEY_ID`` and ``STORAGE_SECRET_ACCESS_KEY`` are exported (the docker-compose
MinIO values locally; CI starts a MinIO container). Every test writes under its own random
organization id and deletes exactly that namespace afterwards.
"""

from __future__ import annotations

import hashlib
import io
import os
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator

import pytest
from storage_support import integration_enabled, minio_backend

from uadas_api.storage.backend import ObjectBackend
from uadas_api.storage.errors import StorageUnavailableError
from uadas_api.storage.store import TenantObjectStore

pytestmark = pytest.mark.skipif(
    not integration_enabled(),
    reason="set STORAGE_INTEGRATION=1 and the STORAGE_* variables",
)

BIN = {"application/octet-stream"}  # the content types these tests store


@pytest.fixture
def backend() -> ObjectBackend:
    return minio_backend()


@pytest.fixture
def store(backend: ObjectBackend) -> Iterator[TenantObjectStore]:
    handle = TenantObjectStore(uuid.uuid4(), backend, presign_seconds=60)
    yield handle
    handle.delete_prefix(f"{handle.organization_id}/", allow_org_root=True)


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=10) as response:  # nosec B310
        data: bytes = response.read()
        return data


def _put(store: TenantObjectStore, key: str, data: bytes) -> None:
    store.put(
        key, data, content_type="application/octet-stream", allowed_content_types=BIN
    )


def test_a_presigned_url_downloads_the_object_and_nothing_else(
    store: TenantObjectStore,
) -> None:
    key = f"{store.organization_id}/exports/a.bin"
    _put(store, key, b"signed content")
    other = f"{store.organization_id}/exports/b.bin"
    _put(store, other, b"other content")

    url = store.presigned_get(key, download_filename="Quarterly report.csv")

    assert _fetch(url) == b"signed content"
    # The signature covers the key: pointing it at another object is refused.
    forged = url.replace("exports/a.bin", "exports/b.bin")
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _fetch(forged)
    assert excinfo.value.code == 403


def test_a_presigned_url_stops_working_after_its_lifetime(
    store: TenantObjectStore,
) -> None:
    key = f"{store.organization_id}/exports/short.bin"
    _put(store, key, b"short lived")
    # A few seconds, not one: the first fetch must land inside the window even on a loaded
    # machine, or the test would fail for the wrong reason (it did, once, in a full run).
    url = store.presigned_get(key, expires_in=4)
    assert _fetch(url) == b"short lived"
    time.sleep(6)
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _fetch(url)
    assert excinfo.value.code == 403


def test_the_download_name_reaches_the_response_header_sanitised(
    store: TenantObjectStore,
) -> None:
    key = f"{store.organization_id}/exports/named.bin"
    _put(store, key, b"x")
    url = store.presigned_get(key, download_filename='../../evil"\r\nX-Injected: 1.csv')
    with urllib.request.urlopen(url, timeout=10) as response:  # nosec B310
        disposition = response.headers["Content-Disposition"]
        assert response.headers.get("X-Injected") is None
    assert disposition.startswith("attachment;") and "evil" in disposition
    assert "\r" not in disposition and "\n" not in disposition


def test_an_unsigned_request_for_an_object_is_refused(store: TenantObjectStore) -> None:
    """The bucket is not public: no signature, no object."""
    key = f"{store.organization_id}/exports/private.bin"
    _put(store, key, b"private")
    endpoint = os.environ["STORAGE_ENDPOINT_URL"].rstrip("/")
    bucket = os.environ["STORAGE_BUCKET"]
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _fetch(f"{endpoint}/{bucket}/{key}")
    assert excinfo.value.code in {401, 403}


def test_the_store_itself_rejects_an_upload_that_does_not_match_its_sha256(
    backend: ObjectBackend, store: TenantObjectStore
) -> None:
    key = f"{store.organization_id}/objects/mismatch.bin"
    with pytest.raises(StorageUnavailableError):
        backend.put(
            key,
            io.BytesIO(b"these bytes"),
            size=11,
            content_type="application/octet-stream",
            metadata={"sha256": hashlib.sha256(b"different bytes").hexdigest()},
        )
    assert store.exists(key) is False  # nothing was stored


def test_a_multipart_sized_object_round_trips_with_its_hash(
    store: TenantObjectStore,
) -> None:
    payload = (
        os.urandom(1024 * 1024) * 66
    )  # 66 MiB: above the 64 MiB multipart threshold
    key = f"{store.organization_id}/objects/big.bin"
    stored = store.put(
        key,
        io.BytesIO(payload),
        content_type="application/octet-stream",
        allowed_content_types=BIN,
    )
    assert stored.size == len(payload)
    assert hashlib.sha256(store.get(key)).hexdigest() == stored.sha256
    store.delete(key)


@pytest.mark.skipif(
    not os.environ.get("STORAGE_TEST_SSE"),
    reason="needs a store with server-side encryption (MinIO needs a KMS); set STORAGE_TEST_SSE=1",
)
def test_sse_s3_is_applied_when_configured(store: TenantObjectStore) -> None:
    key = f"{store.organization_id}/objects/encrypted.bin"
    _put(store, key, b"encrypted at rest")
    info = store._backend.head(key)
    assert info is not None and info.encryption == "AES256"

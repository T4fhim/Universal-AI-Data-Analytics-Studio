# File: apps/api/uadas_api/storage/store.py
"""``TenantObjectStore``: the only way application code touches object storage.

Why a facade rather than ``default_storage`` or a boto3 client in each module: tenant
isolation in a shared bucket is only as strong as its weakest caller. Here every operation
is bound to one organization and re-validates *every* key it is given through
:func:`uadas_api.storage.keys.check_key` (``tenancy.validate_storage_key`` plus length
limits) **before** any request is made, so a key for organization A can never be read,
written, deleted, listed, copied or presigned through organization B's handle -- whether it
came from a view, a manifest or a database row somebody edited.

Guarantees, beyond isolation:

* **Integrity.** ``put`` records the SHA-256 of the bytes in object metadata and returns it;
  ``get`` / ``open`` / ``download_to`` verify it by default (and an object with *no* recorded
  hash is refused, not trusted). A caller that holds an independent hash (a manifest) passes
  ``expected_sha256``.
* **Caps.** A deployment-wide ``max_object_bytes`` that no call can raise; a stream is
  abandoned as soon as it exceeds the cap rather than read to the end.
* **Allow-listed content types.** The caller must name the types it will accept; an empty
  list refuses everything. A content type is a plain ``type/subtype`` (no parameters stored,
  no header injection).
* **Create-only by default.** ``put`` and ``copy`` refuse to replace an existing object
  unless asked: the D4-on-object-storage design (``storage.workspace``) never overwrites a key
  a manifest references, and this makes breaking that rule a loud error.
* **User file names are metadata**, percent-encoded, never key segments.
* **Scoped deletes.** ``delete_prefix`` works on directory boundaries and refuses the
  organization root unless the caller says so.
* **Short-lived signed URLs**, never longer than the configured maximum.

What this does not do: it cannot stop a second tenant's *bucket-level* credentials (there is
one credential for the whole bucket; isolation is by key prefix, enforced here, not by
IAM), it does not scan content, and a ``put`` followed by a crash may leave an orphan
object (``storage.lifecycle`` reports and collects those).
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import unicodedata
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO
from urllib.parse import quote, unquote

from django.conf import settings

from uadas_api.storage import keys as _keys
from uadas_api.storage.backend import ObjectBackend, ObjectInfo
from uadas_api.storage.errors import (
    DisallowedContentTypeError,
    InvalidKeyError,
    ObjectExistsError,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectTooLargeError,
    StorageNotConfiguredError,
    StorageUnavailableError,
)
from uadas_api.tenancy import OrganizationRef

_logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024
_SPOOL_IN_MEMORY = 8 * 1024 * 1024
_DELETE_BATCH = 1000
_MAX_FILENAME_CHARS = 200
_MAX_ENCODED_FILENAME = 1024  # S3 allows ~2 KB of user metadata in total

_MEDIA_TYPE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}"
)
_METADATA_KEY = re.compile(r"[a-z0-9-]{1,32}")
_METADATA_VALUE = re.compile(r"[\x20-\x7e]{0,256}")
_RESERVED_METADATA = frozenset({"sha256", "original-filename"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


def sha256_hex(data: bytes) -> str:
    """SHA-256 of ``data`` as lowercase hex (the form stored and compared everywhere)."""
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class StoredObject:
    """What the facade returns about an object. ``sha256`` is ``None`` if none was recorded."""

    key: str
    size: int
    sha256: str | None
    content_type: str
    etag: str
    last_modified: datetime
    original_filename: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DeleteResult:
    """Outcome of :meth:`TenantObjectStore.delete_prefix`: how many went, which did not."""

    deleted: int
    failed: list[str]


def _stored(info: ObjectInfo) -> StoredObject:
    metadata = dict(info.metadata)
    filename = metadata.pop("original-filename", None)
    return StoredObject(
        key=info.key,
        size=info.size,
        sha256=metadata.pop("sha256", None),
        content_type=info.content_type,
        etag=info.etag,
        last_modified=info.last_modified,
        original_filename=unquote(filename) if filename is not None else None,
        metadata=metadata,
    )


def _normalise_content_type(content_type: str, allowed: Collection[str]) -> str:
    """Return the bare lowercase ``type/subtype`` of ``content_type`` if it is allow-listed."""
    if not isinstance(content_type, str):
        raise DisallowedContentTypeError("content type must be a string")
    bare = content_type.split(";", 1)[0].strip().lower()
    permitted = {a.split(";", 1)[0].strip().lower() for a in allowed}
    if not permitted:
        raise DisallowedContentTypeError("no content types are allowed by this call")
    if _MEDIA_TYPE.fullmatch(bare) is None or bare not in permitted:
        raise DisallowedContentTypeError("content type is not allowed here")
    return bare


def _clean_filename(name: str) -> str:
    """Reduce a user-supplied name to a bounded, printable last path component."""
    last = name.replace("\\", "/").rsplit("/", 1)[-1]
    printable = "".join(
        ch
        for ch in last
        if unicodedata.category(ch) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    ).strip()
    printable = printable[:_MAX_FILENAME_CHARS]
    while printable and len(quote(printable, safe="")) > _MAX_ENCODED_FILENAME:
        printable = printable[:-1]
    return printable or "file"


def _validate_metadata(metadata: Mapping[str, str] | None) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in (metadata or {}).items():
        if not isinstance(key, str) or not _METADATA_KEY.fullmatch(key):
            raise ValueError(
                "metadata keys must be 1-32 lowercase letters, digits or hyphens"
            )
        if key in _RESERVED_METADATA:
            raise ValueError(f"metadata key {key!r} is reserved")
        if not isinstance(value, str) or not _METADATA_VALUE.fullmatch(value):
            raise ValueError(
                "metadata values must be printable ASCII of at most 256 characters"
            )
        clean[key] = value
    return clean


def _content_disposition(filename: str) -> str:
    """An ``attachment`` header with an ASCII fallback and an RFC 5987 UTF-8 name."""
    name = _clean_filename(filename)
    fallback = re.sub(r"[^A-Za-z0-9._-]", "_", name) or "file"
    return (
        f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"
    )


def _spool(data: bytes | BinaryIO, cap: int) -> tuple[BinaryIO, int, str]:
    """Copy ``data`` into a seekable spool while counting and hashing; refuse past ``cap``.

    Reads at most ``cap + 1`` bytes: an endless or oversized stream is abandoned as soon as
    the cap is crossed. The caller closes the returned spool.
    """
    digest = hashlib.sha256()
    spool: Any = SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY)  # noqa: SIM115
    size = 0
    try:
        if isinstance(data, bytes | bytearray | memoryview):
            view = memoryview(data)
            if len(view) > cap:
                raise ObjectTooLargeError(f"object exceeds the {cap}-byte limit")
            digest.update(view)
            spool.write(view)
            size = len(view)
        else:
            while True:
                chunk = data.read(min(_CHUNK, cap + 1 - size))
                if not chunk:
                    break
                if not isinstance(chunk, bytes | bytearray):
                    raise TypeError("the stream must be opened in binary mode")
                size += len(chunk)
                if size > cap:
                    raise ObjectTooLargeError(f"object exceeds the {cap}-byte limit")
                digest.update(chunk)
                spool.write(chunk)
        spool.seek(0)
    except BaseException:
        spool.close()
        raise
    return spool, size, digest.hexdigest()


def _hash_stream(handle: BinaryIO) -> str:
    handle.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(_CHUNK), b""):
        digest.update(chunk)
    return digest.hexdigest()


class TenantObjectStore:
    """One organization's view of the bucket. Construct with :func:`get_store`."""

    def __init__(
        self,
        organization: OrganizationRef,
        backend: ObjectBackend,
        *,
        max_object_bytes: int | None = None,
        presign_seconds: int | None = None,
        required_encryption: str | None = None,
    ) -> None:
        self._organization_id = _keys.organization_id(organization)
        self._backend = backend
        defaults: Mapping[str, Any] = getattr(settings, "UADAS_STORAGE", {})
        deployment_cap = int(defaults.get("max_object_bytes", 1024**3))
        # A handle may lower the deployment-wide caps, never raise them.
        self._max_object_bytes = min(max_object_bytes or deployment_cap, deployment_cap)
        presign_cap = int(defaults.get("presign_seconds", 300))
        self._presign_seconds = min(presign_seconds or presign_cap, presign_cap)
        # The server-side encryption every write must come back with ("" = none required).
        self._required_encryption = (
            str(defaults.get("server_side_encryption", ""))
            if required_encryption is None
            else required_encryption
        )

    @property
    def organization_id(self) -> str:
        """The organization this handle is bound to (canonical lowercase UUID)."""
        return self._organization_id

    @property
    def max_object_bytes(self) -> int:
        """The largest object this handle will store or fetch."""
        return self._max_object_bytes

    # --- helpers --------------------------------------------------------------------

    def _key(self, key: str) -> str:
        return _keys.check_key(self._organization_id, key)

    def _check_encryption(self, key: str) -> None:
        """Confirm a fresh write carries the required server-side encryption, where reported.

        Asking for SSE does not prove a store applied it. When encryption is required and the
        backend *reports* what it applied (S3 does; MinIO without a KMS says nothing) a
        different answer means the object is stored with weaker protection than promised: it
        is removed and the write fails. One extra ``HEAD``, only when encryption is required.
        """
        if not self._required_encryption:
            return
        info = self._backend.head(key)
        if (
            info is not None
            and info.encryption
            and info.encryption != self._required_encryption
        ):
            self._backend.delete_many([key])
            raise ObjectIntegrityError(
                "the store did not apply the required encryption"
            )

    def _cap(self, max_bytes: int | None) -> int:
        if max_bytes is None:
            return self._max_object_bytes
        return min(max_bytes, self._max_object_bytes)

    # --- writes ---------------------------------------------------------------------

    def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str,
        allowed_content_types: Collection[str],
        max_bytes: int | None = None,
        metadata: Mapping[str, str] | None = None,
        original_filename: str | None = None,
        overwrite: bool = False,
    ) -> StoredObject:
        """Store ``data`` under ``key`` and return its description (including the SHA-256).

        ``allowed_content_types`` is mandatory and fail-closed; ``max_bytes`` can only lower
        the deployment cap. ``original_filename`` becomes metadata (sanitised, percent-
        encoded), never part of the key. Without ``overwrite`` an existing object is an
        :class:`ObjectExistsError` (a check-then-write, so a defence against bugs, not a
        lock: the key layouts are unique by construction).
        """
        key = self._key(key)
        normalised_type = _normalise_content_type(content_type, allowed_content_types)
        user_metadata = _validate_metadata(metadata)
        spool, size, digest = _spool(data, self._cap(max_bytes))
        try:
            if not overwrite and self._backend.head(key) is not None:
                raise ObjectExistsError("an object already exists under this key")
            stored_metadata = {**user_metadata, "sha256": digest}
            if original_filename is not None:
                stored_metadata["original-filename"] = quote(
                    _clean_filename(original_filename), safe=""
                )
            self._backend.put(
                key,
                spool,
                size=size,
                content_type=normalised_type,
                metadata=stored_metadata,
            )
            self._check_encryption(key)
        finally:
            spool.close()
        return _stored(
            ObjectInfo(
                key=key,
                size=size,
                etag="",
                last_modified=datetime.now().astimezone(),
                content_type=normalised_type,
                metadata=stored_metadata,
            )
        )

    def copy(
        self, source: str, destination: str, *, overwrite: bool = False
    ) -> StoredObject:
        """Copy within this organization, keeping content, type, hash and file name."""
        source = self._key(source)
        destination = self._key(destination)
        if source == destination:
            raise InvalidKeyError("source and destination are the same key")
        if self._backend.head(source) is None:
            raise ObjectNotFoundError("no such object")
        if not overwrite and self._backend.head(destination) is not None:
            raise ObjectExistsError(
                "an object already exists under the destination key"
            )
        self._backend.copy(source, destination)
        copied = self._backend.head(destination)
        if copied is None:
            raise StorageUnavailableError("the copy did not produce an object")
        return _stored(copied)

    # --- reads ----------------------------------------------------------------------

    def head(self, key: str) -> StoredObject | None:
        """Describe the object, or ``None`` if there is none."""
        info = self._backend.head(self._key(key))
        return _stored(info) if info is not None else None

    def exists(self, key: str) -> bool:
        """Whether an object exists under ``key``."""
        return self._backend.head(self._key(key)) is not None

    def _fetch_into(
        self,
        key: str,
        handle: BinaryIO,
        *,
        verify: bool,
        expected_sha256: str | None,
        max_bytes: int | None,
    ) -> StoredObject:
        key = self._key(key)
        if expected_sha256 is not None and _SHA256.fullmatch(expected_sha256) is None:
            raise ValueError("expected_sha256 must be 64 lowercase hex characters")
        if expected_sha256 is not None and not verify:
            # An expected hash that is then not checked would read as a guarantee it is not.
            raise ValueError("expected_sha256 requires verify=True")
        info = self._backend.head(key)
        if info is None:
            raise ObjectNotFoundError("no such object")
        cap = self._cap(max_bytes)
        if info.size > cap:
            raise ObjectTooLargeError("object exceeds the allowed size")
        self._backend.download(key, handle)
        # `head` and `download` are separate requests, so the object could have been replaced
        # (or grown) between them: check what actually arrived, not what was announced.
        handle.seek(0, 2)
        if handle.tell() > cap:
            raise ObjectTooLargeError("object exceeds the allowed size")
        stored = _stored(info)
        if verify:
            expected = expected_sha256 or stored.sha256
            if expected is None:
                raise ObjectIntegrityError(
                    "the object has no recorded SHA-256 to verify"
                )
            if (
                expected_sha256 is not None
                and stored.sha256 is not None
                and stored.sha256 != expected_sha256
            ):
                raise ObjectIntegrityError(
                    "the stored hash differs from the expected one"
                )
            if _hash_stream(handle) != expected:
                raise ObjectIntegrityError(
                    "the object's bytes do not match their SHA-256"
                )
        handle.seek(0)
        return stored

    def open(
        self,
        key: str,
        *,
        verify: bool = True,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> BinaryIO:
        """Return a verified, seekable binary stream of the object. The caller closes it."""
        spool: Any = SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY)  # noqa: SIM115
        try:
            self._fetch_into(
                key,
                spool,
                verify=verify,
                expected_sha256=expected_sha256,
                max_bytes=max_bytes,
            )
        except BaseException:
            spool.close()
            raise
        return spool

    def get(
        self,
        key: str,
        *,
        verify: bool = True,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> bytes:
        """Return the object's bytes, verified against its recorded (or expected) SHA-256."""
        with self.open(
            key, verify=verify, expected_sha256=expected_sha256, max_bytes=max_bytes
        ) as handle:
            return handle.read()

    def download_to(
        self,
        key: str,
        path: Path,
        *,
        verify: bool = True,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> StoredObject:
        """Download straight into ``path``; a file that fails verification is removed."""
        try:
            with path.open("wb+") as handle:
                return self._fetch_into(
                    key,
                    handle,
                    verify=verify,
                    expected_sha256=expected_sha256,
                    max_bytes=max_bytes,
                )
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        """Yield the objects under a directory of this organization, in key order."""
        normalised = _keys.check_prefix(self._organization_id, prefix)
        for info in self._backend.list(normalised):
            if not info.key.startswith(
                normalised
            ):  # a misbehaving backend must not leak
                _logger.error("backend returned a key outside the requested prefix")
                continue
            yield _stored(info)

    def presigned_get(
        self,
        key: str,
        *,
        expires_in: int | None = None,
        download_filename: str | None = None,
    ) -> str:
        """Return a GET URL that stops working after ``expires_in`` seconds.

        Defaults to, and may not exceed, the configured ``presign_seconds`` (15 minutes at
        most). ``download_filename`` only shapes the ``Content-Disposition`` the store
        answers with; it is sanitised and never reaches the key. The URL is issued without
        checking the object exists.
        """
        key = self._key(key)
        seconds = self._presign_seconds if expires_in is None else expires_in
        if not 1 <= seconds <= self._presign_seconds:
            raise ValueError(
                f"expires_in must be between 1 and {self._presign_seconds} seconds"
            )
        disposition = (
            _content_disposition(download_filename)
            if download_filename is not None
            else None
        )
        return self._backend.presign_get(
            key, expires_in=seconds, content_disposition=disposition
        )

    # --- deletes --------------------------------------------------------------------

    def delete(self, key: str) -> None:
        """Delete one object. Deleting what is not there is not an error."""
        key = self._key(key)
        failed = self._backend.delete_many([key])
        if failed:
            raise StorageUnavailableError("the object could not be deleted")

    def delete_many(self, keys: Iterable[str]) -> DeleteResult:
        """Delete exactly ``keys`` (each validated first; one foreign key refuses the batch).

        Partial failure is reported, not raised. What :func:`lifecycle` uses when it has
        already decided *which* objects of a directory are owed.
        """
        checked = [self._key(key) for key in keys]
        failed: list[str] = []
        for start in range(0, len(checked), _DELETE_BATCH):
            failed.extend(
                self._backend.delete_many(checked[start : start + _DELETE_BATCH])
            )
        return DeleteResult(deleted=len(checked) - len(failed), failed=failed)

    def delete_prefix(
        self, prefix: str, *, allow_org_root: bool = False
    ) -> DeleteResult:
        """Delete every object under a directory of this organization.

        Refuses the organization root (``<org>/``) unless ``allow_org_root`` -- wiping a
        whole tenant is rare and deliberate. Partial failure is reported, not raised: the
        caller (``lifecycle``) queues the stragglers for retry.
        """
        normalised = _keys.check_prefix(self._organization_id, prefix)
        if (
            normalised == _keys.organization_prefix(self._organization_id)
            and not allow_org_root
        ):
            raise InvalidKeyError(
                "refusing to delete the organization root without allow_org_root=True"
            )
        deleted = 0
        failed: list[str] = []
        batch: list[str] = []

        def flush() -> None:
            nonlocal deleted
            if not batch:
                return
            not_deleted = self._backend.delete_many(list(batch))
            failed.extend(not_deleted)
            deleted += len(batch) - len(not_deleted)
            batch.clear()

        for info in self._backend.list(normalised):
            if not info.key.startswith(normalised):
                continue
            batch.append(info.key)
            if len(batch) >= _DELETE_BATCH:
                flush()
        flush()
        return DeleteResult(deleted=deleted, failed=failed)


# --- process-wide backend and the factory -----------------------------------------------

_backend_lock = threading.Lock()
_backend: ObjectBackend | None = None


def _build_backend() -> ObjectBackend:
    config: Mapping[str, Any] = settings.UADAS_STORAGE
    kind = config["backend"]
    if kind == "memory":
        from uadas_api.storage.memory import InMemoryBackend

        return InMemoryBackend(server_side_encryption=config["server_side_encryption"])
    if kind == "s3":
        from django.core.files.storage import storages

        from uadas_api.storage.s3 import S3Backend

        return S3Backend(
            storages["tenant_objects"],
            server_side_encryption=config["server_side_encryption"],
        )
    raise StorageNotConfiguredError(
        "object storage is not configured: set STORAGE_BUCKET, STORAGE_ACCESS_KEY_ID and "
        "STORAGE_SECRET_ACCESS_KEY"
    )


def _get_backend() -> ObjectBackend:
    global _backend
    backend = _backend
    if backend is not None:
        return backend
    with _backend_lock:
        if _backend is None:
            _backend = _build_backend()
        return _backend


def reset_backend() -> None:
    """Forget the cached backend (tests: a fresh in-memory store per test)."""
    global _backend
    with _backend_lock:
        _backend = None


@contextmanager
def override_backend(backend: ObjectBackend) -> Iterator[ObjectBackend]:
    """Use ``backend`` for every :func:`get_store` inside the block (tests only)."""
    global _backend
    with _backend_lock:
        previous, _backend = _backend, backend
    try:
        yield backend
    finally:
        with _backend_lock:
            _backend = previous


def get_store(organization: OrganizationRef) -> TenantObjectStore:
    """Return ``organization``'s handle on the configured store (the sanctioned entry point).

    Raises :class:`StorageNotConfiguredError` when no store is configured: unavailable
    storage fails closed rather than falling back to the local disk.
    """
    return TenantObjectStore(organization, _get_backend())

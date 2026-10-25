# File: apps/api/uadas_api/storage/errors.py
"""The storage layer's exceptions: one hierarchy, so callers can map each to a response.

Why a dedicated hierarchy instead of leaking ``botocore.exceptions.ClientError``: the rest of
the API must not import ``botocore`` (it would couple every view to one SDK), and the
distinction between "that key is not allowed", "that object is not there", "that object was
tampered with" and "the store is down" decides the HTTP status a later router returns
(400 / 404 / 502 / 503). Messages never include a key that belongs to another tenant: a
key is validated *before* any request is made, and the offending value is not echoed.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base class for every storage failure."""


class InvalidKeyError(StorageError, ValueError):
    """A key or prefix is malformed, over-long, or outside the organization's namespace."""


class StorageNotConfiguredError(StorageError):
    """No object store is configured (``UADAS_STORAGE['backend']`` is empty): fail closed."""


class ObjectNotFoundError(StorageError):
    """The key is valid but no object exists under it."""


class ObjectExistsError(StorageError):
    """A create-only write found an object already stored under the key."""


class ObjectTooLargeError(StorageError):
    """An object exceeds the size cap of the call or of the deployment."""


class DisallowedContentTypeError(StorageError):
    """A content type is not on the caller's allow-list (or is not a plain media type)."""


class ObjectIntegrityError(StorageError):
    """Stored bytes do not match their recorded SHA-256 (or none was recorded)."""


class StorageUnavailableError(StorageError):
    """The backend failed (network, credentials, throttling, a 5xx): not the caller's fault."""


class ManifestError(StorageError):
    """A stored workspace manifest is malformed or names objects it must not."""


class WorkspaceNotFoundError(ObjectNotFoundError):
    """A project has no saved workspace (no head row)."""


class ConcurrentSaveError(StorageError):
    """A save lost the compare-and-swap: someone else committed since this caller loaded."""

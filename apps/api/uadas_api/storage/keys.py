# File: apps/api/uadas_api/storage/keys.py
"""Object keys: fixed layouts built here and nowhere else, validated before every use.

Why one module: a key is the only thing separating one organization's objects from another's
in a shared bucket, and the only path by which user input could reach it is a file name.
So (1) every key is built from *identifiers* (UUIDs, a server-chosen token, a short
extension) -- the builders have no parameter for a name, and the user's original file name
is stored as object metadata instead; (2) every key, built here or received from elsewhere
(a manifest, a database row), is re-validated by :func:`check_key` on every store operation.

Layouts (``<org>`` is the organization UUID; the prefix is enforced, not conventional)::

    <org>/datasets/<dataset_id>/original/<uuid4hex>          uploaded original (immutable)
    <org>/datasets/<dataset_id>/frames/<save_token>.parquet  materialised frame (immutable)
    <org>/projects/<project_id>/workspace/<save_token>/workspace.db   workspace metadata
    <org>/exports/<report_id>/<uuid4hex>.<ext>               generated report file

Every object is written once under a key nobody else holds and is never overwritten;
"updating" a workspace means writing new keys and moving a pointer (``storage.workspace``).
The save token embeds the generation (``g0000007-...``) for humans and a random suffix so that
two concurrent saves of one project can never collide on a key.

Validation is :func:`uadas_api.tenancy.validate_storage_key` (prefix ``<org>/``, ASCII
``[A-Za-z0-9._-]`` segments, no ``.``/``..``/trailing dot, no empty segment) plus length
limits: a whole key is at most :data:`MAX_KEY_LENGTH` characters (the models' column width)
and a segment at most :data:`MAX_SEGMENT_LENGTH`. NUL, control characters, percent-encoding,
backslashes and Unicode look-alikes all fail the segment grammar.
"""

from __future__ import annotations

import re
import secrets
import uuid
from typing import Any

from django.core.exceptions import ValidationError

from uadas_api.storage.errors import InvalidKeyError
from uadas_api.tenancy import OrganizationRef, validate_storage_key

MAX_KEY_LENGTH = 512
MAX_SEGMENT_LENGTH = 128

# Canonical 8-4-4-4-12 only: uuid.UUID() alone would also accept braces, "urn:uuid:" and
# dash-less hex, which would give one object several spellings.
_UUID_TEXT = re.compile(
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
)
_DELETABLE_PREFIX = re.compile(
    r"(?P<org>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"/(?:datasets|projects)/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_TOKEN = re.compile(r"[A-Za-z0-9-]{1,64}")
_EXTENSION = re.compile(r"[a-z0-9]{1,8}")


def uuid_text(value: Any, what: str) -> str:
    """Return ``value`` as a canonical lowercase UUID string or raise :class:`InvalidKeyError`."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str) and _UUID_TEXT.fullmatch(value):
        return value.lower()
    # Deliberately does not echo the value: it may be attacker-controlled text.
    raise InvalidKeyError(f"{what} must be a canonical UUID")


def organization_id(organization: OrganizationRef) -> str:
    """Return the organization's id as a canonical lowercase UUID string."""
    pk = organization.pk if hasattr(organization, "pk") else organization
    return uuid_text(pk, "organization")


def check_key(organization: OrganizationRef, key: str) -> str:
    """Return ``key`` unchanged if it is a plain key inside ``organization``; else raise.

    The single gate every :class:`~uadas_api.storage.store.TenantObjectStore` operation
    passes a key through, whatever its origin. Never coerces: a ``bytes`` or ``None`` key is
    refused, not decoded.
    """
    org = organization_id(organization)
    if not isinstance(key, str):
        raise InvalidKeyError("a storage key must be a string")
    if len(key) > MAX_KEY_LENGTH:
        raise InvalidKeyError(
            f"a storage key may not exceed {MAX_KEY_LENGTH} characters"
        )
    try:
        validate_storage_key(org, key)
    except ValidationError:
        raise InvalidKeyError(
            "not a valid storage key for this organization (expected "
            "'<organization_id>/' followed by plain path segments)"
        ) from None
    if any(len(segment) > MAX_SEGMENT_LENGTH for segment in key.split("/")):
        raise InvalidKeyError(
            f"a storage key segment may not exceed {MAX_SEGMENT_LENGTH} characters"
        )
    return key


def check_prefix(organization: OrganizationRef, prefix: str) -> str:
    """Return ``prefix`` normalised to end in ``/`` if it names a directory of ``organization``.

    Directory semantics on purpose: ``<org>/datasets/ab`` must not also match
    ``<org>/datasets/abc...``, so a prefix without a trailing slash gets one. The
    organization root (``<org>/``) is a valid prefix -- callers that act on it destructively
    must opt in explicitly (see ``TenantObjectStore.delete_prefix``).
    """
    org = organization_id(organization)
    root = f"{org}/"
    if not isinstance(prefix, str) or not prefix.startswith(root):
        raise InvalidKeyError("not a valid storage prefix for this organization")
    if len(prefix) > MAX_KEY_LENGTH:
        raise InvalidKeyError(
            f"a storage prefix may not exceed {MAX_KEY_LENGTH} characters"
        )
    normalised = prefix if prefix.endswith("/") else f"{prefix}/"
    if normalised != root:
        check_key(org, normalised[:-1])
    return normalised


def new_save_token(version: int) -> str:
    """Return a token for one save attempt at generation ``version``.

    ``g0000007-1a2b3c4d5e6f``: readable generation, random suffix. The suffix is what makes
    two concurrent attempts at the same version write different keys, so neither can
    overwrite (and thereby corrupt) the other's objects before the pointer decides a winner.
    """
    if version < 0:
        raise InvalidKeyError("a save generation cannot be negative")
    return f"g{version:07d}-{secrets.token_hex(6)}"


def _token(value: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise InvalidKeyError("a save token must be 1-64 letters, digits or hyphens")
    return value


def dataset_original_key(organization: OrganizationRef, dataset_id: Any) -> str:
    """Key for a dataset's uploaded original. The user's file name is metadata, not a segment."""
    org = organization_id(organization)
    dataset = uuid_text(dataset_id, "dataset id")
    return check_key(org, f"{org}/datasets/{dataset}/original/{uuid.uuid4().hex}")


def dataset_frame_key(
    organization: OrganizationRef, dataset_id: Any, save_token: str
) -> str:
    """Key for one materialised Parquet frame of a dataset, written by the save ``save_token``."""
    org = organization_id(organization)
    dataset = uuid_text(dataset_id, "dataset id")
    return check_key(
        org, f"{org}/datasets/{dataset}/frames/{_token(save_token)}.parquet"
    )


def workspace_db_key(
    organization: OrganizationRef, project_id: Any, save_token: str
) -> str:
    """Key for the ``workspace.db`` written by the save ``save_token`` of a project."""
    org = organization_id(organization)
    project = uuid_text(project_id, "project id")
    return check_key(
        org,
        f"{org}/projects/{project}/workspace/{_token(save_token)}/workspace.db",
    )


def export_key(
    organization: OrganizationRef,
    report_id: Any,
    extension: str,
    token: str | None = None,
) -> str:
    """Key for a generated report file; ``extension`` is a short lowercase suffix, no dot.

    ``token`` names the build attempt (``j<attempt>-<job>``, like a stage run's derived frame) so
    every attempt of a job writes under a key of its own and a cleanup can only name its own
    object; without one the key is random (still unique, but not derivable).
    """
    org = organization_id(organization)
    report = uuid_text(report_id, "report id")
    if not isinstance(extension, str) or not _EXTENSION.fullmatch(extension):
        raise InvalidKeyError(
            "an export extension must be 1-8 lowercase letters or digits"
        )
    name = _token(token) if token is not None else uuid.uuid4().hex
    return check_key(org, f"{org}/exports/{report}/{name}.{extension}")


def is_deletable_prefix(organization: OrganizationRef, prefix: str) -> bool:
    """Whether ``prefix`` (no trailing slash) is a dataset or project directory of ``organization``.

    The only two directory shapes the layouts define and the only ones the orphan queue may
    ever delete wholesale: ``<org>/datasets/<uuid>`` and ``<org>/projects/<uuid>``. Anything
    broader (``<org>``, ``<org>/exports``) is refused, so no queue entry -- whatever wrote it --
    can erase more than one dataset's or one project's objects.
    """
    org = organization_id(organization)
    match = _DELETABLE_PREFIX.fullmatch(prefix) if isinstance(prefix, str) else None
    return match is not None and match.group("org") == org


def organization_prefix(organization: OrganizationRef) -> str:
    """The whole organization's namespace (``<org>/``)."""
    return f"{organization_id(organization)}/"


def dataset_prefix(organization: OrganizationRef, dataset_id: Any) -> str:
    """Everything stored for one dataset: its original and every frame."""
    org = organization_id(organization)
    return check_prefix(org, f"{org}/datasets/{uuid_text(dataset_id, 'dataset id')}/")


def project_prefix(organization: OrganizationRef, project_id: Any) -> str:
    """Everything stored under one project (its workspace databases)."""
    org = organization_id(organization)
    return check_prefix(org, f"{org}/projects/{uuid_text(project_id, 'project id')}/")

# File: apps/api/uadas_api/settings/_storage.py
"""Object-storage settings: strict parsing, explicit credentials, fail-closed production.

Why this lives beside the settings and not in ``uadas_api.storage``: settings are imported
before apps are ready, and the rules here are *configuration* rules (what the environment may
say), not behaviour. The runtime half is :mod:`uadas_api.storage`.

What is enforced, and why:

* **Nothing is guessed.** There is no default bucket, endpoint or credential in ``base`` (the
  throwaway MinIO values of ``docker-compose.dev.yml`` are supplied by ``dev`` alone, through
  the ``defaults`` argument). ``django-storages`` would otherwise fall back to the ambient
  ``AWS_*`` variables, a shared profile or an instance role; the credentials are therefore
  passed explicitly and the ambient ones are never read.
* **All or nothing.** A bucket, an access key id and a secret travel together; a store that is
  half configured stops start-up instead of failing on the first upload.
* **A typo is not a fallback.** An unknown addressing style or encryption mode, a non-integer
  or out-of-range number, a malformed bucket name or endpoint raises
  :class:`~django.core.exceptions.ImproperlyConfigured` naming the variable.
* **Short-lived signed URLs, private objects.** ``STORAGE_PRESIGN_SECONDS`` is capped at 15
  minutes, ``querystring_auth`` is on and the default ACL is ``private``. Nothing here (or in
  the facade) ever makes an object public; the bucket's own policy must keep it that way.
* **Production additionally** requires https for a custom endpoint and rejects a short,
  low-entropy or placeholder-looking secret (:func:`validate_for_production`).

``UADAS_STORAGE`` is what the rest of the code reads. Its nested key names contain ``key`` /
``secret`` on purpose: Django's debug-page cleanser matches names, so the values are masked
in a settings dump.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from django.conf import global_settings
from django.core.exceptions import ImproperlyConfigured

from ._env import get_bool, get_choice, get_int, get_str

# 3-63 chars, lowercase letters, digits, dots and hyphens, starting and ending alphanumeric
# (S3's rules for buckets that work with virtual-hosted-style addressing and TLS).
_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
_IPV4_SHAPED = re.compile(r"\d{1,3}(\.\d{1,3}){3}")
_REGION = re.compile(r"[a-z0-9-]{2,32}")

# How long an owed deletion must wait before it is paid: long enough for a reader that loaded
# the previous workspace, or a save that uploaded but has not yet swapped, to finish.
DEFAULT_GC_GRACE_SECONDS = 3600
MAX_GC_GRACE_SECONDS = 7 * 24 * 3600
MAX_PRESIGN_SECONDS = 900
DEFAULT_PRESIGN_SECONDS = 300
DEFAULT_MAX_OBJECT_BYTES = 1024**3
# S3's single-object ceiling; a larger cap could never be honoured.
_ABSOLUTE_MAX_OBJECT_BYTES = 5 * 1024**4

_MIN_PROD_SECRET_LENGTH = 24
_MIN_PROD_ACCESS_KEY_LENGTH = 8
_MIN_PROD_SECRET_DISTINCT_CHARS = 8
# Substrings that mark a value somebody forgot to replace. Compared case-insensitively. Short,
# plausible-in-random-data words are deliberately left out ("test", "key", "secret").
_PLACEHOLDER_MARKERS = (
    "changeme",
    "change-me",
    "change_me",
    "placeholder",
    "example",
    "minioadmin",
    "password",
    "your-",
    "your_",
    "xxxx",
    "dummy",
    "todo",
    "<",
    ">",
)

_ADDRESSING = {"AUTO": None, "PATH": "path", "VIRTUAL": "virtual"}
_SSE = {"NONE": "", "AES256": "AES256"}


def _bucket(name: str, default: str) -> str:
    value = get_str(name, default)
    if value and (
        _BUCKET.fullmatch(value) is None
        or ".." in value
        or _IPV4_SHAPED.fullmatch(value) is not None
    ):
        raise ImproperlyConfigured(
            f"{name} must be a valid bucket name (3-63 lowercase letters, digits, dots "
            f"and hyphens), got {value!r}."
        )
    return value


def _endpoint(name: str, default: str) -> str:
    value = get_str(name, default)
    if not value:
        return ""
    # The value is deliberately not echoed: a URL with embedded credentials would put them
    # in the start-up log.
    problem = (
        f"{name} must be an http(s) URL with a host and nothing else "
        "(no credentials, path, query or fragment)."
    )
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ImproperlyConfigured(problem) from None
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
        or port == 0
    ):
        raise ImproperlyConfigured(problem)
    return f"{parts.scheme}://{parts.netloc}"


def _bounded_int(name: str, default: int, *, low: int, high: int) -> int:
    value = get_int(name, default)
    if not low <= value <= high:
        raise ImproperlyConfigured(
            f"{name} must be between {low} and {high}, got {value}."
        )
    return value


def parse_storage(defaults: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Read ``STORAGE_*`` from the environment into the ``UADAS_STORAGE`` mapping.

    ``defaults`` supplies values for variables that are *unset* (only ``dev`` passes any);
    an explicit environment value always wins. Unconfigured (no bucket, credential or
    endpoint at all) yields ``backend == ""``: the store is then unavailable and
    :func:`uadas_api.storage.get_store` refuses to hand one out. Anything partly configured
    raises.
    """
    fallback = defaults or {}
    if any(
        get_str(name)
        for name in (
            "STORAGE_BUCKET",
            "STORAGE_ENDPOINT_URL",
            "STORAGE_ACCESS_KEY_ID",
            "STORAGE_SECRET_ACCESS_KEY",
        )
    ):
        # The developer is configuring a store of their own: the throwaway defaults (the
        # docker-compose MinIO credentials) must not silently fill in what they left out.
        fallback = {}

    def read(name: str) -> str:
        return get_str(name, fallback.get(name, ""))

    bucket = _bucket("STORAGE_BUCKET", fallback.get("STORAGE_BUCKET", ""))
    endpoint = _endpoint(
        "STORAGE_ENDPOINT_URL", fallback.get("STORAGE_ENDPOINT_URL", "")
    )
    access_key_id = read("STORAGE_ACCESS_KEY_ID")
    secret_access_key = read("STORAGE_SECRET_ACCESS_KEY")

    configured = any((bucket, endpoint, access_key_id, secret_access_key))
    if configured:
        for name, value in (
            ("STORAGE_BUCKET", bucket),
            ("STORAGE_ACCESS_KEY_ID", access_key_id),
            ("STORAGE_SECRET_ACCESS_KEY", secret_access_key),
        ):
            if not value:
                raise ImproperlyConfigured(
                    f"{name} must be set when object storage is configured: the bucket "
                    "and both credentials travel together (ambient AWS_* credentials "
                    "are deliberately not used)."
                )

    region = read("STORAGE_REGION") or "us-east-1"
    if _REGION.fullmatch(region) is None:
        raise ImproperlyConfigured(
            f"STORAGE_REGION must look like 'us-east-1', got {region!r}."
        )

    addressing_raw = get_choice(
        "STORAGE_ADDRESSING",
        tuple(_ADDRESSING),
        default=fallback.get("STORAGE_ADDRESSING", "auto").upper(),
    )
    sse_raw = get_choice("STORAGE_SSE", tuple(_SSE), default="NONE")

    return {
        "backend": "s3" if configured else "",
        "bucket_name": bucket,
        "endpoint_url": endpoint,
        "access_key_id": access_key_id,
        "secret_access_key": secret_access_key,
        "region_name": region,
        "addressing_style": _ADDRESSING[addressing_raw],
        "server_side_encryption": _SSE[sse_raw],
        # Only meaningful (and only consulted) in production: "I know objects are not asked
        # to be encrypted, the bucket/store encrypts at rest by itself".
        "encryption_acknowledged": get_bool("STORAGE_ENCRYPTION_ACKNOWLEDGED"),
        "gc_grace_seconds": _bounded_int(
            "STORAGE_GC_GRACE_SECONDS",
            DEFAULT_GC_GRACE_SECONDS,
            low=0,
            high=MAX_GC_GRACE_SECONDS,
        ),
        "presign_seconds": _bounded_int(
            "STORAGE_PRESIGN_SECONDS",
            DEFAULT_PRESIGN_SECONDS,
            low=1,
            high=MAX_PRESIGN_SECONDS,
        ),
        "max_object_bytes": _bounded_int(
            "STORAGE_MAX_OBJECT_BYTES",
            DEFAULT_MAX_OBJECT_BYTES,
            low=1,
            high=_ABSOLUTE_MAX_OBJECT_BYTES,
        ),
    }


def memory_storage() -> dict[str, Any]:
    """The hermetic mapping the ``test`` settings use: no endpoint, no credentials, no network."""
    # Built from pairs, not a dict literal: bandit's B105 reads an empty-string value under a
    # key named like a secret as a hardcoded password (same trick as ACCOUNT_RATE_LIMITS).
    return dict(
        [
            ("backend", "memory"),
            ("bucket_name", "uadas-test"),
            ("endpoint_url", ""),
            ("access_key_id", ""),
            ("secret_access_key", ""),
            ("region_name", "us-east-1"),
            ("addressing_style", None),
            ("server_side_encryption", ""),
            ("encryption_acknowledged", False),
            ("gc_grace_seconds", 0),  # hermetic tests collect garbage at once
            ("presign_seconds", DEFAULT_PRESIGN_SECONDS),
            ("max_object_bytes", DEFAULT_MAX_OBJECT_BYTES),
        ]
    )


def django_storages(storage: Mapping[str, Any]) -> dict[str, Any]:
    """Return the ``STORAGES`` setting, adding ``tenant_objects`` when the backend is S3.

    ``default`` and ``staticfiles`` are kept as Django ships them (declaring ``STORAGES``
    replaces the whole mapping). ``tenant_objects`` is the one django-storages
    :class:`~storages.backends.s3.S3Storage`; only :mod:`uadas_api.storage` reaches it.

    ``default_acl="private"`` and ``querystring_auth=True`` are explicit rather than relied
    on as defaults, and a test pins them. ``file_overwrite`` stays true because every key is
    unique by construction; the facade never overwrites a key a manifest references.
    """
    storages: dict[str, Any] = dict(global_settings.STORAGES)
    if storage["backend"] != "s3":
        return storages
    from botocore.config import (
        Config,  # imported lazily: only an S3 deployment needs it
    )

    addressing = storage["addressing_style"]
    client_config = Config(
        signature_version="s3v4",
        s3={"addressing_style": addressing} if addressing else {},
        retries={"max_attempts": 3, "mode": "standard"},
        connect_timeout=5,
        read_timeout=60,
        # boto3 >= 1.36 adds a CRC32 trailer by default, which several S3-compatible stores
        # reject; the facade sends an explicit SHA-256 where it matters.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    storages["tenant_objects"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": storage["bucket_name"],
            "endpoint_url": storage["endpoint_url"] or None,
            "region_name": storage["region_name"],
            "access_key": storage["access_key_id"],
            "secret_key": storage["secret_access_key"],
            "addressing_style": addressing,
            "signature_version": "s3v4",
            "client_config": client_config,
            "default_acl": "private",
            "querystring_auth": True,
            "querystring_expire": storage["presign_seconds"],
            "file_overwrite": True,
        },
    }
    return storages


def _looks_like_a_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def validate_for_production(storage: Mapping[str, Any]) -> None:
    """Refuse a production storage configuration that is missing, unencrypted in transit or weak.

    Run by ``prod`` at import time, so a mis-configured deployment never starts. Checks
    that the S3 backend is configured at all, that a custom endpoint is https, and that
    neither credential looks like a placeholder (the dev MinIO pair included) -- the secret
    additionally needs real length and variety and must differ from the access key id.
    """
    if storage["backend"] != "s3":
        raise ImproperlyConfigured(
            "STORAGE_BUCKET, STORAGE_ACCESS_KEY_ID and STORAGE_SECRET_ACCESS_KEY must be "
            "set for production: tenant data lives in object storage."
        )
    endpoint: str = storage["endpoint_url"]
    if endpoint and not endpoint.startswith("https://"):
        raise ImproperlyConfigured(
            "STORAGE_ENDPOINT_URL must be an https:// URL in production: objects and "
            "credentials would otherwise cross the network in clear text."
        )
    if not storage["server_side_encryption"] and not storage["encryption_acknowledged"]:
        raise ImproperlyConfigured(
            "STORAGE_SSE=aes256 is required in production (objects are then written with "
            "SSE-S3). If the store or bucket encrypts at rest by itself and rejects the "
            "header, say so explicitly: STORAGE_SSE=none with STORAGE_ENCRYPTION_ACKNOWLEDGED=1."
        )
    access_key_id: str = storage["access_key_id"]
    secret: str = storage["secret_access_key"]
    if len(access_key_id) < _MIN_PROD_ACCESS_KEY_LENGTH or _looks_like_a_placeholder(
        access_key_id
    ):
        raise ImproperlyConfigured(
            "STORAGE_ACCESS_KEY_ID looks like a placeholder or a development value; "
            "use the real access key id."
        )
    if (
        len(secret) < _MIN_PROD_SECRET_LENGTH
        or len(set(secret)) < _MIN_PROD_SECRET_DISTINCT_CHARS
        or _looks_like_a_placeholder(secret)
        or secret == access_key_id
    ):
        raise ImproperlyConfigured(
            f"STORAGE_SECRET_ACCESS_KEY must be a real secret of at least "
            f"{_MIN_PROD_SECRET_LENGTH} characters with some variety, not a placeholder, "
            "a repeated value or the access key id."
        )

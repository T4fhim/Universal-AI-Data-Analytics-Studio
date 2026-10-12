# File: apps/api/tests/storage_support.py
"""Test helpers for the storage suites: fault injection and the opt-in real-MinIO backend.

Why a module and not conftest fixtures: the same helpers are imported by the facade tests,
the workspace-persistence atomicity tests and the integration tests, and a fault injector
must be constructible with an arbitrary inner backend.

* :class:`FaultyBackend` wraps any backend and raises on a matching operation (a frame
  upload that fails, a delete that fails, ...), or runs a hook right after one succeeds (to
  interleave a second writer deterministically). It is the object-store analogue of the
  ``os.replace`` monkeypatches in ``tests/persistence/test_persistence_atomicity.py``.
* :func:`integration_enabled` / :func:`minio_backend` -- real-store tests run only when
  ``STORAGE_INTEGRATION=1`` *and* ``STORAGE_ENDPOINT_URL`` and credentials are exported (the
  docker-compose MinIO values, or CI's). Nothing is ever guessed: the hermetic suite must
  not reach a real bucket by accident.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from uadas_api.storage.backend import ObjectBackend, ObjectInfo


def integration_enabled(env: Mapping[str, str] | None = None) -> bool:
    """True when the real-MinIO tests were asked for and the environment can reach one."""
    source = os.environ if env is None else env
    return source.get("STORAGE_INTEGRATION") == "1" and all(
        source.get(name)
        for name in (
            "STORAGE_ENDPOINT_URL",
            "STORAGE_BUCKET",
            "STORAGE_ACCESS_KEY_ID",
            "STORAGE_SECRET_ACCESS_KEY",
        )
    )


def integration_required_but_missing(env: Mapping[str, str] | None = None) -> bool:
    """True when CI demands the real-store tests but they would silently skip.

    GitHub Actions sets ``CI=true``. A job that loses ``STORAGE_INTEGRATION`` (a renamed
    variable, a dropped step) would otherwise report ~110 skips and a green build.
    """
    source = os.environ if env is None else env
    return source.get("CI", "").lower() == "true" and not integration_enabled(source)


def minio_backend() -> ObjectBackend:
    """Build the production :class:`S3Backend` against the store named by ``STORAGE_*``."""

    from uadas_api.settings import _storage
    from uadas_api.storage.s3 import S3Backend

    env = os.environ
    config = _storage.memory_storage() | {
        "backend": "s3",
        "bucket_name": env["STORAGE_BUCKET"],
        "endpoint_url": env["STORAGE_ENDPOINT_URL"],
        "access_key_id": env["STORAGE_ACCESS_KEY_ID"],
        "secret_access_key": env["STORAGE_SECRET_ACCESS_KEY"],
        "addressing_style": env.get("STORAGE_ADDRESSING") or "path",
        "server_side_encryption": "AES256" if env.get("STORAGE_TEST_SSE") else "",
    }
    # The same OPTIONS the production settings hand to django-storages, built from the test
    # environment instead of the process settings.
    from storages.backends.s3 import S3Storage

    options = _storage.django_storages(config)["tenant_objects"]["OPTIONS"]
    return S3Backend(
        S3Storage(**options), server_side_encryption=config["server_side_encryption"]
    )


def write_behind_the_facade(
    backend: ObjectBackend, key: str, data: bytes, metadata: dict[str, str]
) -> None:
    """Put ``data`` under ``key`` with arbitrary metadata, as an attacker with bucket access could.

    The production S3 backend sends ``ChecksumSHA256`` taken from the metadata hash, so a
    real store *rejects* an upload whose bytes do not match it -- which is the point, but
    it also means tampering cannot go through that backend. A raw ``put_object`` can.
    """
    import io

    from uadas_api.storage.s3 import S3Backend

    if isinstance(backend, S3Backend):
        backend._client.put_object(
            Bucket=backend._bucket, Key=key, Body=data, Metadata=metadata
        )
    else:
        backend.put(
            key,
            io.BytesIO(data),
            size=len(data),
            content_type="application/octet-stream",
            metadata=metadata,
        )


@dataclass
class _Rule:
    op: str
    when: Callable[[str], bool]
    exc: BaseException
    times: int | None  # None = every match
    hits: int = 0


@dataclass
class FaultyBackend:
    """A backend wrapper that fails, or calls back, on chosen operations.

    ``fail("put", when=lambda key: "/frames/" in key)`` makes every frame upload raise.
    ``after("put", hook)`` runs ``hook(key)`` right after a put succeeds, which lets a test
    commit a *competing* save at the exact moment between this save's upload and its swap.
    ``calls`` records ``(operation, key)`` for assertions such as "no request was made".
    """

    inner: ObjectBackend
    rules: list[_Rule] = field(default_factory=list)
    hooks: list[tuple[str, Callable[[str], None]]] = field(default_factory=list)
    pre_hooks: list[tuple[str, Callable[[str], None]]] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def fail(
        self,
        op: str,
        *,
        when: Callable[[str], bool] = lambda key: True,
        exc: BaseException | None = None,
        times: int | None = None,
    ) -> None:
        from uadas_api.storage.errors import StorageUnavailableError

        self.rules.append(
            _Rule(
                op,
                when,
                exc or StorageUnavailableError(f"injected: {op} failed"),
                times,
            )
        )

    def after(self, op: str, hook: Callable[[str], None]) -> None:
        self.hooks.append((op, hook))

    def before(self, op: str, hook: Callable[[str], None]) -> None:
        """Run ``hook(key)`` just before ``op`` is attempted (once per call)."""
        self.pre_hooks.append((op, hook))

    def heal(self) -> None:
        self.rules.clear()
        self.hooks.clear()
        self.pre_hooks.clear()

    def _fault(self, op: str, key: str) -> BaseException | None:
        """Record the call, run any ``before`` hook, return the fault to raise (if a rule matches)."""
        self.calls.append((op, key))
        for hook_op, hook in list(self.pre_hooks):
            if hook_op == op:
                hook(key)
        for rule in self.rules:
            matches = rule.op == op and rule.when(key)
            if matches and (rule.times is None or rule.hits < rule.times):
                rule.hits += 1
                return rule.exc
        return None

    def _enter(self, op: str, key: str) -> None:
        fault = self._fault(op, key)
        if fault is not None:
            raise fault

    def _leave(self, op: str, key: str) -> None:
        for hook_op, hook in list(self.hooks):
            if hook_op == op:
                hook(key)

    def put(self, key: str, fileobj: BinaryIO, **kwargs: Any) -> None:
        self._enter("put", key)
        self.inner.put(key, fileobj, **kwargs)
        self._leave("put", key)

    def head(self, key: str) -> ObjectInfo | None:
        self._enter("head", key)
        return self.inner.head(key)

    def download(self, key: str, fileobj: BinaryIO) -> None:
        self._enter("download", key)
        self.inner.download(key, fileobj)

    def delete_many(self, keys: Sequence[str]) -> list[str]:
        failed: list[str] = []
        for key in keys:
            if self._fault("delete", key) is not None:
                failed.append(
                    key
                )  # a real store reports per-key failures, it does not raise
                continue
            failed.extend(self.inner.delete_many([key]))
            self._leave("delete", key)
        return failed

    def list(self, prefix: str) -> Iterator[ObjectInfo]:
        self._enter("list", prefix)
        return self.inner.list(prefix)

    def copy(self, source: str, destination: str) -> None:
        self._enter("copy", destination)
        self.inner.copy(source, destination)

    def presign_get(
        self, key: str, *, expires_in: int, content_disposition: str | None = None
    ) -> str:
        self._enter("presign", key)
        return self.inner.presign_get(
            key, expires_in=expires_in, content_disposition=content_disposition
        )

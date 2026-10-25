# File: apps/api/uadas_api/storage/s3.py
"""The S3-compatible :class:`~uadas_api.storage.backend.ObjectBackend` (MinIO, AWS S3, R2).

Why this is the *only* module that imports ``boto3`` / ``botocore`` / ``django-storages``:
the SDK's exceptions, retry behaviour and request shapes stay behind one seam, and
``tests/test_storage_boundary.py`` fails if another module imports them. The configured
django-storages :class:`~storages.backends.s3.S3Storage` (``STORAGES["tenant_objects"]``,
built from the ``STORAGE_*`` environment in ``settings/_storage.py``) supplies the boto3
client -- endpoint, region, explicit credentials, addressing style, SigV4, timeouts and
retries -- so there is one definition of how this app talks to the bucket.

Behaviour worth knowing:

* **No ACL is ever sent.** Objects are private by default; the bucket's own policy must
  keep it so (and many buckets reject ACL headers outright). Presigned URLs are the only
  way to hand an object to a browser.
* **SSE-S3** (``ServerSideEncryption: AES256``) is sent on writes and copies only when
  ``STORAGE_SSE=aes256`` -- AWS encrypts new objects with SSE-S3 by default; MinIO without
  a KMS rejects the header; R2 always encrypts.
* **Upload** uses the SDK's managed transfer (single request below 64 MiB, multipart above).
  A single request also sends ``ChecksumSHA256`` so the store itself rejects a corrupted
  upload; a multipart upload cannot carry a whole-object SHA-256, so only the metadata hash
  (verified on read by the facade) protects it.
* Every SDK failure becomes :class:`StorageUnavailableError` (or
  :class:`ObjectNotFoundError`); the response body, which can echo request details, is not
  propagated, only the error code is logged.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, BinaryIO

from boto3.exceptions import Boto3Error
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import BotoCoreError, ClientError
from storages.backends.s3 import S3Storage

from uadas_api.storage.backend import ObjectInfo
from uadas_api.storage.errors import ObjectNotFoundError, StorageUnavailableError

_logger = logging.getLogger(__name__)

_MULTIPART_THRESHOLD = 64 * 1024 * 1024
_MISSING = {"404", "NoSuchKey", "NotFound"}


def _code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


class S3Backend:
    """Object operations over a django-storages ``S3Storage``'s boto3 client."""

    def __init__(self, storage: S3Storage, *, server_side_encryption: str = "") -> None:
        self._storage = storage
        self._bucket: str = storage.bucket_name
        self._sse = server_side_encryption

    @property
    def _client(self) -> Any:
        # `connection` is a per-thread boto3 resource; its low-level client is thread-safe
        # to use from the thread that owns it.
        return self._storage.connection.meta.client

    def _fail(self, action: str, error: BaseException) -> StorageUnavailableError:
        code = _code(error) if isinstance(error, ClientError) else type(error).__name__
        _logger.warning("object store %s failed (%s)", action, code)
        return StorageUnavailableError(f"object store {action} failed ({code})")

    def _extra(self) -> dict[str, str]:
        return {"ServerSideEncryption": self._sse} if self._sse else {}

    def put(
        self,
        key: str,
        fileobj: BinaryIO,
        *,
        size: int,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> None:
        extra: dict[str, Any] = {
            "ContentType": content_type,
            "Metadata": dict(metadata),
            **self._extra(),
        }
        digest = metadata.get("sha256")
        if digest and size <= _MULTIPART_THRESHOLD:
            extra["ChecksumSHA256"] = base64.b64encode(bytes.fromhex(digest)).decode()
        fileobj.seek(0)
        try:
            self._client.upload_fileobj(
                fileobj,
                self._bucket,
                key,
                ExtraArgs=extra,
                Config=TransferConfig(multipart_threshold=_MULTIPART_THRESHOLD),
            )
        except (ClientError, BotoCoreError, Boto3Error) as error:
            raise self._fail("upload", error) from None

    def head(self, key: str) -> ObjectInfo | None:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if _code(error) in _MISSING:
                return None
            raise self._fail("head", error) from None
        except BotoCoreError as error:
            raise self._fail("head", error) from None
        return ObjectInfo(
            key=key,
            size=int(response["ContentLength"]),
            etag=str(response.get("ETag", "")).strip('"'),
            last_modified=response["LastModified"],
            content_type=str(response.get("ContentType", "")),
            metadata={k.lower(): v for k, v in response.get("Metadata", {}).items()},
            encryption=str(response.get("ServerSideEncryption", "")),
        )

    def download(self, key: str, fileobj: BinaryIO) -> None:
        try:
            self._client.download_fileobj(self._bucket, key, fileobj)
        except ClientError as error:
            if _code(error) in _MISSING:
                raise ObjectNotFoundError("no such object") from None
            raise self._fail("download", error) from None
        except (BotoCoreError, Boto3Error) as error:
            raise self._fail("download", error) from None

    def delete_many(self, keys: Sequence[str]) -> list[str]:
        failed: list[str] = []
        for start in range(0, len(keys), 1000):
            batch = list(keys[start : start + 1000])
            try:
                response = self._client.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
                )
            except (ClientError, BotoCoreError) as error:
                self._fail("delete", error)
                failed.extend(batch)
                continue
            failed.extend(str(item["Key"]) for item in response.get("Errors", []))
        return failed

    def list(self, prefix: str) -> Iterator[ObjectInfo]:
        paginator = self._client.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    yield ObjectInfo(
                        key=str(item["Key"]),
                        size=int(item["Size"]),
                        etag=str(item.get("ETag", "")).strip('"'),
                        last_modified=item["LastModified"],
                    )
        except (ClientError, BotoCoreError) as error:
            raise self._fail("list", error) from None

    def copy(self, source: str, destination: str) -> None:
        info = self.head(source)
        if info is None:
            raise ObjectNotFoundError("no such object")
        extra: dict[str, Any] = {
            "MetadataDirective": "REPLACE",
            "Metadata": dict(info.metadata),
            "ContentType": info.content_type,
            **self._extra(),
        }
        try:
            # The managed copy handles objects above the 5 GiB single-request limit.
            self._client.copy(
                {"Bucket": self._bucket, "Key": source},
                self._bucket,
                destination,
                ExtraArgs=extra,
            )
        except (ClientError, BotoCoreError, Boto3Error) as error:
            raise self._fail("copy", error) from None

    def presign_get(
        self, key: str, *, expires_in: int, content_disposition: str | None = None
    ) -> str:
        params: dict[str, str] = {"Bucket": self._bucket, "Key": key}
        if content_disposition:
            params["ResponseContentDisposition"] = content_disposition
        try:
            url = self._client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=expires_in
            )
        except (ClientError, BotoCoreError) as error:
            raise self._fail("presign", error) from None
        return str(url)

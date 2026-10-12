# File: apps/api/tests/test_storage_s3_backend.py
"""``S3Backend``'s requests, checked without a network (3.4).

Why: the production backend is exercised for real only when ``STORAGE_INTEGRATION=1``. These
tests cover, hermetically, the properties that must never silently change: the shape of each
request (encryption only when configured, never an ACL, the SHA-256 integrity header only where a
single request can carry it, metadata preserved on copy), and how SDK failures are mapped
(absent -> ``None`` / ``ObjectNotFoundError``, everything else -> ``StorageUnavailableError``
without leaking the response). A fake client records calls; no boto3 request is made.
"""

from __future__ import annotations

import base64
import hashlib
import io
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from uadas_api.storage.errors import ObjectNotFoundError, StorageUnavailableError
from uadas_api.storage.s3 import S3Backend

DIGEST = hashlib.sha256(b"payload").hexdigest()


def _backend(sse: str = "") -> tuple[S3Backend, MagicMock]:
    client = MagicMock()
    storage = SimpleNamespace(
        bucket_name="the-bucket",
        connection=SimpleNamespace(meta=SimpleNamespace(client=client)),
    )
    return S3Backend(storage, server_side_encryption=sse), client


def _client_error(code: str, operation: str = "HeadObject") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "secret details"}}, operation
    )


def _put(
    backend: S3Backend, size: int = 7, metadata: dict[str, str] | None = None
) -> None:
    backend.put(
        "org/k",
        io.BytesIO(b"payload"),
        size=size,
        content_type="application/octet-stream",
        metadata=metadata if metadata is not None else {"sha256": DIGEST},
    )


def test_put_sends_type_metadata_and_a_checksum_but_no_acl_and_no_encryption_by_default() -> (
    None
):
    backend, client = _backend()
    _put(backend)
    (_, bucket, key), kwargs = client.upload_fileobj.call_args
    extra = kwargs["ExtraArgs"]
    assert (bucket, key) == ("the-bucket", "org/k")
    assert extra["ContentType"] == "application/octet-stream"
    assert extra["Metadata"] == {"sha256": DIGEST}
    assert extra["ChecksumSHA256"] == base64.b64encode(bytes.fromhex(DIGEST)).decode()
    assert "ServerSideEncryption" not in extra
    assert "ACL" not in extra  # objects are private by default; no ACL is ever sent


def test_put_requests_sse_s3_only_when_configured() -> None:
    backend, client = _backend(sse="AES256")
    _put(backend)
    assert (
        client.upload_fileobj.call_args.kwargs["ExtraArgs"]["ServerSideEncryption"]
        == "AES256"
    )


def test_a_multipart_sized_upload_carries_no_whole_object_checksum() -> None:
    backend, client = _backend()
    _put(backend, size=65 * 1024 * 1024)
    assert "ChecksumSHA256" not in client.upload_fileobj.call_args.kwargs["ExtraArgs"]
    assert (
        client.upload_fileobj.call_args.kwargs["ExtraArgs"]["Metadata"]["sha256"]
        == DIGEST
    )


def test_an_upload_without_a_hash_sends_no_checksum_header() -> None:
    backend, client = _backend()
    _put(backend, metadata={})
    assert "ChecksumSHA256" not in client.upload_fileobj.call_args.kwargs["ExtraArgs"]


def test_head_maps_the_response_and_lowercases_user_metadata() -> None:
    backend, client = _backend()
    client.head_object.return_value = {
        "ContentLength": 7,
        "ETag": '"abc"',
        "LastModified": datetime(2026, 1, 1, tzinfo=UTC),
        "ContentType": "application/json",
        "Metadata": {"SHA256": DIGEST},
        "ServerSideEncryption": "AES256",
    }
    info = backend.head("org/k")
    assert info is not None
    assert (info.size, info.etag, info.content_type) == (7, "abc", "application/json")
    assert info.metadata == {"sha256": DIGEST}
    assert info.encryption == "AES256"


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_an_absent_object_is_none_on_head(code: str) -> None:
    backend, client = _backend()
    client.head_object.side_effect = _client_error(code)
    assert backend.head("org/k") is None


@pytest.mark.parametrize(
    "code", ["AccessDenied", "500", "SlowDown", "InvalidAccessKeyId"]
)
def test_any_other_failure_is_unavailable_and_does_not_leak_the_response(
    code: str,
) -> None:
    backend, client = _backend()
    client.head_object.side_effect = _client_error(code)
    with pytest.raises(StorageUnavailableError) as excinfo:
        backend.head("org/k")
    assert "secret details" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None  # `from None`: the SDK error is not chained


def test_a_network_failure_is_unavailable() -> None:
    backend, client = _backend()
    client.head_object.side_effect = EndpointConnectionError(endpoint_url="http://x")
    with pytest.raises(StorageUnavailableError):
        backend.head("org/k")


def test_download_maps_a_missing_object_and_other_failures_separately() -> None:
    backend, client = _backend()
    client.download_fileobj.side_effect = _client_error("404", "GetObject")
    with pytest.raises(ObjectNotFoundError):
        backend.download("org/k", io.BytesIO())
    client.download_fileobj.side_effect = _client_error("AccessDenied", "GetObject")
    with pytest.raises(StorageUnavailableError):
        backend.download("org/k", io.BytesIO())


def test_delete_many_batches_by_a_thousand_and_reports_per_key_errors() -> None:
    backend, client = _backend()
    client.delete_objects.side_effect = [
        {"Errors": [{"Key": "org/bad", "Code": "InternalError"}]},
        {},
    ]
    keys = [f"org/{i}" for i in range(1000)] + ["org/bad2"]
    failed = backend.delete_many(keys)
    assert failed == ["org/bad"]
    first, second = client.delete_objects.call_args_list
    assert len(first.kwargs["Delete"]["Objects"]) == 1000
    assert len(second.kwargs["Delete"]["Objects"]) == 1
    assert first.kwargs["Delete"]["Quiet"] is True


def test_a_failed_delete_request_marks_the_whole_batch_failed() -> None:
    backend, client = _backend()
    client.delete_objects.side_effect = _client_error("500", "DeleteObjects")
    assert backend.delete_many(["org/a", "org/b"]) == ["org/a", "org/b"]


def test_list_walks_every_page() -> None:
    backend, client = _backend()
    when = datetime(2026, 1, 1, tzinfo=UTC)
    client.get_paginator.return_value.paginate.return_value = [
        {
            "Contents": [
                {"Key": "org/a", "Size": 1, "ETag": '"1"', "LastModified": when}
            ]
        },
        {},
        {
            "Contents": [
                {"Key": "org/b", "Size": 2, "ETag": '"2"', "LastModified": when}
            ]
        },
    ]
    assert [(o.key, o.size) for o in backend.list("org/")] == [
        ("org/a", 1),
        ("org/b", 2),
    ]
    client.get_paginator.return_value.paginate.assert_called_once_with(
        Bucket="the-bucket", Prefix="org/"
    )


def test_copy_replaces_metadata_explicitly_so_a_multipart_copy_keeps_it() -> None:
    backend, client = _backend(sse="AES256")
    client.head_object.return_value = {
        "ContentLength": 7,
        "ETag": '"x"',
        "LastModified": datetime(2026, 1, 1, tzinfo=UTC),
        "ContentType": "application/json",
        "Metadata": {"sha256": DIGEST},
    }
    backend.copy("org/src", "org/dst")
    (source, bucket, destination), kwargs = client.copy.call_args
    assert source == {"Bucket": "the-bucket", "Key": "org/src"}
    assert (bucket, destination) == ("the-bucket", "org/dst")
    extra: dict[str, Any] = kwargs["ExtraArgs"]
    assert extra["MetadataDirective"] == "REPLACE"
    assert extra["Metadata"] == {"sha256": DIGEST}
    assert extra["ContentType"] == "application/json"
    assert extra["ServerSideEncryption"] == "AES256"
    assert "ACL" not in extra


def test_copy_of_a_missing_source_is_not_found() -> None:
    backend, client = _backend()
    client.head_object.side_effect = _client_error("404")
    with pytest.raises(ObjectNotFoundError):
        backend.copy("org/src", "org/dst")


def test_presign_asks_for_a_get_with_the_given_lifetime_and_disposition() -> None:
    backend, client = _backend()
    client.generate_presigned_url.return_value = "https://signed.example/url"
    url = backend.presign_get("org/k", expires_in=120, content_disposition="attachment")
    assert url == "https://signed.example/url"
    client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={
            "Bucket": "the-bucket",
            "Key": "org/k",
            "ResponseContentDisposition": "attachment",
        },
        ExpiresIn=120,
    )

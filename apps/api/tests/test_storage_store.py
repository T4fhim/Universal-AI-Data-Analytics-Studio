# File: apps/api/tests/test_storage_store.py
"""The tenant object-store facade (3.4): isolation, caps, integrity, scoped deletes.

Why: ``TenantObjectStore`` is the only way application code touches the bucket, so its
guarantees are the storage half of tenant isolation. Every test runs against the in-memory
backend; the same file also runs against a real MinIO when ``STORAGE_INTEGRATION=1`` (see
``storage_support``), so the fake is held to the behaviour of the real store rather than to
the author's idea of it.

No database is involved: the facade takes an organization id, and each test uses fresh
random organizations, which is also what makes the real-store variant safe to run in a shared
bucket (its keys live under those ids; teardown deletes only them).
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

import pytest
from storage_support import (
    FaultyBackend,
    integration_enabled,
    minio_backend,
    write_behind_the_facade,
)

from uadas_api.storage.backend import ObjectBackend
from uadas_api.storage.errors import (
    DisallowedContentTypeError,
    InvalidKeyError,
    ObjectExistsError,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectTooLargeError,
)
from uadas_api.storage.memory import InMemoryBackend
from uadas_api.storage.store import TenantObjectStore, sha256_hex

BIN = "application/octet-stream"
ALLOWED = {BIN, "application/json"}


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "minio",
            marks=pytest.mark.skipif(
                not integration_enabled(), reason="set STORAGE_INTEGRATION=1 for MinIO"
            ),
        ),
    ]
)
def backend(request: pytest.FixtureRequest) -> ObjectBackend:
    return InMemoryBackend() if request.param == "memory" else minio_backend()


@pytest.fixture
def make_store(backend: ObjectBackend) -> Iterator[Any]:
    """``make_store(org=None, **options)``; deletes everything the test wrote, at the end."""
    created: list[TenantObjectStore] = []

    def make(org: uuid.UUID | None = None, **options: Any) -> TenantObjectStore:
        store = TenantObjectStore(org or uuid.uuid4(), backend, **options)
        created.append(store)
        return store

    yield make
    for store in created:
        store.delete_prefix(f"{store.organization_id}/", allow_org_root=True)


def _key(store: TenantObjectStore, *parts: str) -> str:
    return "/".join((store.organization_id, *parts))


def _put(
    store: TenantObjectStore, key: str, data: bytes | BinaryIO = b"hello", **kw: Any
) -> Any:
    kw.setdefault("content_type", BIN)
    kw.setdefault("allowed_content_types", ALLOWED)
    return store.put(key, data, **kw)


# --- round trip and integrity -------------------------------------------------------


def test_put_then_get_round_trips_and_returns_the_sha256(make_store: Any) -> None:
    store = make_store()
    key = _key(store, "datasets", "a")
    stored = _put(store, key, b"some bytes")
    assert stored.key == key
    assert stored.size == 10
    assert stored.sha256 == sha256_hex(b"some bytes")
    assert stored.content_type == BIN
    assert store.get(key) == b"some bytes"
    assert store.head(key).sha256 == stored.sha256


def test_a_stream_is_stored_like_bytes(make_store: Any) -> None:
    store = make_store()
    payload = b"x" * 3_000_000
    stored = _put(store, _key(store, "s"), io.BytesIO(payload))
    assert stored.size == len(payload)
    assert stored.sha256 == sha256_hex(payload)
    assert store.get(_key(store, "s")) == payload


def test_an_empty_object_is_allowed(make_store: Any) -> None:
    store = make_store()
    _put(store, _key(store, "empty"), b"")
    assert store.get(_key(store, "empty")) == b""


def test_a_tampered_object_fails_verification_and_verify_false_still_reads_it(
    make_store: Any, backend: ObjectBackend
) -> None:
    store = make_store()
    key = _key(store, "t")
    good = _put(store, key, b"original")
    # Overwrite behind the facade's back, keeping the recorded hash of the original.
    write_behind_the_facade(backend, key, b"tampered", {"sha256": good.sha256})
    with pytest.raises(ObjectIntegrityError):
        store.get(key)
    with pytest.raises(ObjectIntegrityError):
        store.open(key)
    assert store.get(key, verify=False) == b"tampered"


def test_an_untampered_object_verifies_against_an_expected_hash(
    make_store: Any,
) -> None:
    store = make_store()
    key = _key(store, "e")
    stored = _put(store, key, b"data")
    assert store.get(key, expected_sha256=stored.sha256) == b"data"
    with pytest.raises(ObjectIntegrityError):
        store.get(key, expected_sha256=sha256_hex(b"something else"))


def test_an_object_with_no_recorded_hash_is_refused_unless_a_hash_is_supplied(
    make_store: Any, backend: ObjectBackend
) -> None:
    store = make_store()
    key = _key(store, "nohash")
    backend.put(key, io.BytesIO(b"raw"), size=3, content_type=BIN, metadata={})
    with pytest.raises(ObjectIntegrityError):
        store.get(key)  # fail closed: nothing to verify against
    assert store.get(key, expected_sha256=sha256_hex(b"raw")) == b"raw"
    assert store.get(key, verify=False) == b"raw"


def test_an_expected_hash_is_not_silently_ignored_when_verification_is_off(
    make_store: Any,
) -> None:
    store = make_store()
    stored = _put(store, _key(store, "v"), b"data")
    with pytest.raises(ValueError, match="verify"):
        store.get(_key(store, "v"), verify=False, expected_sha256=stored.sha256)
    assert (
        store.get(_key(store, "v"), verify=False) == b"data"
    )  # twin: no hash supplied


def test_a_handle_cannot_be_built_with_a_cap_above_the_deployment_cap(
    backend: ObjectBackend,
) -> None:
    from django.conf import settings

    ceiling = settings.UADAS_STORAGE["max_object_bytes"]
    above = TenantObjectStore(uuid.uuid4(), backend, max_object_bytes=ceiling * 10)
    assert above.max_object_bytes == ceiling  # clamped to the deployment's own cap
    below = TenantObjectStore(uuid.uuid4(), backend, max_object_bytes=10)
    assert below.max_object_bytes == 10  # twin: a lower cap is honoured


def test_a_handle_cannot_be_built_with_a_presign_lifetime_above_the_deployment_cap(
    backend: ObjectBackend,
) -> None:
    from django.conf import settings

    ceiling = settings.UADAS_STORAGE["presign_seconds"]
    above = TenantObjectStore(uuid.uuid4(), backend, presign_seconds=ceiling * 100)
    key = f"{above.organization_id}/exports/x"
    with pytest.raises(ValueError, match="expires_in"):
        above.presigned_get(key, expires_in=ceiling + 1)
    assert above.presigned_get(
        key, expires_in=ceiling
    )  # twin: the cap itself is allowed
    below = TenantObjectStore(uuid.uuid4(), backend, presign_seconds=10)
    with pytest.raises(ValueError, match="expires_in"):
        below.presigned_get(f"{below.organization_id}/exports/x", expires_in=11)
    assert below.presigned_get(f"{below.organization_id}/exports/x", expires_in=10)


def test_a_write_is_refused_and_removed_when_the_store_reports_weaker_encryption() -> (
    None
):
    org = uuid.uuid4()
    weak = InMemoryBackend(server_side_encryption="aws:kms")
    store = TenantObjectStore(org, weak, required_encryption="AES256")
    key = f"{org}/datasets/x"
    with pytest.raises(ObjectIntegrityError, match="encrypt"):
        _put(store, key)
    assert weak.head(key) is None  # the unprotected object was removed


def test_a_write_passes_when_the_reported_encryption_matches_or_is_not_reported() -> (
    None
):
    org = uuid.uuid4()
    for reported in ("AES256", ""):  # matching; a store that does not say (e.g. MinIO)
        backend = InMemoryBackend(server_side_encryption=reported)
        store = TenantObjectStore(org, backend, required_encryption="AES256")
        _put(store, f"{org}/datasets/{reported or 'silent'}")
        assert store.exists(f"{org}/datasets/{reported or 'silent'}")
    # And with no encryption required at all, nothing is checked (no extra request is made).
    faulty = FaultyBackend(InMemoryBackend(server_side_encryption="aws:kms"))
    plain = TenantObjectStore(org, faulty, required_encryption="")
    _put(plain, f"{org}/datasets/plain")
    assert [op for op, _ in faulty.calls].count(
        "head"
    ) == 1  # only the create-only check


def test_delete_many_removes_exactly_the_given_keys_and_validates_each(
    make_store: Any, backend: ObjectBackend
) -> None:
    store = make_store()
    keep, drop_a, drop_b = (_key(store, "m", n) for n in ("keep", "a", "b"))
    for key in (keep, drop_a, drop_b):
        _put(store, key)
    result = store.delete_many([drop_a, drop_b])
    assert (result.deleted, result.failed) == (2, [])
    assert store.exists(keep) and not store.exists(drop_a) and not store.exists(drop_b)
    with pytest.raises(
        InvalidKeyError
    ):  # twin: one foreign key refuses the whole batch
        store.delete_many([keep, f"{uuid.uuid4()}/m/a"])
    assert store.exists(keep)


def test_download_to_writes_a_verified_file(make_store: Any, tmp_path: Path) -> None:
    store = make_store()
    key = _key(store, "d")
    stored = _put(store, key, b"on disk")
    target = tmp_path / "out.bin"
    result = store.download_to(key, target, expected_sha256=stored.sha256)
    assert target.read_bytes() == b"on disk"
    assert result.sha256 == stored.sha256


def test_download_to_removes_a_file_that_failed_verification(
    make_store: Any, backend: ObjectBackend, tmp_path: Path
) -> None:
    store = make_store()
    key = _key(store, "d2")
    good = _put(store, key, b"good")
    write_behind_the_facade(backend, key, b"evil", {"sha256": good.sha256})
    target = tmp_path / "out.bin"
    with pytest.raises(ObjectIntegrityError):
        store.download_to(key, target)
    assert not target.exists()


def test_open_returns_a_readable_binary_stream(make_store: Any) -> None:
    store = make_store()
    _put(store, _key(store, "o"), b"stream me")
    with store.open(_key(store, "o")) as handle:
        assert handle.read() == b"stream me"


# --- size caps ----------------------------------------------------------------------


def test_put_over_the_per_call_cap_is_refused_and_stores_nothing(
    make_store: Any,
) -> None:
    store = make_store()
    key = _key(store, "big")
    with pytest.raises(ObjectTooLargeError):
        _put(store, key, b"x" * 11, max_bytes=10)
    assert store.exists(key) is False


def test_put_exactly_at_the_cap_is_accepted(make_store: Any) -> None:
    store = make_store()
    _put(store, _key(store, "exact"), b"x" * 10, max_bytes=10)
    assert store.exists(_key(store, "exact"))


def test_a_stream_over_the_cap_is_abandoned_without_reading_it_all(
    make_store: Any,
) -> None:
    store = make_store()

    class Endless(io.RawIOBase):
        read_total = 0

        def readable(self) -> bool:
            return True

        def readinto(self, buffer: Any) -> int:
            Endless.read_total += len(buffer)
            buffer[:] = b"x" * len(buffer)
            return len(buffer)

    with pytest.raises(ObjectTooLargeError):
        _put(
            store, _key(store, "endless"), io.BufferedReader(Endless()), max_bytes=1000
        )
    assert Endless.read_total < 4 * 1024 * 1024  # stopped near the cap, not at infinity
    assert store.exists(_key(store, "endless")) is False


def test_the_deployment_cap_cannot_be_raised_by_a_caller(make_store: Any) -> None:
    store = make_store(max_object_bytes=10)
    with pytest.raises(ObjectTooLargeError):
        _put(store, _key(store, "deployment"), b"x" * 11, max_bytes=10_000)
    _put(store, _key(store, "deployment-ok"), b"x" * 10, max_bytes=10_000)


def test_get_over_the_cap_is_refused_before_downloading(
    make_store: Any, backend: ObjectBackend
) -> None:
    faulty = FaultyBackend(backend)
    store = TenantObjectStore(uuid.uuid4(), faulty)
    key = _key(store, "g")
    try:
        _put(store, key, b"x" * 20)
        with pytest.raises(ObjectTooLargeError):
            store.get(key, max_bytes=19)
        assert ("download", key) not in faulty.calls
        assert store.get(key, max_bytes=20) == b"x" * 20
    finally:
        store.delete_prefix(f"{store.organization_id}/", allow_org_root=True)


# --- content types and metadata -----------------------------------------------------


def test_a_content_type_outside_the_allow_list_is_refused(make_store: Any) -> None:
    store = make_store()
    with pytest.raises(DisallowedContentTypeError):
        _put(store, _key(store, "ct"), content_type="text/html")
    assert not store.exists(_key(store, "ct"))


def test_an_allowed_content_type_is_accepted_whatever_its_case_and_parameters(
    make_store: Any,
) -> None:
    store = make_store()
    stored = _put(
        store, _key(store, "ct"), content_type="Application/JSON; charset=utf-8"
    )
    assert stored.content_type == "application/json"


@pytest.mark.parametrize(
    "content_type",
    ["", "text", "a/b/c", "text/ht ml", "text/html\r\nX: y", "*/*", "é/é"],
)
def test_a_malformed_content_type_is_refused_even_if_listed(
    make_store: Any, content_type: str
) -> None:
    store = make_store()
    with pytest.raises(DisallowedContentTypeError):
        _put(
            store,
            _key(store, "bad-ct"),
            content_type=content_type,
            allowed_content_types={content_type},
        )


def test_an_empty_allow_list_fails_closed(make_store: Any) -> None:
    store = make_store()
    with pytest.raises(DisallowedContentTypeError):
        _put(store, _key(store, "none"), allowed_content_types=set())


def test_the_original_file_name_is_metadata_and_never_part_of_the_key(
    make_store: Any,
) -> None:
    store = make_store()
    key = _key(store, "datasets", "x", "original", "abc")
    stored = _put(store, key, original_filename="../../Quarterly report (final) é.csv")
    assert stored.original_filename == "Quarterly report (final) é.csv"
    assert "Quarterly" not in key
    assert store.head(key).original_filename == "Quarterly report (final) é.csv"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain.csv", "plain.csv"),
        ("C:\\Users\\me\\data.csv", "data.csv"),
        ("a/b/c.csv", "c.csv"),
        ("tab\tand\x00nul.csv", "tabandnul.csv"),
        ("x" * 500 + ".csv", ("x" * 500 + ".csv")[:200]),
    ],
)
def test_the_original_file_name_is_sanitised(
    make_store: Any, raw: str, expected: str
) -> None:
    store = make_store()
    stored = _put(store, _key(store, "n"), original_filename=raw)
    assert stored.original_filename == expected


def test_custom_metadata_round_trips_but_cannot_shadow_reserved_names(
    make_store: Any,
) -> None:
    store = make_store()
    stored = _put(store, _key(store, "m"), metadata={"dataset-kind": "frame"})
    assert stored.metadata["dataset-kind"] == "frame"
    for reserved in ("sha256", "original-filename"):
        with pytest.raises(ValueError, match="reserved"):
            _put(store, _key(store, "m2"), metadata={reserved: "x"})


@pytest.mark.parametrize(
    "metadata",
    [{"Bad Key": "v"}, {"k": "line\nbreak"}, {"k": "é"}, {"": "v"}, {"k" * 40: "v"}],
)
def test_malformed_metadata_is_refused(
    make_store: Any, metadata: dict[str, str]
) -> None:
    store = make_store()
    with pytest.raises(ValueError):
        _put(store, _key(store, "m3"), metadata=metadata)


# --- no overwrite -------------------------------------------------------------------


def test_put_refuses_to_overwrite_an_existing_object_by_default(
    make_store: Any,
) -> None:
    store = make_store()
    key = _key(store, "once")
    _put(store, key, b"first")
    with pytest.raises(ObjectExistsError):
        _put(store, key, b"second")
    assert store.get(key) == b"first"


def test_put_can_overwrite_when_asked_explicitly(make_store: Any) -> None:
    store = make_store()
    key = _key(store, "twice")
    _put(store, key, b"first")
    _put(store, key, b"second", overwrite=True)
    assert store.get(key) == b"second"


# --- tenant isolation ---------------------------------------------------------------


def test_one_organizations_handle_cannot_touch_another_organizations_key(
    make_store: Any, backend: ObjectBackend
) -> None:
    faulty = FaultyBackend(backend)
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    store_a = TenantObjectStore(org_a, faulty)
    store_b = TenantObjectStore(org_b, faulty)
    key_a = f"{org_a}/datasets/secret"
    own_b = f"{org_b}/datasets/mine"
    try:
        _put(store_a, key_a, b"tenant A data")
        faulty.calls.clear()
        attempts = {
            "get": lambda: store_b.get(key_a),
            "open": lambda: store_b.open(key_a),
            "head": lambda: store_b.head(key_a),
            "exists": lambda: store_b.exists(key_a),
            "delete": lambda: store_b.delete(key_a),
            "put": lambda: _put(store_b, key_a, b"overwrite", overwrite=True),
            "presign": lambda: store_b.presigned_get(key_a),
            "copy-out": lambda: store_b.copy(key_a, own_b),
            "copy-in": lambda: store_b.copy(own_b, key_a),
            "list": lambda: list(store_b.list_prefix(f"{org_a}/datasets/")),
            "delete_prefix": lambda: store_b.delete_prefix(f"{org_a}/datasets/"),
            "delete_org_root": lambda: store_b.delete_prefix(
                f"{org_a}/", allow_org_root=True
            ),
        }
        for name, attempt in attempts.items():
            with pytest.raises(InvalidKeyError):
                attempt()
            assert faulty.calls == [], f"{name} reached the backend"
        assert store_a.get(key_a) == b"tenant A data"  # untouched
    finally:
        for store in (store_a, store_b):
            store.delete_prefix(f"{store.organization_id}/", allow_org_root=True)


def test_each_handle_still_works_inside_its_own_namespace(make_store: Any) -> None:
    store_a, store_b = make_store(), make_store()
    _put(store_a, _key(store_a, "k"), b"a")
    _put(store_b, _key(store_b, "k"), b"b")
    assert store_a.get(_key(store_a, "k")) == b"a"
    assert store_b.get(_key(store_b, "k")) == b"b"
    assert [o.key for o in store_a.list_prefix(f"{store_a.organization_id}/")] == [
        _key(store_a, "k")
    ]


@pytest.mark.parametrize(
    "suffix",
    ["../x", "a/../b", "%2e%2e/x", "a\x00b", "a\\b", "\uff0e\uff0e/x", "x" * 600, ""],
)
def test_a_malformed_key_never_reaches_the_backend(
    backend: ObjectBackend, suffix: str
) -> None:
    faulty = FaultyBackend(backend)
    store = TenantObjectStore(uuid.uuid4(), faulty)
    key = f"{store.organization_id}/{suffix}"
    for operation in (
        lambda: store.get(key),
        lambda: store.head(key),
        lambda: store.exists(key),
        lambda: store.delete(key),
        lambda: _put(store, key),
        lambda: store.presigned_get(key),
    ):
        with pytest.raises(InvalidKeyError):
            operation()
    assert faulty.calls == []


def test_a_non_string_key_is_refused(make_store: Any) -> None:
    store = make_store()
    with pytest.raises(InvalidKeyError):
        store.get(None)


# --- missing objects, deletes, listing ----------------------------------------------


def test_missing_objects_report_absent_or_raise_not_found(make_store: Any) -> None:
    store = make_store()
    key = _key(store, "nope")
    assert store.exists(key) is False
    assert store.head(key) is None
    with pytest.raises(ObjectNotFoundError):
        store.get(key)
    with pytest.raises(ObjectNotFoundError):
        store.open(key)
    with pytest.raises(ObjectNotFoundError):
        store.copy(key, _key(store, "dest"))


def test_delete_removes_the_object_and_is_idempotent(make_store: Any) -> None:
    store = make_store()
    key = _key(store, "del")
    _put(store, key)
    store.delete(key)
    assert store.exists(key) is False
    store.delete(key)  # deleting what is not there is not an error


def test_delete_prefix_removes_exactly_the_directory(make_store: Any) -> None:
    store = make_store()
    inside = [_key(store, "datasets", "ab", f"o{i}") for i in range(3)]
    sibling = _key(
        store, "datasets", "abc", "o"
    )  # shares the *text* prefix, not the directory
    other = _key(store, "exports", "o")
    for key in (*inside, sibling, other):
        _put(store, key)
    result = store.delete_prefix(_key(store, "datasets", "ab"))
    assert result.deleted == 3
    assert result.failed == []
    assert [store.exists(k) for k in inside] == [False, False, False]
    assert store.exists(sibling) and store.exists(other)


def test_delete_prefix_pages_through_more_than_one_batch(make_store: Any) -> None:
    store = make_store()
    for i in range(1105):
        # Tiny objects; the point is the 1000-key delete batch limit.
        _put(store, _key(store, "many", f"{i:05d}"), b"")
    assert store.delete_prefix(_key(store, "many")).deleted == 1105
    assert list(store.list_prefix(_key(store, "many"))) == []


def test_delete_prefix_refuses_the_organization_root_unless_explicit(
    make_store: Any,
) -> None:
    store = make_store()
    key = _key(store, "keep")
    _put(store, key)
    root = f"{store.organization_id}/"
    with pytest.raises(InvalidKeyError, match="root"):
        store.delete_prefix(root)
    assert store.exists(key)
    assert store.delete_prefix(root, allow_org_root=True).deleted == 1
    assert not store.exists(key)


def test_delete_prefix_reports_what_it_could_not_delete(
    backend: ObjectBackend,
) -> None:
    faulty = FaultyBackend(backend)
    store = TenantObjectStore(uuid.uuid4(), faulty)
    good, stuck = _key(store, "p", "good"), _key(store, "p", "stuck")
    try:
        _put(store, good)
        _put(store, stuck)
        faulty.fail("delete", when=lambda key: key == stuck)
        result = store.delete_prefix(_key(store, "p"))
        assert result.deleted == 1
        assert result.failed == [stuck]
        faulty.heal()
        assert store.exists(stuck) and not store.exists(good)
    finally:
        faulty.heal()
        store.delete_prefix(f"{store.organization_id}/", allow_org_root=True)


def test_list_prefix_returns_only_that_directory_in_key_order(make_store: Any) -> None:
    store = make_store()
    for name in ("b/2", "a/1", "a/0", "ab/9"):
        _put(store, _key(store, name), b"xy")
    listed = list(store.list_prefix(_key(store, "a")))
    assert [o.key for o in listed] == [_key(store, "a/0"), _key(store, "a/1")]
    assert all(o.size == 2 for o in listed)


# --- presigned URLs -----------------------------------------------------------------


def test_a_presigned_url_defaults_to_the_short_configured_lifetime(
    make_store: Any,
) -> None:
    store = make_store(presign_seconds=120)
    key = _key(store, "u")
    _put(store, key)
    url = store.presigned_get(key)
    assert url.startswith(("http://", "https://", "memory://"))
    assert key in url


def test_a_presigned_url_cannot_outlive_the_configured_maximum(make_store: Any) -> None:
    store = make_store(presign_seconds=120)
    key = _key(store, "u2")
    _put(store, key)
    assert store.presigned_get(key, expires_in=1)
    assert store.presigned_get(key, expires_in=120)
    for bad in (0, -5, 121, 3600):
        with pytest.raises(ValueError, match="expires_in"):
            store.presigned_get(key, expires_in=bad)


def test_a_download_name_cannot_inject_headers_into_the_signed_url(
    make_store: Any,
) -> None:
    store = make_store()
    key = _key(store, "u3")
    _put(store, key)
    url = store.presigned_get(key, download_filename='a"b\r\nX-Evil: 1/../c.csv')
    assert "\r" not in url and "\n" not in url
    assert "X-Evil" not in url  # only the last path component of the name survives
    assert "attachment" in url.lower() and "c.csv" in url


# --- copy ---------------------------------------------------------------------------


def test_copy_within_the_tenant_keeps_content_hash_and_type(make_store: Any) -> None:
    store = make_store()
    src, dst = _key(store, "src"), _key(store, "dst")
    original = _put(store, src, b"payload", original_filename="up.csv")
    copied = store.copy(src, dst)
    assert store.get(dst) == b"payload"
    assert copied.sha256 == original.sha256
    assert copied.content_type == BIN
    assert copied.original_filename == "up.csv"
    assert store.exists(src)


def test_copy_refuses_to_overwrite_or_to_copy_onto_itself(make_store: Any) -> None:
    store = make_store()
    src, dst = _key(store, "src"), _key(store, "dst")
    _put(store, src, b"a")
    _put(store, dst, b"b")
    with pytest.raises(ObjectExistsError):
        store.copy(src, dst)
    with pytest.raises(InvalidKeyError):
        store.copy(src, src)
    assert store.get(dst) == b"b"
    assert store.copy(src, dst, overwrite=True).sha256 == sha256_hex(b"a")


# --- factory ------------------------------------------------------------------------


def test_the_store_handle_reports_the_canonical_organization_id() -> None:
    org = uuid.UUID("abcdef01-2345-4678-8abc-def012345678")
    store = TenantObjectStore(str(org).upper(), InMemoryBackend())
    assert store.organization_id == str(org)
    with pytest.raises(InvalidKeyError):
        TenantObjectStore("not-a-uuid", InMemoryBackend())

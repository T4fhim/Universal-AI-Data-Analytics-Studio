# File: apps/api/tests/test_storage_settings.py
"""Object-storage settings (3.4): strict parsing, fail-closed prod, hermetic test, dev-only defaults.

Why: the bucket is where every tenant's data lives, so its configuration is a security
boundary. These tests pin that (a) nothing is guessed -- credentials come only from the
environment and have no default outside ``dev`` (whose throwaway MinIO values must never
leak into ``base``/``prod``); (b) a typo stops start-up instead of silently weakening
something; (c) ``prod`` additionally refuses an http endpoint, a missing or placeholder
credential and anything that could make objects world-readable; (d) the ``test`` settings
are hermetic whatever ``STORAGE_*`` the developer's shell exports.

Every rejection has a positive twin (observation 0033): a guard test that only proves the
reject path can pass for the wrong reason.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured
from test_settings import PROD_ENV, STORAGE_ENV

Loader = Callable[..., ModuleType]


def _storage(module: ModuleType) -> dict[str, object]:
    value: dict[str, object] = module.UADAS_STORAGE
    return value


# --- base: nothing guessed ---------------------------------------------------------


def test_base_without_storage_variables_is_unconfigured_and_has_no_secrets(
    load_settings: Loader,
) -> None:
    storage = _storage(load_settings("base"))
    assert storage["backend"] == ""
    assert storage["bucket_name"] == ""
    assert storage["access_key_id"] == ""
    assert storage["secret_access_key"] == ""
    assert "tenant_objects" not in load_settings("base").STORAGES


def test_base_with_a_complete_environment_selects_s3_and_reads_every_value(
    load_settings: Loader,
) -> None:
    base = load_settings(
        "base",
        **STORAGE_ENV,
        STORAGE_ADDRESSING="path",
        STORAGE_SSE="aes256",
        STORAGE_PRESIGN_SECONDS="120",
        STORAGE_MAX_OBJECT_BYTES="1048576",
    )
    storage = _storage(base)
    assert storage["backend"] == "s3"
    assert storage["bucket_name"] == STORAGE_ENV["STORAGE_BUCKET"]
    assert storage["endpoint_url"] == STORAGE_ENV["STORAGE_ENDPOINT_URL"]
    assert storage["access_key_id"] == STORAGE_ENV["STORAGE_ACCESS_KEY_ID"]
    assert storage["secret_access_key"] == STORAGE_ENV["STORAGE_SECRET_ACCESS_KEY"]
    assert storage["region_name"] == "us-east-1"
    assert storage["addressing_style"] == "path"
    assert storage["server_side_encryption"] == "AES256"
    assert storage["presign_seconds"] == 120
    assert storage["max_object_bytes"] == 1048576


def test_the_defaults_are_the_conservative_ones(load_settings: Loader) -> None:
    storage = _storage(
        load_settings(
            "base",
            STORAGE_BUCKET="uadas-tenant-data",
            STORAGE_ACCESS_KEY_ID="ci-key-4f7q2m9xj3kd8tlp",
            STORAGE_SECRET_ACCESS_KEY="wJ9r3Kd8Zx2PqL7mV5nB1cT6yH4sG0aE9uRf",
        )
    )
    assert storage["addressing_style"] is None  # boto3 decides
    assert storage["server_side_encryption"] == ""
    assert storage["presign_seconds"] == 300
    assert storage["endpoint_url"] == ""


def test_django_storages_is_configured_private_and_with_signed_urls(
    load_settings: Loader,
) -> None:
    options = load_settings(
        "base", **STORAGE_ENV, STORAGE_PRESIGN_SECONDS="90"
    ).STORAGES["tenant_objects"]["OPTIONS"]
    assert options["default_acl"] == "private"
    assert options["querystring_auth"] is True
    assert options["querystring_expire"] == 90
    assert options["bucket_name"] == STORAGE_ENV["STORAGE_BUCKET"]
    # Credentials are passed explicitly: django-storages would otherwise fall back to the
    # ambient AWS_* variables, a shared profile or an instance role.
    assert options["access_key"] == STORAGE_ENV["STORAGE_ACCESS_KEY_ID"]
    assert options["secret_key"] == STORAGE_ENV["STORAGE_SECRET_ACCESS_KEY"]
    assert options["signature_version"] == "s3v4"
    assert options["file_overwrite"] is True  # keys are unique by construction


# --- strict parsing: each rejection with its positive twin -------------------------

BAD_BUCKETS = [
    "ab",
    "A" * 3,
    "has_underscore",
    "-leading",
    "trailing-",
    "a..b",
    "x" * 64,
]
GOOD_BUCKETS = ["abc", "uadas-uploads", "a.b.c", "x" * 63, "0bucket9"]


@pytest.mark.parametrize("bucket", BAD_BUCKETS)
def test_a_malformed_bucket_name_is_refused(load_settings: Loader, bucket: str) -> None:
    env = {**STORAGE_ENV, "STORAGE_BUCKET": bucket}
    with pytest.raises(ImproperlyConfigured, match="STORAGE_BUCKET"):
        load_settings("base", **env)


@pytest.mark.parametrize("bucket", GOOD_BUCKETS)
def test_a_well_formed_bucket_name_is_accepted(
    load_settings: Loader, bucket: str
) -> None:
    env = {**STORAGE_ENV, "STORAGE_BUCKET": bucket}
    assert _storage(load_settings("base", **env))["bucket_name"] == bucket


BAD_ENDPOINTS = [
    "ftp://objects.example.com",
    "objects.example.com",
    "https://user:pw@objects.example.com",
    "https://objects.example.com/some/path",
    "https://objects.example.com?x=1",
    "https://objects.example.com#frag",
    "https://",
]
GOOD_ENDPOINTS = [
    "https://objects.example.com",
    "https://objects.example.com/",
    "http://localhost:9000",
    "https://abc123.r2.cloudflarestorage.com",
]


@pytest.mark.parametrize("endpoint", BAD_ENDPOINTS)
def test_a_malformed_endpoint_is_refused(load_settings: Loader, endpoint: str) -> None:
    env = {**STORAGE_ENV, "STORAGE_ENDPOINT_URL": endpoint}
    with pytest.raises(ImproperlyConfigured, match="STORAGE_ENDPOINT_URL"):
        load_settings("base", **env)


@pytest.mark.parametrize("endpoint", GOOD_ENDPOINTS)
def test_a_well_formed_endpoint_is_accepted(
    load_settings: Loader, endpoint: str
) -> None:
    env = {**STORAGE_ENV, "STORAGE_ENDPOINT_URL": endpoint}
    stored = _storage(load_settings("base", **env))["endpoint_url"]
    assert stored == endpoint.rstrip("/")


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("STORAGE_ADDRESSING", "subdomain"),
        ("STORAGE_SSE", "aws:kms"),
        ("STORAGE_PRESIGN_SECONDS", "soon"),
        ("STORAGE_PRESIGN_SECONDS", "0"),
        ("STORAGE_PRESIGN_SECONDS", "901"),
        ("STORAGE_MAX_OBJECT_BYTES", "0"),
        ("STORAGE_MAX_OBJECT_BYTES", "-5"),
        ("STORAGE_MAX_OBJECT_BYTES", "lots"),
    ],
)
def test_a_typo_in_an_option_stops_start_up(
    load_settings: Loader, variable: str, value: str
) -> None:
    with pytest.raises(ImproperlyConfigured, match=variable):
        load_settings("base", **STORAGE_ENV, **{variable: value})


@pytest.mark.parametrize(
    ("variable", "value", "expected_key", "expected"),
    [
        ("STORAGE_ADDRESSING", "path", "addressing_style", "path"),
        ("STORAGE_ADDRESSING", "virtual", "addressing_style", "virtual"),
        ("STORAGE_ADDRESSING", "AUTO", "addressing_style", None),
        ("STORAGE_SSE", "none", "server_side_encryption", ""),
        ("STORAGE_SSE", "AES256", "server_side_encryption", "AES256"),
        ("STORAGE_PRESIGN_SECONDS", "900", "presign_seconds", 900),
        ("STORAGE_PRESIGN_SECONDS", "1", "presign_seconds", 1),
        ("STORAGE_MAX_OBJECT_BYTES", "1", "max_object_bytes", 1),
    ],
)
def test_the_valid_forms_of_those_options_are_accepted(
    load_settings: Loader,
    variable: str,
    value: str,
    expected_key: str,
    expected: object,
) -> None:
    storage = _storage(load_settings("base", **STORAGE_ENV, **{variable: value}))
    assert storage[expected_key] == expected


@pytest.mark.parametrize(
    "missing",
    ["STORAGE_BUCKET", "STORAGE_ACCESS_KEY_ID", "STORAGE_SECRET_ACCESS_KEY"],
)
def test_a_partly_configured_store_fails_instead_of_half_working(
    load_settings: Loader, missing: str
) -> None:
    env = {k: v for k, v in STORAGE_ENV.items() if k != missing}
    with pytest.raises(ImproperlyConfigured, match=missing):
        load_settings("base", **env)


def test_ambient_aws_credentials_are_never_consulted(load_settings: Loader) -> None:
    storage = _storage(
        load_settings(
            "base",
            AWS_ACCESS_KEY_ID="ci-key-4f7q2m9xj3kd8tlp",
            AWS_SECRET_ACCESS_KEY="wJ9r3Kd8Zx2PqL7mV5nB1cT6yH4sG0aE9uRf",
        )
    )
    assert storage["backend"] == ""
    assert storage["access_key_id"] == ""


# --- dev: throwaway MinIO defaults, here and nowhere else ---------------------------


def test_an_endpoint_error_never_echoes_credentials_embedded_in_the_url(
    load_settings: Loader,
) -> None:
    env = {
        **STORAGE_ENV,
        "STORAGE_ENDPOINT_URL": "https://admin:hunter2pass@objects.example.com",
    }
    with pytest.raises(ImproperlyConfigured) as excinfo:
        load_settings("base", **env)
    assert "hunter2pass" not in str(excinfo.value)
    assert "STORAGE_ENDPOINT_URL" in str(excinfo.value)


def test_dev_defaults_apply_only_when_no_storage_variable_is_set(
    load_settings: Loader,
) -> None:
    # One variable set means the developer is configuring a store of their own: the
    # docker-compose credentials must not silently fill in the rest.
    with pytest.raises(ImproperlyConfigured, match="STORAGE_ACCESS_KEY_ID"):
        load_settings("dev", STORAGE_BUCKET="my-own-bucket")
    assert (
        _storage(load_settings("dev"))["access_key_id"] == "minioadmin"
    )  # twin: none set


def test_no_settings_module_wraps_requests_in_a_transaction(
    load_settings: Loader,
) -> None:
    """``StorageBackedPersistence.save`` is only atomic outside an outer transaction."""
    for name, env in (("dev", {}), ("test", {}), ("prod", PROD_ENV)):
        databases = load_settings(name, **env).DATABASES
        assert databases["default"].get("ATOMIC_REQUESTS", False) is False


def test_dev_defaults_to_the_docker_compose_minio(load_settings: Loader) -> None:
    storage = _storage(load_settings("dev"))
    assert storage["backend"] == "s3"
    assert storage["endpoint_url"] == "http://localhost:9000"
    assert storage["bucket_name"] == "uadas-uploads"
    assert storage["access_key_id"] == "minioadmin"
    assert (
        storage["secret_access_key"] == "minioadmin"
    )  # nosec B105 - throwaway dev value
    assert storage["addressing_style"] == "path"


def test_explicit_environment_beats_the_dev_defaults(load_settings: Loader) -> None:
    storage = _storage(load_settings("dev", **STORAGE_ENV))
    assert storage["bucket_name"] == STORAGE_ENV["STORAGE_BUCKET"]
    assert storage["endpoint_url"] == STORAGE_ENV["STORAGE_ENDPOINT_URL"]
    assert storage["access_key_id"] == STORAGE_ENV["STORAGE_ACCESS_KEY_ID"]


def test_dev_credentials_exist_in_no_other_settings_module(
    load_settings: Loader,
) -> None:
    for name in ("base", "test"):
        storage = _storage(load_settings(name))
        assert "minioadmin" not in repr(storage)
    with pytest.raises(ImproperlyConfigured):
        load_settings(
            "prod", **{k: v for k, v in PROD_ENV.items() if "STORAGE" not in k}
        )


# --- test: hermetic ----------------------------------------------------------------


def test_the_test_settings_use_the_in_memory_store_whatever_the_shell_exports(
    load_settings: Loader,
) -> None:
    storage = _storage(load_settings("test", **STORAGE_ENV))
    assert storage["backend"] == "memory"
    assert storage["endpoint_url"] == ""
    assert storage["secret_access_key"] == ""
    assert "tenant_objects" not in load_settings("test", **STORAGE_ENV).STORAGES


# --- prod: fail closed ---------------------------------------------------------------


def test_prod_accepts_a_complete_configuration(load_settings: Loader) -> None:
    storage = _storage(load_settings("prod", **PROD_ENV))
    assert storage["backend"] == "s3"
    assert storage["bucket_name"] == STORAGE_ENV["STORAGE_BUCKET"]


@pytest.mark.parametrize(
    "missing",
    ["STORAGE_BUCKET", "STORAGE_ACCESS_KEY_ID", "STORAGE_SECRET_ACCESS_KEY"],
)
def test_prod_refuses_to_start_without_a_bucket_or_credentials(
    load_settings: Loader, missing: str
) -> None:
    env = {k: v for k, v in PROD_ENV.items() if k != missing}
    with pytest.raises(ImproperlyConfigured, match="STORAGE"):
        load_settings("prod", **env)


def test_prod_refuses_a_plain_http_endpoint(load_settings: Loader) -> None:
    env = {**PROD_ENV, "STORAGE_ENDPOINT_URL": "http://objects.example.com"}
    with pytest.raises(ImproperlyConfigured, match="https"):
        load_settings("prod", **env)


def test_prod_without_an_endpoint_means_aws_and_is_accepted(
    load_settings: Loader,
) -> None:
    env = {k: v for k, v in PROD_ENV.items() if k != "STORAGE_ENDPOINT_URL"}
    assert _storage(load_settings("prod", **env))["endpoint_url"] == ""


@pytest.mark.parametrize(
    "secret",
    [
        "short",
        "a" * 40,
        "changeme-changeme-changeme-123456",
        "minioadmin",
        "my-placeholder-secret-value-1234567",
        "ExampleExampleExample0123456789ab",
        "password-password-password-1234567",
        "ci-key-4f7q2m9xj3kd8tlp",  # the access key id reused as the secret
    ],
)
def test_prod_rejects_short_weak_or_placeholder_secrets(
    load_settings: Loader, secret: str
) -> None:
    env = {**PROD_ENV, "STORAGE_SECRET_ACCESS_KEY": secret}
    with pytest.raises(ImproperlyConfigured, match="STORAGE_SECRET_ACCESS_KEY"):
        load_settings("prod", **env)


def test_prod_rejects_a_secret_identical_to_the_access_key_id(
    load_settings: Loader,
) -> None:
    # Long and varied enough to pass every other check, so only the equality can reject it.
    reused = "wJ9r3Kd8Zx2PqL7mV5nB1cT6yH4sG0aE9uRf"
    env = {
        **PROD_ENV,
        "STORAGE_ACCESS_KEY_ID": reused,
        "STORAGE_SECRET_ACCESS_KEY": reused,
    }
    with pytest.raises(ImproperlyConfigured, match="STORAGE_SECRET_ACCESS_KEY"):
        load_settings("prod", **env)


def test_prod_rejects_the_dev_access_key(load_settings: Loader) -> None:
    env = {**PROD_ENV, "STORAGE_ACCESS_KEY_ID": "minioadmin"}
    with pytest.raises(ImproperlyConfigured, match="STORAGE_ACCESS_KEY_ID"):
        load_settings("prod", **env)


def test_prod_requires_encryption_at_rest_unless_the_operator_acknowledges_its_absence(
    load_settings: Loader,
) -> None:
    without = {k: v for k, v in PROD_ENV.items() if k != "STORAGE_SSE"}
    with pytest.raises(ImproperlyConfigured, match="STORAGE_SSE"):
        load_settings("prod", **without)
    with pytest.raises(ImproperlyConfigured, match="STORAGE_SSE"):
        load_settings("prod", **{**without, "STORAGE_SSE": "none"})
    # Twins: SSE-S3 requested, or "none" with a conscious acknowledgement (a store or bucket
    # that encrypts by default and rejects the header).
    assert (
        _storage(load_settings("prod", **PROD_ENV))["server_side_encryption"]
        == "AES256"
    )
    acknowledged = {
        **without,
        "STORAGE_SSE": "none",
        "STORAGE_ENCRYPTION_ACKNOWLEDGED": "1",
    }
    storage = _storage(load_settings("prod", **acknowledged))
    assert (
        storage["server_side_encryption"] == ""
        and storage["encryption_acknowledged"] is True
    )


def test_the_acknowledgement_alone_does_not_override_a_requested_encryption(
    load_settings: Loader,
) -> None:
    storage = _storage(
        load_settings(
            "base",
            **STORAGE_ENV,
            STORAGE_SSE="aes256",
            STORAGE_ENCRYPTION_ACKNOWLEDGED="1",
        )
    )
    assert storage["server_side_encryption"] == "AES256"
    with pytest.raises(ImproperlyConfigured, match="STORAGE_ENCRYPTION_ACKNOWLEDGED"):
        load_settings("base", **STORAGE_ENV, STORAGE_ENCRYPTION_ACKNOWLEDGED="maybe")


def test_the_gc_grace_period_is_an_hour_by_default_and_bounded(
    load_settings: Loader,
) -> None:
    assert _storage(load_settings("base", **STORAGE_ENV))["gc_grace_seconds"] == 3600
    assert (
        _storage(load_settings("base", **STORAGE_ENV, STORAGE_GC_GRACE_SECONDS="0"))[
            "gc_grace_seconds"
        ]
        == 0
    )
    for bad in ("-1", "99999999", "soon"):
        with pytest.raises(ImproperlyConfigured, match="STORAGE_GC_GRACE_SECONDS"):
            load_settings("base", **STORAGE_ENV, STORAGE_GC_GRACE_SECONDS=bad)
    assert (
        _storage(load_settings("test"))["gc_grace_seconds"] == 0
    )  # hermetic tests collect at once


def test_prod_keeps_objects_private_and_urls_short_lived(load_settings: Loader) -> None:
    prod = load_settings("prod", **PROD_ENV)
    options = prod.STORAGES["tenant_objects"]["OPTIONS"]
    assert options["default_acl"] == "private"
    assert options["querystring_auth"] is True
    assert int(options["querystring_expire"]) <= 900
    assert int(str(_storage(prod)["presign_seconds"])) <= 900

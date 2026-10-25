# File: apps/api/tests/test_quota_settings.py
"""Settings for the per-tenant quotas (3.8): strict parsing, unlimited off-production, explicit in it.

Why: a quota the operator mistyped must stop start-up rather than become "no quota", and production
must never be unmetered by *omission* -- it states every limit or acknowledges unlimited out loud.
Each refusal is paired with the nearest accepted configuration, so a parser (or a production check)
that rejected everything could not pass, and the units conversion (megabytes -> bytes, minutes ->
seconds) is pinned because the rest of the quota code only ever sees the converted numbers.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured

from uadas_api.settings import _quota

Loader = Callable[..., ModuleType]

# A valid production environment (see test_settings.PROD_ENV), repeated so this module stands alone.
PROD_ENV = {
    "DJANGO_SECRET_KEY": "k" * 60,
    "DJANGO_ALLOWED_HOSTS": "api.example.com",
    "DATABASE_URL": "postgres://uadas:pw@db.internal:5432/uadas",
    "REDIS_URL": "redis://cache.internal:6379/0",
    "DEFAULT_FROM_EMAIL": "UADAS <no-reply@example.com>",
    "EMAIL_HOST": "smtp.example.com",
    "FRONTEND_BASE_URL": "https://app.example.com",
    "STORAGE_BUCKET": "uadas-tenant-data",
    "STORAGE_ENDPOINT_URL": "https://objects.example.com",
    "STORAGE_ACCESS_KEY_ID": "ci-key-4f7q2m9xj3kd8tlp",
    "STORAGE_SECRET_ACCESS_KEY": "wJ9r3Kd8Zx2PqL7mV5nB1cT6yH4sG0aE9uRf",
    "STORAGE_REGION": "us-east-1",
    "STORAGE_SSE": "aes256",
    "SANDBOX_ISOLATION_ACKNOWLEDGED": "container",
    "SANDBOX_NETWORK_ISOLATION": "container",
}
LIMITS = {
    "QUOTA_MAX_ROWS": "1000000",
    "QUOTA_MAX_STORAGE_MB": "512",
    "QUOTA_MAX_JOB_MINUTES": "600",
    "QUOTA_MAX_LLM_TOKENS": "2000000",
}


def test_unset_means_unlimited_everywhere_and_not_acknowledged() -> None:
    quota = _quota.parse_quota({})
    assert quota == {
        "max_rows": None,
        "max_storage_bytes": None,
        "max_job_seconds": None,
        "max_llm_tokens": None,
        "unlimited_acknowledged": False,
    }


def test_blank_values_are_unset_not_zero() -> None:
    assert _quota.parse_quota({"QUOTA_MAX_ROWS": "   "})["max_rows"] is None


def test_limits_are_converted_to_internal_units() -> None:
    quota = _quota.parse_quota(LIMITS)
    assert quota["max_rows"] == 1_000_000
    assert quota["max_storage_bytes"] == 512 * 1024 * 1024
    assert quota["max_job_seconds"] == 600 * 60
    assert quota["max_llm_tokens"] == 2_000_000


@pytest.mark.parametrize("name", sorted(_quota.LIMIT_VARIABLES))
@pytest.mark.parametrize("bad", ["many", "1.5", "0", "-3", "1e6"])
def test_a_malformed_or_non_positive_limit_stops_start_up(name: str, bad: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=name):
        _quota.parse_quota({name: bad})


@pytest.mark.parametrize("name", sorted(_quota.LIMIT_VARIABLES))
def test_the_smallest_valid_limit_is_accepted(name: str) -> None:
    quota = _quota.parse_quota({name: "1"})
    assert quota[_quota.LIMIT_VARIABLES[name]] is not None


@pytest.mark.parametrize("value", ["yes", "TRUE", "1", "on"])
def test_the_acknowledgement_accepts_the_usual_truthy_words(value: str) -> None:
    assert _quota.parse_quota({"QUOTA_UNLIMITED_ACKNOWLEDGED": value})[
        "unlimited_acknowledged"
    ]


def test_a_mistyped_acknowledgement_is_an_error_not_false() -> None:
    with pytest.raises(ImproperlyConfigured, match="QUOTA_UNLIMITED_ACKNOWLEDGED"):
        _quota.parse_quota({"QUOTA_UNLIMITED_ACKNOWLEDGED": "ture"})


# --------------------------------------------------------------- production rule


def test_production_accepts_every_limit_stated() -> None:
    _quota.validate_for_production(_quota.parse_quota(LIMITS))


def test_production_accepts_unlimited_when_acknowledged() -> None:
    _quota.validate_for_production(
        _quota.parse_quota({"QUOTA_UNLIMITED_ACKNOWLEDGED": "true"})
    )


def test_production_refuses_silence_and_names_what_is_missing() -> None:
    with pytest.raises(ImproperlyConfigured) as raised:
        _quota.validate_for_production(_quota.parse_quota({}))
    for name in _quota.LIMIT_VARIABLES:
        assert name in str(raised.value)
    assert "QUOTA_UNLIMITED_ACKNOWLEDGED" in str(raised.value)


def test_production_refuses_a_partial_statement_and_names_only_the_gap() -> None:
    partial = {k: v for k, v in LIMITS.items() if k != "QUOTA_MAX_LLM_TOKENS"}
    with pytest.raises(ImproperlyConfigured, match="QUOTA_MAX_LLM_TOKENS") as raised:
        _quota.validate_for_production(_quota.parse_quota(partial))
    assert "QUOTA_MAX_ROWS" not in str(raised.value)


# --------------------------------------------------- the settings modules use it


def test_prod_settings_refuse_to_start_without_a_quota_statement(
    load_settings: Loader,
) -> None:
    with pytest.raises(ImproperlyConfigured, match="QUOTA_MAX_ROWS"):
        load_settings("prod", **PROD_ENV)


def test_prod_settings_load_with_every_limit(load_settings: Loader) -> None:
    prod = load_settings("prod", **PROD_ENV, **LIMITS)
    assert prod.UADAS_QUOTA["max_rows"] == 1_000_000
    assert prod.UADAS_QUOTA["unlimited_acknowledged"] is False


def test_prod_settings_load_with_the_unlimited_acknowledgement(
    load_settings: Loader,
) -> None:
    prod = load_settings("prod", **PROD_ENV, QUOTA_UNLIMITED_ACKNOWLEDGED="true")
    assert prod.UADAS_QUOTA["max_rows"] is None
    assert prod.UADAS_QUOTA["unlimited_acknowledged"] is True


def test_dev_settings_are_unlimited_by_default(load_settings: Loader) -> None:
    assert load_settings("dev").UADAS_QUOTA["max_rows"] is None


def test_the_test_settings_ignore_the_environment(
    load_settings: Loader, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A developer's QUOTA_* must not change a test's outcome (same rule as UADAS_JOBS).
    test = load_settings("test", **LIMITS)
    assert test.UADAS_QUOTA["max_rows"] is None

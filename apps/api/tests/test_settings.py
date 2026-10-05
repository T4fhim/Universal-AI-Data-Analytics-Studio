# File: apps/api/tests/test_settings.py
"""Settings-module contract tests (Phase 3.1).

Why: the settings split is the security boundary of the backend. ``base`` must carry
no insecure default, ``dev`` may relax things for a laptop, ``prod`` must refuse to
start unconfigured and must not be switchable into debug mode by an env var, and
``test`` must be hermetic. Each module is imported afresh under a scrubbed
environment (see ``conftest.load_settings``) so these tests do not depend on the
shell they run in.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured

Loader = Callable[..., ModuleType]

PROD_ENV = {
    "DJANGO_SECRET_KEY": "k" * 60,
    "DJANGO_ALLOWED_HOSTS": "api.example.com",
    "DATABASE_URL": "postgres://uadas:pw@db.internal:5432/uadas",
    # Added in 3.3: auth needs a shared cache (rate limits), a mail relay (verification
    # and password-reset mail) and the SPA's address (links inside those mails).
    "REDIS_URL": "redis://cache.internal:6379/0",
    "DEFAULT_FROM_EMAIL": "UADAS <no-reply@example.com>",
    "EMAIL_HOST": "smtp.example.com",
    "FRONTEND_BASE_URL": "https://app.example.com",
}


# --- base --------------------------------------------------------------------


def test_base_has_no_insecure_defaults(load_settings: Loader) -> None:
    base = load_settings("base")
    assert base.SECRET_KEY == ""  # empty -> Django itself refuses to start
    assert base.DEBUG is False
    assert base.ALLOWED_HOSTS == []
    assert base.CORS_ALLOWED_ORIGINS == []
    assert base.CSRF_TRUSTED_ORIGINS == []
    assert base.DATABASES == {}  # no silent local-file database


def test_base_reads_twelve_factor_environment(load_settings: Loader) -> None:
    base = load_settings(
        "base",
        DJANGO_SECRET_KEY="s3cret",
        DJANGO_DEBUG="true",
        DJANGO_ALLOWED_HOSTS="a.example.com, b.example.com ,",
        CORS_ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com",
        CSRF_TRUSTED_ORIGINS="https://app.example.com",
        DATABASE_URL="sqlite:///tmp-test.sqlite3",
    )
    assert base.SECRET_KEY == "s3cret"
    assert base.DEBUG is True
    assert base.ALLOWED_HOSTS == ["a.example.com", "b.example.com"]
    assert base.CORS_ALLOWED_ORIGINS == [
        "https://app.example.com",
        "https://admin.example.com",
    ]
    assert base.CSRF_TRUSTED_ORIGINS == ["https://app.example.com"]
    assert base.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("0", False),
        ("no", False),
        ("off", False),
        ("False", False),
        ("", False),
    ],
)
def test_base_debug_flag_parsing(
    load_settings: Loader, raw: str, expected: bool
) -> None:
    assert load_settings("base", DJANGO_DEBUG=raw).DEBUG is expected


def test_base_rejects_an_unrecognised_boolean(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_DEBUG"):
        load_settings("base", DJANGO_DEBUG="ture")


def test_base_database_url_postgres(load_settings: Loader) -> None:
    base = load_settings(
        "base", DATABASE_URL="postgres://uadas:pw@db.internal:5432/uadas"
    )
    default = base.DATABASES["default"]
    assert default["ENGINE"] == "django.db.backends.postgresql"
    assert default["NAME"] == "uadas"
    assert default["HOST"] == "db.internal"


def test_base_registers_the_five_apps_and_cors(load_settings: Loader) -> None:
    base = load_settings("base")
    for app in ("accounts", "workspaces", "pipeline", "ai", "exports"):
        assert f"uadas_api.{app}" in base.INSTALLED_APPS
    assert "corsheaders" in base.INSTALLED_APPS
    assert base.ROOT_URLCONF == "uadas_api.urls"


# --- dev ---------------------------------------------------------------------


def test_dev_allows_an_insecure_key_and_turns_debug_on(load_settings: Loader) -> None:
    dev = load_settings("dev")
    assert dev.DEBUG is True
    assert dev.SECRET_KEY  # non-empty even though DJANGO_SECRET_KEY is unset
    assert "insecure" in dev.SECRET_KEY


def test_dev_prefers_an_explicit_secret_key(load_settings: Loader) -> None:
    assert load_settings("dev", DJANGO_SECRET_KEY="mine").SECRET_KEY == "mine"


def test_dev_defaults_to_sqlite_and_honours_database_url(load_settings: Loader) -> None:
    dev = load_settings("dev")
    assert dev.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert str(dev.DATABASES["default"]["NAME"]).endswith("db.sqlite3")
    pg = load_settings("dev", DATABASE_URL="postgres://u:p@h:5432/d")
    assert pg.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


# --- test --------------------------------------------------------------------


def test_test_settings_are_hermetic_and_fast(load_settings: Loader) -> None:
    mod = load_settings("test")
    assert mod.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert mod.DATABASES["default"]["NAME"] == ":memory:"
    assert mod.PASSWORD_HASHERS == ["django.contrib.auth.hashers.MD5PasswordHasher"]
    assert mod.SECRET_KEY
    assert mod.DEBUG is False


def test_live_test_settings_are_active(settings: object) -> None:
    from django.conf import settings as live

    assert live.SETTINGS_MODULE == "uadas_api.settings.test"
    assert live.PASSWORD_HASHERS == ["django.contrib.auth.hashers.MD5PasswordHasher"]


# --- prod --------------------------------------------------------------------


def test_prod_loads_with_valid_environment(load_settings: Loader) -> None:
    prod = load_settings("prod", **PROD_ENV)
    assert PROD_ENV["DJANGO_SECRET_KEY"] == prod.SECRET_KEY
    assert prod.ALLOWED_HOSTS == ["api.example.com"]


def _prod_env_without(*names: str, **overrides: str) -> dict[str, str]:
    env = {k: v for k, v in PROD_ENV.items() if k not in names}
    env.update(overrides)
    return env


def test_prod_refuses_missing_secret_key(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        load_settings("prod", **_prod_env_without("DJANGO_SECRET_KEY"))


def test_prod_refuses_blank_secret_key(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        load_settings("prod", **_prod_env_without(DJANGO_SECRET_KEY="   "))


@pytest.mark.parametrize(
    "key",
    ["changeme", "k" * 49, "django-insecure-" + "x" * 60],
    ids=["too-short", "49-chars", "django-insecure-prefix"],
)
def test_prod_refuses_a_weak_secret_key(load_settings: Loader, key: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        load_settings("prod", **_prod_env_without(DJANGO_SECRET_KEY=key))


def test_prod_refuses_missing_allowed_hosts(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_ALLOWED_HOSTS"):
        load_settings("prod", **_prod_env_without("DJANGO_ALLOWED_HOSTS"))


def test_prod_refuses_empty_allowed_hosts(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_ALLOWED_HOSTS"):
        load_settings("prod", **_prod_env_without(DJANGO_ALLOWED_HOSTS=" , "))


@pytest.mark.parametrize("hosts", ["*", "api.example.com, *"])
def test_prod_refuses_a_wildcard_host(load_settings: Loader, hosts: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_ALLOWED_HOSTS"):
        load_settings("prod", **_prod_env_without(DJANGO_ALLOWED_HOSTS=hosts))


def test_prod_refuses_a_missing_database_url(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
        load_settings("prod", **_prod_env_without("DATABASE_URL"))


@pytest.mark.parametrize("raw", ["0", "-5"])
def test_prod_refuses_hsts_that_is_not_positive(
    load_settings: Loader, raw: str
) -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECURE_HSTS_SECONDS"):
        load_settings("prod", DJANGO_SECURE_HSTS_SECONDS=raw, **PROD_ENV)


def test_prod_rejects_an_unrecognised_boolean_instead_of_failing_open(
    load_settings: Loader,
) -> None:
    # "flase" used to parse as False and silently switch the HTTPS redirect off.
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECURE_SSL_REDIRECT"):
        load_settings("prod", DJANGO_SECURE_SSL_REDIRECT="flase", **PROD_ENV)


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on"])
def test_prod_forces_debug_false(load_settings: Loader, raw: str) -> None:
    assert load_settings("prod", DJANGO_DEBUG=raw, **PROD_ENV).DEBUG is False


def test_prod_security_defaults(load_settings: Loader) -> None:
    prod = load_settings("prod", **PROD_ENV)
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SECURE_SSL_REDIRECT is True
    assert prod.SECURE_HSTS_SECONDS >= 31536000
    assert prod.SECURE_HSTS_INCLUDE_SUBDOMAINS is True
    assert prod.SECURE_HSTS_PRELOAD is True
    assert prod.SECURE_CONTENT_TYPE_NOSNIFF is True
    # Trusting X-Forwarded-Proto is only safe behind a proxy that sets it, so the
    # header is off unless the operator opts in.
    assert prod.SECURE_PROXY_SSL_HEADER is None


def test_prod_security_knobs_are_env_configurable(load_settings: Loader) -> None:
    prod = load_settings(
        "prod",
        DJANGO_SECURE_SSL_REDIRECT="false",
        DJANGO_SECURE_HSTS_SECONDS="60",
        DJANGO_SECURE_PROXY_SSL_HEADER="true",
        **PROD_ENV,
    )
    assert prod.SECURE_SSL_REDIRECT is False
    assert prod.SECURE_HSTS_SECONDS == 60
    assert prod.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_prod_rejects_a_non_integer_hsts_value(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECURE_HSTS_SECONDS"):
        load_settings("prod", DJANGO_SECURE_HSTS_SECONDS="a-lot", **PROD_ENV)

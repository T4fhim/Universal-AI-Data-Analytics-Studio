# File: apps/api/tests/test_auth_settings.py
"""Configuration contract for authentication (Phase 3.3).

Why: auth correctness is mostly *configuration* -- which verification mode runs where,
whether the rate limits have a shared cache behind them, whether an OAuth provider is on
only when its credentials exist, whether the cookies carry the right flags. Each of those
is a one-line setting that silently regresses, so each is pinned here. Every settings
module is imported afresh under a scrubbed environment (``conftest.load_settings``), and
nothing touches the network. Every refusal test is paired with a test that the legitimate
configuration loads, so a refusal cannot pass because the module fails for another reason.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured
from test_settings import PROD_ENV

Loader = Callable[..., ModuleType]

GITHUB = {"GITHUB_CLIENT_ID": "gh-id-fake", "GITHUB_CLIENT_SECRET": "gh-secret-fake"}
GOOGLE = {"GOOGLE_CLIENT_ID": "g-id-fake", "GOOGLE_CLIENT_SECRET": "g-secret-fake"}


# --- headless, email-only login ----------------------------------------------------


def test_allauth_is_headless_browser_only_with_email_login(
    load_settings: Loader,
) -> None:
    base = load_settings("base")
    for app in (
        "allauth",
        "allauth.account",
        "allauth.headless",
        "allauth.socialaccount",
    ):
        assert app in base.INSTALLED_APPS
    assert base.HEADLESS_ONLY is True
    # Session cookies only: no token strategy for non-browser "app" clients.
    assert base.HEADLESS_CLIENTS == ("browser",)
    assert {"email"} == base.ACCOUNT_LOGIN_METHODS
    assert base.ACCOUNT_SIGNUP_FIELDS == ["email*", "password1*"]
    assert base.ACCOUNT_USER_MODEL_USERNAME_FIELD is None
    assert (
        "allauth.account.middleware.AccountMiddleware" in base.MIDDLEWARE
    ), "allauth.account refuses to run without its middleware"
    assert base.MIDDLEWARE.index(
        "allauth.account.middleware.AccountMiddleware"
    ) > base.MIDDLEWARE.index("django.contrib.auth.middleware.AuthenticationMiddleware")


def test_enumeration_prevention_is_not_switched_off(load_settings: Loader) -> None:
    # Unset means allauth's default, which is on. Checked in every environment module,
    # because an override in dev/test/prod would not show up in `base`.
    for name, env in (("base", {}), ("dev", {}), ("test", {}), ("prod", PROD_ENV)):
        module = load_settings(name, **env)
        assert getattr(module, "ACCOUNT_PREVENT_ENUMERATION", True) is not False, name
        assert not hasattr(module, "ACCOUNT_PREVENT_ENUMERATION") or (
            module.ACCOUNT_PREVENT_ENUMERATION in (True, "strict")
        ), name


def test_authentication_backends_are_the_model_backend_then_allauths(
    load_settings: Loader,
) -> None:
    base = load_settings("base")
    assert base.AUTHENTICATION_BACKENDS == [
        "django.contrib.auth.backends.ModelBackend",
        "allauth.account.auth_backends.AuthenticationBackend",
    ]


def test_password_validators_are_configured(load_settings: Loader) -> None:
    validators = {
        v["NAME"].rsplit(".", 1)[1]: v
        for v in load_settings("base").AUTH_PASSWORD_VALIDATORS
    }
    assert set(validators) == {
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    }
    assert validators["MinimumLengthValidator"]["OPTIONS"]["min_length"] >= 12


def test_allauth_rate_limits_are_configured(load_settings: Loader) -> None:
    limits = load_settings("base").ACCOUNT_RATE_LIMITS
    for action in ("login", "login_failed", "signup", "reset_password"):
        assert limits[action], f"{action} must have an explicit limit"
    # A failed-login limit keyed on the *account* (key), not only the address: a
    # distributed guesser rotating IPs must still hit it.
    assert "/key" in limits["login_failed"]
    assert "/ip" in limits["login_failed"]


# --- email verification per environment -------------------------------------------


def test_email_verification_is_mandatory_in_prod(load_settings: Loader) -> None:
    prod = load_settings("prod", **PROD_ENV)
    assert prod.ACCOUNT_EMAIL_VERIFICATION == "mandatory"


def test_email_verification_is_relaxed_in_dev_and_off_in_test(
    load_settings: Loader,
) -> None:
    assert load_settings("dev").ACCOUNT_EMAIL_VERIFICATION == "optional"
    assert load_settings("test").ACCOUNT_EMAIL_VERIFICATION == "none"


def test_prod_verification_mode_is_not_an_environment_switch(
    load_settings: Loader,
) -> None:
    prod = load_settings("prod", ACCOUNT_EMAIL_VERIFICATION="none", **PROD_ENV)
    assert prod.ACCOUNT_EMAIL_VERIFICATION == "mandatory"


# --- cookies and CSRF ---------------------------------------------------------------


def test_session_cookie_flags(load_settings: Loader) -> None:
    for name, env in (("base", {}), ("dev", {}), ("test", {}), ("prod", PROD_ENV)):
        mod = load_settings(name, **env)
        assert mod.SESSION_COOKIE_HTTPONLY is True, name
        assert mod.SESSION_COOKIE_SAMESITE == "Lax", name
        assert mod.CSRF_COOKIE_SAMESITE == "Lax", name
        # The SPA reads the CSRF cookie to echo it in a header; HttpOnly would make that
        # impossible (the session cookie, which is the secret, stays HttpOnly).
        assert mod.CSRF_COOKIE_HTTPONLY is False, name


def test_prod_cookies_are_secure_and_dev_cookies_are_not(load_settings: Loader) -> None:
    prod = load_settings("prod", **PROD_ENV)
    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert getattr(load_settings("dev"), "SESSION_COOKIE_SECURE", False) is False


def test_cors_allows_credentials_only_for_listed_origins(load_settings: Loader) -> None:
    base = load_settings("base")
    # Credentials are needed for the cross-origin SPA's cookies; they are safe because
    # CORS_ALLOW_ALL_ORIGINS stays off and the origin list defaults to empty.
    assert base.CORS_ALLOW_CREDENTIALS is True
    assert getattr(base, "CORS_ALLOW_ALL_ORIGINS", False) is False
    assert base.CORS_ALLOWED_ORIGINS == []


# --- cache (shared rate-limit counters) ---------------------------------------------


def test_cache_is_locmem_without_redis_url(load_settings: Loader) -> None:
    for name in ("base", "dev", "test"):
        default = load_settings(name).CACHES["default"]
        assert (
            default["BACKEND"] == "django.core.cache.backends.locmem.LocMemCache"
        ), name


def test_cache_uses_redis_when_redis_url_is_set(load_settings: Loader) -> None:
    default = load_settings("base", REDIS_URL="redis://r.internal:6379/1").CACHES[
        "default"
    ]
    assert default["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    assert default["LOCATION"] == "redis://r.internal:6379/1"


def test_prod_requires_redis_url_and_uses_it(load_settings: Loader) -> None:
    env = {k: v for k, v in PROD_ENV.items() if k != "REDIS_URL"}
    with pytest.raises(ImproperlyConfigured, match="REDIS_URL"):
        load_settings("prod", **env)
    prod = load_settings("prod", **PROD_ENV)
    assert (
        prod.CACHES["default"]["BACKEND"]
        == "django.core.cache.backends.redis.RedisCache"
    )
    assert prod.CACHES["default"]["LOCATION"] == PROD_ENV["REDIS_URL"]


def test_prod_trusted_proxy_count_defaults_to_zero_and_is_configurable(
    load_settings: Loader,
) -> None:
    assert load_settings("prod", **PROD_ENV).ALLAUTH_TRUSTED_PROXY_COUNT == 0
    prod = load_settings("prod", DJANGO_TRUSTED_PROXY_COUNT="1", **PROD_ENV)
    assert prod.ALLAUTH_TRUSTED_PROXY_COUNT == 1
    with pytest.raises(ImproperlyConfigured, match="DJANGO_TRUSTED_PROXY_COUNT"):
        load_settings("prod", DJANGO_TRUSTED_PROXY_COUNT="-1", **PROD_ENV)


# --- email ---------------------------------------------------------------------------


def test_email_backends_per_environment(load_settings: Loader) -> None:
    assert (
        load_settings("dev").EMAIL_BACKEND
        == "django.core.mail.backends.console.EmailBackend"
    )
    assert (
        load_settings("test").EMAIL_BACKEND
        == "django.core.mail.backends.locmem.EmailBackend"
    )
    assert (
        load_settings("prod", **PROD_ENV).EMAIL_BACKEND
        == "django.core.mail.backends.smtp.EmailBackend"
    )


def test_prod_reads_smtp_settings_from_the_environment(load_settings: Loader) -> None:
    prod = load_settings(
        "prod",
        EMAIL_PORT="2525",
        EMAIL_HOST_USER="mailer",
        EMAIL_HOST_PASSWORD="smtp-pw-fake",
        EMAIL_USE_TLS="false",
        **PROD_ENV,
    )
    assert prod.EMAIL_HOST == "smtp.example.com"
    assert prod.EMAIL_PORT == 2525
    assert prod.EMAIL_HOST_USER == "mailer"
    assert prod.EMAIL_HOST_PASSWORD == "smtp-pw-fake"  # nosec B105
    assert prod.EMAIL_USE_TLS is False
    assert prod.DEFAULT_FROM_EMAIL == "UADAS <no-reply@example.com>"


def test_prod_smtp_defaults_are_tls_on_587_with_no_credentials(
    load_settings: Loader,
) -> None:
    prod = load_settings("prod", **PROD_ENV)
    assert prod.EMAIL_PORT == 587
    assert prod.EMAIL_USE_TLS is True
    # Secrets have no default: unset means "no authentication", never a baked-in value.
    assert prod.EMAIL_HOST_USER == ""
    assert prod.EMAIL_HOST_PASSWORD == ""


@pytest.mark.parametrize(
    "missing", ["EMAIL_HOST", "DEFAULT_FROM_EMAIL", "FRONTEND_BASE_URL"]
)
def test_prod_refuses_a_missing_mail_or_frontend_setting(
    load_settings: Loader, missing: str
) -> None:
    env = {k: v for k, v in PROD_ENV.items() if k != missing}
    with pytest.raises(ImproperlyConfigured, match=missing):
        load_settings("prod", **env)


@pytest.mark.parametrize("bad", ["not-an-address", "Name <>", "two words"])
def test_prod_refuses_a_malformed_from_address(load_settings: Loader, bad: str) -> None:
    env = {**PROD_ENV, "DEFAULT_FROM_EMAIL": bad}
    with pytest.raises(ImproperlyConfigured, match="DEFAULT_FROM_EMAIL"):
        load_settings("prod", **env)


def test_prod_refuses_a_non_http_frontend_url(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="FRONTEND_BASE_URL"):
        load_settings("prod", **{**PROD_ENV, "FRONTEND_BASE_URL": "app.example.com"})
    ok = load_settings(
        "prod", **{**PROD_ENV, "FRONTEND_BASE_URL": "https://app.example.com/"}
    )
    assert ok.HEADLESS_FRONTEND_URLS["account_confirm_email"] == (
        "https://app.example.com/account/verify-email/{key}"
    )


def test_prod_requires_an_https_frontend_url(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="https"):
        load_settings(
            "prod", **{**PROD_ENV, "FRONTEND_BASE_URL": "http://app.example.com"}
        )
    # dev/test may use plain http (the Vite dev server); prod with https loads.
    assert load_settings("dev").FRONTEND_BASE_URL.startswith("http://")
    assert load_settings("prod", **PROD_ENV).FRONTEND_BASE_URL.startswith("https://")


def test_prod_rejects_a_non_integer_smtp_port(load_settings: Loader) -> None:
    with pytest.raises(ImproperlyConfigured, match="EMAIL_PORT"):
        load_settings("prod", EMAIL_PORT="smtp", **PROD_ENV)


# --- OAuth providers (config logic only; nothing here touches the network) -----------


def test_no_provider_is_configured_without_credentials(load_settings: Loader) -> None:
    base = load_settings("base")
    assert base.SOCIALACCOUNT_PROVIDERS == {}
    assert not [
        a
        for a in base.INSTALLED_APPS
        if a.startswith("allauth.socialaccount.providers")
    ]


def test_github_is_enabled_only_with_both_credentials(load_settings: Loader) -> None:
    base = load_settings("base", **GITHUB)
    assert set(base.SOCIALACCOUNT_PROVIDERS) == {"github"}
    app = base.SOCIALACCOUNT_PROVIDERS["github"]["APPS"][0]
    assert app["client_id"] == "gh-id-fake"
    assert app["secret"] == "gh-secret-fake"  # nosec B105
    assert "allauth.socialaccount.providers.github" in base.INSTALLED_APPS
    assert "allauth.socialaccount.providers.google" not in base.INSTALLED_APPS


def test_google_is_enabled_only_with_both_credentials(load_settings: Loader) -> None:
    base = load_settings("base", **GOOGLE)
    assert set(base.SOCIALACCOUNT_PROVIDERS) == {"google"}
    assert base.SOCIALACCOUNT_PROVIDERS["google"]["APPS"][0]["client_id"] == "g-id-fake"
    assert "allauth.socialaccount.providers.google" in base.INSTALLED_APPS
    assert "allauth.socialaccount.providers.github" not in base.INSTALLED_APPS


def test_both_providers_can_be_enabled_together(load_settings: Loader) -> None:
    base = load_settings("base", **GITHUB, **GOOGLE)
    assert set(base.SOCIALACCOUNT_PROVIDERS) == {"github", "google"}


@pytest.mark.parametrize(
    "half", [{"GITHUB_CLIENT_ID": "x"}, {"GOOGLE_CLIENT_SECRET": "y"}]
)
def test_a_half_configured_provider_fails_loudly(
    load_settings: Loader, half: dict[str, str]
) -> None:
    # Silently skipping a provider whose secret was forgotten would look like a working
    # deployment with a missing "Sign in with ..." button.
    with pytest.raises(ImproperlyConfigured, match="CLIENT_"):
        load_settings("base", **half)


def test_blank_credentials_count_as_unset(load_settings: Loader) -> None:
    base = load_settings("base", GITHUB_CLIENT_ID=" ", GITHUB_CLIENT_SECRET="")
    assert base.SOCIALACCOUNT_PROVIDERS == {}


def test_social_hardening_defaults(load_settings: Loader) -> None:
    base = load_settings("base", **GITHUB)
    # No provider access tokens are stored (nothing in the product calls a provider API).
    assert base.SOCIALACCOUNT_STORE_TOKENS is False
    # A provider-asserted email must never silently attach to an existing local account.
    assert base.SOCIALACCOUNT_EMAIL_AUTHENTICATION is False
    # The provider's own "verified" flag is trusted only if the provider sets it.
    assert base.SOCIALACCOUNT_PROVIDERS["github"].get("VERIFIED_EMAIL", False) is False
    assert base.ACCOUNT_ADAPTER == "uadas_api.accounts.adapters.AccountAdapter"
    assert (
        base.SOCIALACCOUNT_ADAPTER == "uadas_api.accounts.adapters.SocialAccountAdapter"
    )

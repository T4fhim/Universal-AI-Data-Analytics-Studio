# File: apps/api/tests/test_auth_flow.py
"""The authentication flow through allauth's headless browser API (Phase 3.3).

Why: allauth supplies the endpoints; what this project owns -- and must prove -- is the
wiring around them: that signup provisions a personal organization atomically, that login
and logout are audited, that the session cookie has the right flags, that password rules,
verification and rate limits are actually in force, and that enumeration prevention is
still on. Everything goes through real HTTP-shaped requests with CSRF enforcement (see
``apihelpers.Api``). Each refusal is paired with the legitimate path.

Test settings use ``ACCOUNT_EMAIL_VERIFICATION = "none"`` (so most flows can sign up and be
logged in at once); the verification tests flip it to ``mandatory`` as production does.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

import pytest
from apihelpers import CONFIG_URL, Api
from django.core import mail
from django.test import Client, RequestFactory
from factories import make_organization, make_user

from uadas_api.accounts import services
from uadas_api.accounts.models import AuditEvent, Membership, Organization, Role, User

pytestmark = pytest.mark.django_db

BASE = "/api/auth/browser/v1"
PASSWORD = "Correct-Horse-9-Battery"  # nosec B105 - a throwaway test value


def _signup(
    api: Api, email: str = "ada.lovelace@example.com", password: str = PASSWORD
) -> Any:
    return api.post(f"{BASE}/auth/signup", {"email": email, "password": password})


def _login(api: Api, email: str, password: str = PASSWORD) -> Any:
    return api.post(f"{BASE}/auth/login", {"email": email, "password": password})


def _actions(user: User) -> list[str]:
    return list(
        AuditEvent.objects.filter(actor=user)
        .order_by("created_at")
        .values_list("action", flat=True)
    )


# --- CSRF bootstrap and enforcement ------------------------------------------------------


def test_config_endpoint_bootstraps_the_csrf_cookie() -> None:
    client = Client()
    response = client.get(CONFIG_URL)
    assert response.status_code == 200
    assert "csrftoken" in response.cookies
    assert (
        response.json()["data"]["socialaccount"]["providers"] == []
    )  # none configured


def test_the_app_client_with_bearer_tokens_is_not_exposed() -> None:
    assert Client().get("/api/auth/app/v1/config").status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        (
            "POST",
            f"{BASE}/auth/signup",
            {"email": "csrf@example.com", "password": PASSWORD},
        ),
        (
            "POST",
            f"{BASE}/auth/login",
            {"email": "csrf@example.com", "password": PASSWORD},
        ),
        ("POST", f"{BASE}/auth/password/request", {"email": "csrf@example.com"}),
        ("DELETE", f"{BASE}/auth/session", None),
    ],
    ids=["signup", "login", "password-request", "logout"],
)
def test_allauth_state_changes_are_refused_without_the_csrf_token(
    method: str, path: str, body: dict[str, str] | None
) -> None:
    api = Api()
    refused = api.request(method, path, body, csrf=False)
    assert refused.status_code == 403
    assert not User.objects.filter(email="csrf@example.com").exists()
    # Same request with the token is *not* a CSRF refusal (it may fail on its merits).
    accepted = api.request(method, path, body, csrf=True)
    assert accepted.status_code != 403


# --- signup provisions a personal organization --------------------------------------------


def test_signup_creates_user_personal_org_owner_membership_and_audit_events() -> None:
    api = Api()
    response = _signup(api)
    assert response.status_code == 200, response.content
    user = User.objects.get(email="ada.lovelace@example.com")
    membership = Membership.objects.get(user=user)
    assert membership.role == Role.OWNER
    org = membership.organization
    assert org.name == "ada.lovelace"
    assert org.slug.startswith("ada-lovelace")
    signed_up = AuditEvent.objects.get(organization=org, action="user.signed_up")
    assert (signed_up.actor_id, signed_up.target_type, signed_up.target_id) == (
        user.pk,
        "user",
        str(user.pk),
    )
    created = AuditEvent.objects.get(organization=org, action="organization.created")
    assert created.metadata == {"personal": True}
    # ...and the new session can read its own memberships straight away.
    me = api.get("/api/me").json()
    assert [m["role"] for m in me["memberships"]] == ["owner"]


def test_signup_audit_metadata_holds_no_secrets() -> None:
    _signup(Api())
    text = " ".join(str(e.metadata) for e in AuditEvent.objects.all())
    assert PASSWORD not in text
    assert "password" not in text.lower()


def test_signup_is_one_transaction_with_the_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit store down")

    monkeypatch.setattr(services, "record_audit", boom)
    with pytest.raises(RuntimeError):
        _signup(Api(), "atomic@example.com")
    # No user without an organization, no organization without an owner.
    assert not User.objects.filter(email="atomic@example.com").exists()
    assert not Organization.objects.exists()
    assert not Membership.objects.exists()


def test_signup_still_works_when_nothing_is_broken() -> None:
    # The positive twin of the rollback test above.
    assert _signup(Api(), "fine@example.com").status_code == 200
    assert Organization.objects.count() == 1


def test_two_signups_with_the_same_local_part_get_unique_slugs() -> None:
    _signup(Api(), "sam@example.com")
    _signup(Api(), "sam@example.org")
    slugs = list(Organization.objects.values_list("slug", flat=True))
    assert len(slugs) == len(set(slugs)) == 2
    assert all(s.startswith("sam") for s in slugs)


def test_a_slug_collision_with_an_existing_organization_is_resolved() -> None:
    make_organization(slug="sam")
    _signup(Api(), "sam@example.com")
    org = Membership.objects.get(user__email="sam@example.com").organization
    assert org.slug != "sam"
    assert org.slug.startswith("sam-")


def test_provisioning_is_idempotent_for_a_user_who_already_has_an_organization() -> (
    None
):
    user = make_user("already@example.com")
    first = services.provision_personal_organization(user)
    assert first is not None
    assert services.provision_personal_organization(user) is None
    assert Membership.objects.filter(user=user).count() == 1


def test_a_provider_signup_gets_a_personal_organization_too() -> None:
    # OAuth first login goes through SocialAccountAdapter.save_user, not the signup form.
    from allauth.socialaccount.models import SocialAccount, SocialLogin

    from uadas_api.accounts.adapters import SocialAccountAdapter

    request = RequestFactory().get("/")
    request.session = Client().session
    sociallogin = SocialLogin(
        user=User(email="octo.cat@example.com"),
        account=SocialAccount(provider="github", uid="4242"),
    )
    user = SocialAccountAdapter().save_user(request, sociallogin)
    assert isinstance(user, User)
    membership = Membership.objects.get(user=user)
    assert membership.role == Role.OWNER
    assert membership.organization.name == "octo.cat"
    assert AuditEvent.objects.filter(
        organization=membership.organization, action="user.signed_up"
    ).exists()
    assert not user.has_usable_password()  # a provider account has no local password


# --- login / logout -----------------------------------------------------------------------


def test_login_succeeds_ignoring_email_case_and_is_audited() -> None:
    _signup(Api(), "Grace.Hopper@Example.com")
    user = User.objects.get(email__iexact="grace.hopper@example.com")
    fresh = Api()
    response = _login(fresh, "GRACE.HOPPER@EXAMPLE.COM")
    assert response.status_code == 200, response.content
    assert fresh.get("/api/me").status_code == 200
    assert _actions(user).count("user.logged_in") == 2  # at signup, and now


def test_a_wrong_password_is_refused_and_not_audited_as_a_login() -> None:
    _signup(Api(), "grace@example.com")
    user = User.objects.get(email="grace@example.com")
    before = _actions(user).count("user.logged_in")
    fresh = Api()
    assert _login(fresh, "grace@example.com", "Wrong-Password-1234").status_code == 400
    assert fresh.get("/api/me").status_code == 401
    assert _actions(user).count("user.logged_in") == before


def test_logout_ends_the_session_and_is_audited() -> None:
    api = Api()
    _signup(api, "bye@example.com")
    user = User.objects.get(email="bye@example.com")
    assert api.get("/api/me").status_code == 200
    api.delete(f"{BASE}/auth/session")
    assert api.get("/api/me").status_code == 401
    assert _actions(user).count("user.logged_out") == 1


def test_logging_out_when_not_logged_in_records_nothing() -> None:
    Api().delete(f"{BASE}/auth/session")
    assert not AuditEvent.objects.filter(action="user.logged_out").exists()


def test_login_audit_records_ids_only() -> None:
    _signup(Api(), "ids@example.com")
    user = User.objects.get(email="ids@example.com")
    event = AuditEvent.objects.filter(actor=user, action="user.logged_in").first()
    assert event is not None
    assert event.target_id == str(user.pk)
    assert event.metadata == {}


def test_a_user_with_no_organization_can_log_in_without_an_audit_event() -> None:
    # Audit rows are tenant-owned; a user outside every organization has nowhere to record.
    user = make_user("loner@example.com")  # make_user's password is "pw-for-tests"
    api = Api()
    response = _login(api, user.email, "pw-for-tests")  # nosec B106
    assert response.status_code == 200, response.content
    assert api.get("/api/me").json()["memberships"] == []  # really logged in, no org
    assert not AuditEvent.objects.exists()
    # The failure twin: a wrong password is refused, so the 200 above was a real login.
    assert _login(Api(), user.email, "not-the-password-1").status_code == 400


# --- cookies ------------------------------------------------------------------------------


def test_session_cookie_is_httponly_and_samesite_lax_and_csrf_cookie_is_readable() -> (
    None
):
    client = Client(enforce_csrf_checks=True)
    client.get(CONFIG_URL)
    token = client.cookies["csrftoken"].value
    response = client.post(
        f"{BASE}/auth/signup",
        {"email": "cookie@example.com", "password": PASSWORD},
        content_type="application/json",
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 200
    session = response.cookies["sessionid"]
    assert session["httponly"] is True
    assert session["samesite"] == "Lax"
    csrf = client.cookies["csrftoken"]
    assert csrf["samesite"] == "Lax"
    assert not csrf["httponly"]  # the SPA must be able to read it


def test_prod_cookie_flags_add_secure(settings: Any) -> None:
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    client = Client()
    response = client.get(CONFIG_URL)
    assert response.cookies["csrftoken"]["secure"] is True
    client = Client(enforce_csrf_checks=False)
    signed_up = client.post(
        f"{BASE}/auth/signup",
        {"email": "sec@example.com", "password": PASSWORD},
        content_type="application/json",
    )
    assert signed_up.cookies["sessionid"]["secure"] is True


# --- passwords ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    ["Short1!", "password12345", "12345678901234"],
    ids=["too-short", "common", "numeric"],
)
# NB: UserAttributeSimilarityValidator is configured but cannot fire at *signup*: allauth
# validates the new password before it has a user object to compare against (it does on
# password change / reset, where a user exists). Recorded in plans/phase-3-3-auth.md.
def test_weak_passwords_are_refused(password: str) -> None:
    response = _signup(Api(), "ada.lovelace@example.com", password)
    assert response.status_code == 400
    assert not User.objects.exists()


def test_a_strong_password_is_accepted() -> None:
    assert (
        _signup(Api(), "ada.lovelace@example.com", "Analytical-Engine-1843").status_code
        == 200
    )


# --- rate limits --------------------------------------------------------------------------


def test_repeated_failed_logins_for_one_account_are_rate_limited() -> None:
    _signup(Api(), "victim@example.com")
    api = Api()
    # allauth answers a locked-out login with a 400 carrying a distinct error code.
    codes = [
        _error_codes(_login(api, "victim@example.com", f"Wrong-Guess-{i}-xyz"))
        for i in range(7)
    ]
    assert all("too_many_login_attempts" not in c for c in codes[:5])
    assert codes[5:] == [["too_many_login_attempts"]] * 2
    # The limit is per account, not per client: a brand-new client is locked out too, the
    # right password is refused while locked out, and another account is unaffected.
    first = _login(Api(), "victim@example.com", "Wrong-Guess-0-xyz")
    assert _error_codes(first) == ["too_many_login_attempts"]
    correct = _login(api, "victim@example.com")
    assert _error_codes(correct) == ["too_many_login_attempts"]
    _signup(Api(), "bystander@example.com")
    assert _login(Api(), "bystander@example.com").status_code == 200


def test_logins_below_the_limit_are_not_throttled() -> None:
    _signup(Api(), "patient@example.com")
    api = Api()
    for i in range(3):
        assert (
            _login(api, "patient@example.com", f"Wrong-Guess-{i}-xyz").status_code
            == 400
        )
    assert _login(api, "patient@example.com").status_code == 200


def test_signup_is_rate_limited_per_client_ip() -> None:
    # The limit is per source IP (10/m), whatever addresses are being registered.
    api = Api()
    codes = [_signup(api, f"u{i}@example.com").status_code for i in range(12)]
    assert codes[0] == 200
    assert 429 in codes
    assert codes.index(429) >= 5  # not before a human-sized burst


TWIN_DOMAIN = "victim@ｅxample.com"  # fullwidth "e": NFKC-equal to victim@example.com


def test_unicode_twin_spellings_share_one_failed_login_budget() -> None:
    _signup(Api(), "victim@example.com")
    codes = []
    for i in range(7):  # alternate spellings; the account is the same
        email = "victim@example.com" if i % 2 == 0 else TWIN_DOMAIN
        codes.append(_error_codes(_login(Api(), email, f"Wrong-Guess-{i}-xyz")))
    assert all("too_many_login_attempts" not in c for c in codes[:5])
    assert codes[5:] == [["too_many_login_attempts"]] * 2
    # Locked out under *either* spelling, even with the right password.
    assert _error_codes(_login(Api(), TWIN_DOMAIN)) == ["too_many_login_attempts"]
    assert _error_codes(_login(Api(), "victim@example.com")) == [
        "too_many_login_attempts"
    ]


def test_a_legitimate_user_under_budget_can_log_in_with_either_spelling() -> None:
    _signup(Api(), "victim@example.com")
    for i in range(2):
        assert _login(Api(), TWIN_DOMAIN, f"Wrong-Guess-{i}-xyz").status_code == 400
    assert _login(Api(), TWIN_DOMAIN).status_code == 200
    assert _login(Api(), "victim@example.com").status_code == 200


def test_the_failed_login_budget_does_not_depend_on_the_host_header() -> None:
    _signup(Api(), "victim@example.com")
    first, second = Api(), Api()
    second.client.defaults["HTTP_HOST"] = "localhost"  # allowed, but a different Host
    for i in range(3):
        _login(first, "victim@example.com", f"Wrong-Guess-{i}-xyz")
    for i in range(3, 6):
        _login(second, "victim@example.com", f"Wrong-Guess-{i}-xyz")
    assert _error_codes(_login(first, "victim@example.com")) == [
        "too_many_login_attempts"
    ]
    assert _error_codes(_login(second, "victim@example.com")) == [
        "too_many_login_attempts"
    ]


def test_host_header_variation_below_budget_still_logs_in() -> None:
    _signup(Api(), "victim@example.com")
    other = Api()
    other.client.defaults["HTTP_HOST"] = "localhost"
    assert _login(other, "victim@example.com", "Wrong-Guess-0-xyz").status_code == 400
    assert _login(other, "victim@example.com").status_code == 200


# --- duplicate signup against an account with no EmailAddress row ----------------------------


@pytest.mark.parametrize("mode", ["none", "optional", "mandatory"])
@pytest.mark.parametrize("attempt", ["twin@example.com", "TWIN@EXAMPLE.COM"])
def test_signup_over_an_account_made_without_allauth_is_not_a_500(
    settings: Any, mode: str, attempt: str
) -> None:
    # create_user / createsuperuser make a User with no EmailAddress row and a stored
    # mixed-case local part; allauth's own lookup (lower-cased, exact) would miss it and the
    # signup would die on the unique constraint instead of answering like any duplicate.
    settings.ACCOUNT_EMAIL_VERIFICATION = mode
    make_user("Twin@example.com")
    response = _signup(Api(), attempt)  # a 500 would raise here (the client re-raises)
    if mode == "mandatory":
        assert response.status_code == 401  # same as any signup: "check your mail"
        assert "verify_email" in _flow_ids(response)
    else:
        assert response.status_code == 400
        assert _error_codes(response) == ["email_taken"]
    assert User.objects.count() == 1
    assert not Organization.objects.exists()


@pytest.mark.parametrize("mode", ["none", "optional", "mandatory"])
def test_a_fresh_address_still_signs_up_in_every_verification_mode(
    settings: Any, mode: str
) -> None:
    settings.ACCOUNT_EMAIL_VERIFICATION = mode
    make_user("Twin@example.com")
    response = _signup(Api(), "someone.else@example.com")
    assert response.status_code == (401 if mode == "mandatory" else 200)
    assert User.objects.filter(email="someone.else@example.com").exists()
    assert Organization.objects.count() == 1


def test_a_duplicate_looks_like_a_fresh_signup_under_mandatory_verification(
    mandatory: None,
) -> None:
    make_user("Twin@example.com")
    duplicate = _signup(Api(), "twin@example.com")
    fresh = _signup(Api(), "fresh@example.com")
    assert duplicate.status_code == fresh.status_code == 401
    assert _flow_ids(duplicate) == _flow_ids(fresh)


# --- unicode twins ------------------------------------------------------------------------


def test_a_unicode_twin_of_an_existing_address_cannot_sign_up_and_does_not_500() -> (
    None
):
    _signup(Api(), "user@café.example")
    twin = _signup(Api(), "user@café.example")  # decomposed e + combining acute
    assert twin.status_code == 400
    assert User.objects.count() == 1


# --- mandatory verification (as in production) ----------------------------------------------


@pytest.fixture
def mandatory(settings: Any) -> None:
    settings.ACCOUNT_EMAIL_VERIFICATION = "mandatory"


def _key_from_mail(message: Any) -> str:
    match = re.search(r"/account/verify-email/(\S+)", message.body)
    assert match, message.body
    return unquote(match.group(1))  # the link carries the key percent-encoded


def _error_codes(response: Any) -> list[str]:
    return [e["code"] for e in response.json().get("errors", [])]


def _flow_ids(response: Any) -> list[str]:
    return [f["id"] for f in response.json()["data"]["flows"]]


def test_signup_under_mandatory_verification_requires_the_email_link(
    mandatory: None,
) -> None:
    api = Api()
    response = _signup(api, "newbie@example.com")
    assert response.status_code == 401
    assert "verify_email" in _flow_ids(response)
    assert api.get("/api/me").status_code == 401  # not signed in yet
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["newbie@example.com"]
    link = re.search(r"https?://\S+", str(mail.outbox[0].body))
    assert link and link.group(0).startswith(
        "http://localhost:5173/account/verify-email/"
    )


def test_the_emailed_key_verifies_the_address_and_then_login_works(
    mandatory: None,
) -> None:
    api = Api()
    _signup(api, "newbie@example.com")
    verified = api.post(
        f"{BASE}/auth/email/verify", {"key": _key_from_mail(mail.outbox[0])}
    )
    # allauth does not log in on link verification (ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION is
    # left at its secure default: a leaked link must not be a login): the address is now
    # verified and the user signs in with their password.
    assert verified.status_code == 401
    assert api.get("/api/me").status_code == 401
    assert _login(api, "newbie@example.com").status_code == 200
    assert api.get("/api/me").status_code == 200
    assert Membership.objects.filter(
        user__email="newbie@example.com", role=Role.OWNER
    ).exists()


def test_a_wrong_verification_key_is_refused(mandatory: None) -> None:
    api = Api()
    _signup(api, "newbie@example.com")
    assert (
        api.post(f"{BASE}/auth/email/verify", {"key": "not-the-key"}).status_code == 400
    )
    assert api.get("/api/me").status_code == 401


def test_an_unverified_account_cannot_log_in_but_a_verified_one_can(
    mandatory: None,
) -> None:
    _signup(Api(), "newbie@example.com")
    blocked = Api()
    response = _login(blocked, "newbie@example.com")
    assert response.status_code == 401
    assert "verify_email" in _flow_ids(response)
    assert blocked.get("/api/me").status_code == 401
    # Following the link in a *different* browser verifies the address (and logs nobody in);
    # the proof it worked is that the login which was blocked a moment ago now succeeds.
    verifier = Api()
    verified = verifier.post(
        f"{BASE}/auth/email/verify", {"key": _key_from_mail(mail.outbox[0])}
    )
    assert verified.status_code == 401
    assert verifier.get("/api/me").status_code == 401
    assert _login(Api(), "newbie@example.com").status_code == 200


def test_signing_up_with_an_existing_address_looks_the_same_as_a_new_one(
    mandatory: None,
) -> None:
    first = _signup(Api(), "taken@example.com")
    second = _signup(Api(), "taken@example.com")
    assert first.status_code == second.status_code == 401
    assert _flow_ids(first) == _flow_ids(second)
    assert User.objects.filter(email="taken@example.com").count() == 1
    assert Organization.objects.count() == 1  # and no second personal organization


def test_password_reset_does_not_reveal_whether_the_address_exists(
    mandatory: None,
) -> None:
    _signup(Api(), "known@example.com")
    mail.outbox.clear()
    known = Api().post(f"{BASE}/auth/password/request", {"email": "known@example.com"})
    unknown = Api().post(
        f"{BASE}/auth/password/request", {"email": "nobody@example.com"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_password_reset_round_trip(mandatory: None) -> None:
    api = Api()
    _signup(api, "forgetful@example.com")
    verifier = Api()
    verifier.post(f"{BASE}/auth/email/verify", {"key": _key_from_mail(mail.outbox[0])})
    mail.outbox.clear()
    assert (
        Api()
        .post(f"{BASE}/auth/password/request", {"email": "forgetful@example.com"})
        .status_code
        == 200
    )
    (message,) = mail.outbox
    key = re.search(r"/account/password/reset/key/(\S+)", str(message.body))
    assert key, message.body
    new_password = "Brand-New-Passphrase-77"  # nosec B105
    reset = Api().post(
        f"{BASE}/auth/password/reset",
        {"key": unquote(key.group(1)), "password": new_password},
    )
    # Resetting does not log in (LOGIN_ON_PASSWORD_RESET stays at its default).
    assert reset.status_code == 401, reset.content
    assert _login(Api(), "forgetful@example.com", new_password).status_code == 200
    assert _login(Api(), "forgetful@example.com", PASSWORD).status_code == 400


# --- audit filing -------------------------------------------------------------------------------


def test_login_is_filed_under_the_users_oldest_organization() -> None:
    user = make_user("two.orgs@example.com")
    oldest, newer = make_organization(), make_organization()
    Membership.objects.create(user=user, organization=oldest, role=Role.VIEWER)
    Membership.objects.create(user=user, organization=newer, role=Role.OWNER)
    Client().force_login(user)
    assert (
        AuditEvent.objects.filter(organization=oldest, action="user.logged_in").count()
        == 1
    )
    assert not AuditEvent.objects.filter(organization=newer).exists()

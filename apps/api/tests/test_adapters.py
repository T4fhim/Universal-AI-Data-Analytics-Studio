# File: apps/api/tests/test_adapters.py
"""The allauth adapters' email normalisation, on the social-login path.

Why: the database treats canonically equivalent spellings of an address as one account
(``accounts.models.normalise_email`` + the ``LOWER(email)`` constraint). The password signup
form is covered by ``AccountAdapter.clean_email``; a *provider* hands over whatever spelling
it stores, and allauth decides "is this address taken?" from the raw provider value before
the user is saved. Without normalising first, a decomposed twin of an existing address passes
that check, auto-signup proceeds, and ``user.save()`` dies on the unique constraint (a 500).
These tests drive allauth's own ``process_auto_signup`` decision, with no network.
"""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from allauth.socialaccount.internal.flows.signup import process_auto_signup
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.test import RequestFactory
from factories import make_user

from uadas_api.accounts.adapters import SocialAccountAdapter
from uadas_api.accounts.models import User

pytestmark = pytest.mark.django_db

EXISTING = "user@café.example"  # precomposed e-acute
DECOMPOSED_TWIN = "user@café.example"  # e + combining acute: the same address


def _social_login(email: str, uid: str = "1") -> SocialLogin:
    return SocialLogin(
        user=User(email=email),
        account=SocialAccount(provider="github", uid=uid),
        email_addresses=[EmailAddress(email=email, verified=True, primary=True)],
    )


def _decide(sociallogin: SocialLogin) -> bool:
    request = RequestFactory().get("/")
    SocialAccountAdapter().pre_social_login(request, sociallogin)
    auto_signup, _ = process_auto_signup(request, sociallogin)
    return bool(auto_signup)


def _existing_account() -> User:
    user = make_user(EXISTING)
    EmailAddress.objects.create(
        user=user, email=user.email.lower(), primary=True, verified=True
    )
    return user


def test_a_decomposed_twin_of_an_existing_address_is_recognised_as_taken() -> None:
    _existing_account()
    # Not auto-signed-up (so no second user is saved, no IntegrityError later).
    assert _decide(_social_login(DECOMPOSED_TWIN)) is False


def test_the_social_email_and_user_are_normalised_before_the_decision() -> None:
    sociallogin = _social_login(DECOMPOSED_TWIN)
    SocialAccountAdapter().pre_social_login(RequestFactory().get("/"), sociallogin)
    assert sociallogin.email_addresses[0].email == EXISTING.lower()
    assert sociallogin.user.email == EXISTING


def test_a_genuinely_new_social_address_is_still_auto_signed_up() -> None:
    _existing_account()
    assert _decide(_social_login("someone.new@example.com", uid="2")) is True
    # ...and the very same (precomposed) address as the existing account is also "taken".
    assert _decide(_social_login(EXISTING, uid="3")) is False

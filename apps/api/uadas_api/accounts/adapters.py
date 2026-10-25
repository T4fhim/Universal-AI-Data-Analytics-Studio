# File: apps/api/uadas_api/accounts/adapters.py
"""allauth hooks: provision a personal organization at signup, and one notion of "the same email".

Why adapters rather than a ``post_save`` / ``user_signed_up`` signal for provisioning: the
organization, its owner membership and the audit row must be created in the **same
transaction** as the user, so that a failure anywhere leaves no user without an organization.
allauth's ``user_signed_up`` signal fires *after* the user is committed, which would leave
exactly that half-finished state on a crash. ``save_user`` is the one call both signup paths go
through before anything is committed:

* password signup  -> ``AccountAdapter.save_user``
* OAuth first login -> ``SocialAccountAdapter.save_user`` (auto-signup passes no form, and
  allauth then does not call the account adapter's ``save_user`` at all, so it needs its own
  override; with a form the account adapter has already provisioned and the call is a no-op,
  see :func:`~uadas_api.accounts.services.provision_personal_organization`). Only the
  user, organization, membership and audit rows are covered by that transaction; allauth
  adds the ``EmailAddress`` row afterwards, outside it.

The second job is making every allauth decision about an email address agree with the
database, which treats canonically equivalent spellings (NFKC, ``LOWER(email)``) as one
account (``accounts.models.normalise_email``). Left to itself allauth compares raw lower-cased
strings, which opens three gaps, each closed here: a twin spelling is a *fresh* failed-login
budget (:meth:`AccountAdapter._get_login_attempts_cache_key`); a twin of an existing address
passes the signup duplicate check and dies on the unique constraint as a 500
(:meth:`AccountAdapter.clean_email`, and :meth:`SocialAccountAdapter.pre_social_login` for
providers); and a user created outside allauth (``create_user`` / ``createsuperuser``, no
``EmailAddress`` row, mixed-case local part) is invisible to allauth's lookup, which is
exact-match on the lower-cased value.

Login and logout auditing is separate (``signals.py``): those are not creations.
"""

from __future__ import annotations

from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.http import HttpRequest

from uadas_api.accounts.models import User, normalise_email
from uadas_api.accounts.services import provision_personal_organization


class AccountAdapter(DefaultAccountAdapter):
    def _get_login_attempts_cache_key(
        self, request: HttpRequest, **credentials: Any
    ) -> str:
        """Key the per-account failed-login limit on the *normalised* address, and nothing else.

        allauth's default is ``"<site domain>:<email.lower()>"``. Two flaws: a Unicode twin
        of the address (a fullwidth ``e`` in the domain) is a different string but the same account to
        the database and to ``ModelBackend``, so each spelling got a fresh budget; and the
        site domain comes from the request's ``Host`` header, so varying it did too. Using
        the NFKC-normalised, lower-cased address only makes every spelling share one budget
        and the budget independent of the Host header.
        """
        login = credentials.get("email") or credentials.get("username") or ""
        return normalise_email(str(login)).lower()

    def clean_email(self, email: str) -> str:
        """Normalise the address a user submits, and make sure allauth can *see* its owner.

        NFKC-normalising stops a Unicode twin of an existing address passing the form's
        duplicate check (it would otherwise reach the unique constraint and surface as a 500
        instead of the ordinary "already registered" answer). Registering the address of an
        existing user who has no ``EmailAddress`` row (made by ``create_user`` or
        ``createsuperuser``) fixes the other half: allauth looks users up through that table
        and, failing that, by exact match on the lower-cased address, so a stored
        ``Twin@example.com`` is otherwise invisible to a signup for ``twin@example.com``.
        """
        cleaned = normalise_email(super().clean_email(email))
        self._register_addresses_of_legacy_users(cleaned)
        return cleaned

    @staticmethod
    def _register_addresses_of_legacy_users(email: str) -> None:
        if not email:
            return
        for user in User.objects.by_email(email):
            if not EmailAddress.objects.filter(user=user).exists():
                # Unverified: nothing has proved the address belongs to anyone yet.
                EmailAddress.objects.get_or_create(
                    user=user,
                    email=email.lower(),
                    defaults={"primary": True, "verified": False},
                )

    def save_user(
        self,
        request: HttpRequest,
        user: AbstractBaseUser,
        form: Any,
        commit: bool = True,
    ) -> AbstractBaseUser:
        if not commit:
            return super().save_user(request, user, form, commit=False)
        with transaction.atomic():
            saved = super().save_user(request, user, form, commit=True)
            provision_personal_organization(saved)
        return saved


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request: HttpRequest, sociallogin: Any) -> None:
        """Normalise the provider's address before allauth decides whether it is taken.

        allauth checks ``sociallogin.email_addresses`` against existing accounts, then
        auto-signs up; the user row is saved with an NFKC-normalised email. A provider that
        reports a decomposed twin of an existing address would pass the check and then hit
        the unique constraint. Normalising both the recorded addresses and the user first
        makes the check see the existing account (allauth then refuses the auto-signup).
        """
        for address in sociallogin.email_addresses:
            address.email = normalise_email(address.email).lower()
        user = sociallogin.user
        if user is not None and user.email:
            user.email = normalise_email(user.email)
        super().pre_social_login(request, sociallogin)

    def save_user(
        self, request: HttpRequest, sociallogin: Any, form: Any = None
    ) -> AbstractBaseUser:
        with transaction.atomic():
            user = super().save_user(request, sociallogin, form)
            provision_personal_organization(user)
        return user

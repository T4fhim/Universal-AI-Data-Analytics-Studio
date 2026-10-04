# File: apps/api/tests/test_accounts_models.py
"""``User``, ``Organization`` and ``Membership``: identity, tenancy primitives and roles.

Why: these three are the allowlisted non-tenant models, so nothing in the tenant harness
covers them. The behaviours worth pinning are the ones a later auth step (3.3) will lean
on: email is the login name and is unique *regardless of case*, ids are UUIDs, a user can
belong to several organizations with a different role in each, and a role is a closed set
enforced by the database as well as by ``choices``.
"""

from __future__ import annotations

import unicodedata
import uuid

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from factories import make_organization, make_user

from uadas_api.accounts.models import Membership, Organization, Role, User
from uadas_api.tenancy import ImmutableFieldError

pytestmark = pytest.mark.django_db


# ------------------------------------------------------------------------ User


def test_auth_user_model_is_the_accounts_user() -> None:
    assert get_user_model() is User
    assert User._meta.label == "accounts.User"
    assert User.USERNAME_FIELD == "email"


def test_user_primary_key_is_a_uuid() -> None:
    user = make_user()
    assert isinstance(user.pk, uuid.UUID)
    assert isinstance(User._meta.pk, models.UUIDField)


def test_create_user_hashes_the_password_and_has_no_privileges() -> None:
    user = User.objects.create_user(
        email="ada@example.com", password="s3cret-pw"
    )  # nosec B106
    assert user.check_password("s3cret-pw")
    assert user.password != "s3cret-pw"  # nosec B105
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser


def test_create_user_without_a_password_is_unusable() -> None:
    user = User.objects.create_user(email="nopw@example.com")
    assert not user.has_usable_password()


def test_create_superuser_sets_the_privilege_flags() -> None:
    admin = User.objects.create_superuser(
        email="root@example.com", password="pw"
    )  # nosec B106
    assert admin.is_staff
    assert admin.is_superuser


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_create_superuser_refuses_to_be_downgraded(flag: str) -> None:
    with pytest.raises(ValueError, match=flag):
        User.objects.create_superuser(
            email="x@example.com", password="pw", **{flag: False}
        )  # nosec B106


@pytest.mark.parametrize("email", ["", "   "])
def test_create_user_requires_an_email(email: str) -> None:
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user(email=email, password="pw")  # nosec B106


def test_email_uniqueness_ignores_case() -> None:
    User.objects.create_user(email="Grace@Example.com", password="pw")  # nosec B106
    # create_user validates first, so the friendly error comes from full_clean ...
    for twin in ("grace@example.com", "GRACE@EXAMPLE.COM"):
        with pytest.raises(ValidationError):
            User.objects.create_user(email=twin, password="pw")  # nosec B106
        # ... and the database constraint is the backstop when validation is bypassed
        with pytest.raises(IntegrityError), transaction.atomic():
            User(email=twin).save()


@pytest.mark.parametrize(
    "bad", ["no-at-sign", "two@@signs.com", "spaces in@example.com", "@example.com"]
)
def test_create_user_rejects_a_malformed_email(bad: str) -> None:
    with pytest.raises(ValidationError):
        User.objects.create_user(email=bad, password="pw")  # nosec B106
    with pytest.raises(ValidationError):
        User.objects.create_superuser(email=bad, password="pw")  # nosec B106
    assert not User.objects.filter(email=bad).exists()


def test_email_is_nfkc_normalised_so_unicode_twins_cannot_coexist() -> None:
    # Django's validator only admits ASCII local parts, so the twins live in the domain.
    composed = unicodedata.normalize("NFC", "user@caf\u00e9.example")
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    first = User.objects.create_user(email=composed, password="pw")  # nosec B106
    assert first.email == composed
    with pytest.raises(ValidationError):
        User.objects.create_user(email=decomposed, password="pw")  # nosec B106
    with pytest.raises(IntegrityError), transaction.atomic():
        User(email=decomposed).save()  # save() normalises too, so this is the same row
    assert User.objects.count() == 1


def test_compatibility_forms_are_folded() -> None:
    user = User.objects.create_user(
        email="ＡＢＣ@ｅｘａｍｐｌｅ.com",
        password="pw",  # nosec B106
    )
    assert user.email == "ABC@example.com"


def test_save_normalises_an_email_changed_after_creation() -> None:
    user = make_user("plain@example.com")
    user.email = "Café@Example.COM"
    user.save()
    assert User.objects.get(pk=user.pk).email == "Café@example.com"


def test_clean_normalises_the_email() -> None:
    decomposed = unicodedata.normalize("NFD", "caf\u00e9@example.com")
    user = User(email=decomposed)
    user.clean()
    assert user.email == unicodedata.normalize("NFC", decomposed) != decomposed


def test_natural_key_lookup_filters_on_lower_of_the_column() -> None:
    """``email__iexact`` compiles to ``UPPER(col)`` on Postgres and misses the index."""
    sql = str(User.objects.by_email("Anyone@Example.com").query)
    assert 'LOWER("accounts_user"."email")' in sql
    assert "UPPER(" not in sql.upper()


def test_natural_key_lookup_agrees_with_the_unicode_normalisation() -> None:
    composed = unicodedata.normalize("NFC", "user@caf\u00e9.example")
    decomposed = unicodedata.normalize("NFD", composed).upper()  # case too
    user = User.objects.create_user(email=composed, password="pw")  # nosec B106
    assert User.objects.get_by_natural_key(decomposed) == user
    assert authenticate(username=decomposed, password="pw") == user  # nosec B106


def test_natural_key_lookup_of_an_unknown_user_raises_does_not_exist() -> None:
    with pytest.raises(User.DoesNotExist):
        User.objects.get_by_natural_key("nobody@example.com")


def test_email_is_stored_as_given_apart_from_the_domain() -> None:
    user = User.objects.create_user(
        email="MixedCase@EXAMPLE.com", password="pw"
    )  # nosec B106
    assert user.email == "MixedCase@example.com"


def test_lookup_by_natural_key_ignores_case() -> None:
    user = User.objects.create_user(
        email="Alan@Example.com", password="pw"
    )  # nosec B106
    assert User.objects.get_by_natural_key("alan@example.com") == user
    assert User.objects.get_by_natural_key("ALAN@EXAMPLE.COM") == user


def test_authenticate_accepts_any_case_of_the_email() -> None:
    user = User.objects.create_user(
        email="Edsger@Example.com", password="correct-horse"
    )  # nosec B106
    assert (
        authenticate(username="edsger@example.com", password="correct-horse") == user
    )  # nosec B106
    assert (
        authenticate(username="edsger@example.com", password="wrong") is None
    )  # nosec B106


def test_user_str_is_the_email() -> None:
    assert str(make_user("who@example.com")) == "who@example.com"


# ---------------------------------------------------------------- Organization


def test_organization_primary_key_is_a_uuid_and_str_is_its_name() -> None:
    org = Organization.objects.create(name="Acme Analytics", slug="acme")
    assert isinstance(org.pk, uuid.UUID)
    assert str(org) == "Acme Analytics"
    assert org.created_at is not None


def test_organization_slug_is_unique() -> None:
    Organization.objects.create(name="One", slug="same")
    with pytest.raises(IntegrityError), transaction.atomic():
        Organization.objects.create(name="Two", slug="same")


# ------------------------------------------------------------------ Membership


def test_roles_are_the_four_expected_values() -> None:
    assert [r.value for r in Role] == ["owner", "admin", "editor", "viewer"]


def test_membership_links_a_user_to_an_organization_with_a_role() -> None:
    user, org = make_user(), make_organization()
    membership = Membership.objects.create(
        user=user, organization=org, role=Role.EDITOR
    )
    assert isinstance(membership.pk, uuid.UUID)
    assert membership.role == "editor"
    assert list(user.memberships.all()) == [membership]
    assert list(org.memberships.all()) == [membership]


def test_membership_is_unique_per_user_and_organization() -> None:
    user, org = make_user(), make_organization()
    Membership.objects.create(user=user, organization=org, role=Role.VIEWER)
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=user, organization=org, role=Role.OWNER)


def test_a_user_can_hold_a_different_role_in_each_organization() -> None:
    user = make_user()
    org_a, org_b = make_organization(), make_organization()
    Membership.objects.create(user=user, organization=org_a, role=Role.OWNER)
    Membership.objects.create(user=user, organization=org_b, role=Role.VIEWER)
    roles = dict(user.memberships.values_list("organization_id", "role"))
    assert roles == {org_a.pk: "owner", org_b.pk: "viewer"}


def test_many_users_can_share_one_organization() -> None:
    org = make_organization()
    for role in Role:
        Membership.objects.create(user=make_user(), organization=org, role=role)
    assert org.memberships.count() == len(Role)


def test_role_is_a_closed_set_enforced_by_the_database() -> None:
    user, org = make_user(), make_organization()
    with pytest.raises(IntegrityError), transaction.atomic():
        Membership.objects.create(user=user, organization=org, role="superhero")


def test_deleting_a_user_removes_their_memberships_but_not_the_organization() -> None:
    user, org = make_user(), make_organization()
    Membership.objects.create(user=user, organization=org, role=Role.OWNER)
    user.delete()
    assert not Membership.objects.filter(organization=org).exists()
    assert Organization.objects.filter(pk=org.pk).exists()


def test_deleting_an_organization_removes_its_memberships_but_not_the_users() -> None:
    user, org = make_user(), make_organization()
    Membership.objects.create(user=user, organization=org, role=Role.OWNER)
    org.delete()
    assert User.objects.filter(pk=user.pk).exists()
    assert not Membership.objects.filter(user=user).exists()


# ------------------------------------------- Membership: user/organization are fixed


def _membership() -> Membership:
    return Membership.objects.create(
        user=make_user(), organization=make_organization(), role=Role.EDITOR
    )


def test_a_membership_cannot_be_moved_to_another_user_or_organization() -> None:
    membership = _membership()
    other_user, other_org = make_user(), make_organization()
    original = (membership.user_id, membership.organization_id)

    membership.user = other_user
    with pytest.raises(ImmutableFieldError):
        membership.save()
    membership.refresh_from_db()
    membership.organization = other_org
    with pytest.raises(ImmutableFieldError):
        membership.save()

    stored = Membership.objects.get(pk=membership.pk)
    assert (stored.user_id, stored.organization_id) == original


def test_a_membership_cannot_be_moved_after_a_deferred_load() -> None:
    membership = _membership()
    loaded = Membership.objects.only("role").get(pk=membership.pk)
    loaded.user_id = make_user().pk
    with pytest.raises(ImmutableFieldError):
        loaded.save()
    assert Membership.objects.get(pk=membership.pk).user_id == membership.user_id


def test_queryset_update_and_bulk_update_cannot_move_a_membership() -> None:
    membership = _membership()
    other_user, other_org = make_user(), make_organization()
    qs = Membership.objects.filter(pk=membership.pk)
    for kwargs in (
        {"user": other_user},
        {"user_id": other_user.pk},
        {"organization": other_org},
        {"organization_id": other_org.pk},
    ):
        with pytest.raises(ImmutableFieldError):
            qs.update(**kwargs)
    membership.user = other_user
    with pytest.raises(ImmutableFieldError):
        Membership.objects.bulk_update([membership], ["user"])
    stored = Membership.objects.get(pk=membership.pk)
    assert stored.user_id != other_user.pk


def test_related_manager_add_cannot_move_a_membership() -> None:
    membership = _membership()
    with pytest.raises(ImmutableFieldError):
        make_user().memberships.add(membership)
    with pytest.raises(ImmutableFieldError):
        make_organization().memberships.add(membership)


def test_the_base_manager_of_membership_is_guarded() -> None:
    assert Membership._meta.base_manager_name == "objects"
    membership = _membership()
    with pytest.raises(ImmutableFieldError):
        Membership._base_manager.filter(pk=membership.pk).update(user=make_user())


def test_a_membership_role_can_still_change() -> None:
    membership = _membership()
    membership.role = Role.ADMIN
    membership.save()
    assert Membership.objects.filter(pk=membership.pk).update(role=Role.VIEWER) == 1
    membership.refresh_from_db()
    membership.role = Role.OWNER
    Membership.objects.bulk_update([membership], ["role"])
    assert Membership.objects.get(pk=membership.pk).role == "owner"

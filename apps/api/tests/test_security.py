# File: apps/api/tests/test_security.py
"""``require_membership``: the one gate every organization-scoped route passes through.

Why: org selection is path-based and stateless (``/api/organizations/{org_id}/...``), so
authorization is decided per request by looking up the caller's membership. The contract,
pinned here: unauthenticated -> 401; authenticated non-member -> 404 (never 403: the
response must not reveal whether the organization exists); a member below the required role
-> 403; otherwise the :class:`Membership` is returned. Each refusal is paired with the
positive case on the same fixtures so the helper cannot pass by refusing everything.
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from django.test import RequestFactory
from factories import make_organization, make_user
from ninja.errors import HttpError

from uadas_api.accounts.models import Membership, Role, User
from uadas_api.accounts.permissions import ROLE_ORDER, role_rank
from uadas_api.accounts.security import require_membership

pytestmark = pytest.mark.django_db


def _request(user: User | AnonymousUser) -> HttpRequest:
    request = RequestFactory().get("/")
    request.user = user
    return request


def _join(role: Role) -> tuple[User, Membership]:
    org = make_organization()
    user = make_user()
    return user, Membership.objects.create(user=user, organization=org, role=role)


def test_unauthenticated_is_401() -> None:
    with pytest.raises(HttpError) as exc:
        require_membership(_request(AnonymousUser()), make_organization().pk)
    assert exc.value.status_code == 401


def test_a_member_gets_their_membership_back() -> None:
    user, membership = _join(Role.VIEWER)
    got = require_membership(_request(user), membership.organization_id)
    assert got.pk == membership.pk
    assert got.role == Role.VIEWER
    assert got.organization_id == membership.organization_id


def test_a_non_member_gets_404_even_for_an_organization_that_exists() -> None:
    _, membership = _join(Role.OWNER)
    outsider = make_user()
    with pytest.raises(HttpError) as exc:
        require_membership(_request(outsider), membership.organization_id)
    assert exc.value.status_code == 404


def test_404_is_identical_for_an_existing_and_a_nonexistent_organization() -> None:
    _, membership = _join(Role.OWNER)
    outsider = make_user()
    errors = []
    for org_id in (membership.organization_id, uuid.uuid4()):
        with pytest.raises(HttpError) as exc:
            require_membership(_request(outsider), org_id)
        errors.append((exc.value.status_code, str(exc.value.message)))
    assert errors[0] == errors[1]


def test_membership_in_another_organization_does_not_count() -> None:
    user, mine = _join(Role.OWNER)
    theirs = make_organization()
    assert require_membership(_request(user), mine.organization_id).pk == mine.pk
    with pytest.raises(HttpError) as exc:
        require_membership(_request(user), theirs.pk)
    assert exc.value.status_code == 404


@pytest.mark.parametrize("have", ROLE_ORDER)
@pytest.mark.parametrize("need", ROLE_ORDER)
def test_the_role_threshold(have: Role, need: Role) -> None:
    user, membership = _join(have)
    request = _request(user)
    if role_rank(have) >= role_rank(need):
        assert (
            require_membership(request, membership.organization_id, need).pk
            == membership.pk
        )
    else:
        with pytest.raises(HttpError) as exc:
            require_membership(request, membership.organization_id, need)
        assert exc.value.status_code == 403


def test_the_default_minimum_is_viewer() -> None:
    user, membership = _join(Role.VIEWER)
    assert (
        require_membership(_request(user), membership.organization_id).pk
        == membership.pk
    )


def test_an_inactive_user_is_not_a_member_request() -> None:
    # Django's auth middleware never yields an inactive user as request.user, but the
    # helper must not rely on that: a deactivated account is refused outright.
    user, membership = _join(Role.OWNER)
    user.is_active = False
    user.save()
    with pytest.raises(HttpError) as exc:
        require_membership(_request(user), membership.organization_id)
    assert exc.value.status_code == 401

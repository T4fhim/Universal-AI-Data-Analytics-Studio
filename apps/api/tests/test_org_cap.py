# File: apps/api/tests/test_org_cap.py
"""The per-user cap on owned organizations holds under concurrency.

Why: ``create_organization`` counts a user's owned organizations and then inserts one. Two
requests racing from the same account would both count "below the cap" and both insert, so
the count is taken under a row lock on the creating *user* (``select_for_update``). The
sequential behaviour is covered in ``test_accounts_api.py``; this file proves the race, which
needs real row locks (PostgreSQL; SQLite serialises writers, so the race cannot occur there).

Known and accepted: a user can still leave an organization and be promoted owner of another
to hold more than the cap -- the cap limits *creation*, not ownership by invitation.
"""

from __future__ import annotations

import threading

import pytest
from django.db import connection, connections
from factories import make_user

from uadas_api.accounts import services
from uadas_api.accounts.models import Membership, Role


@pytest.mark.django_db(transaction=True)
def test_concurrent_creations_cannot_exceed_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("row locks are a PostgreSQL behaviour; CI's api-test job runs this")
    monkeypatch.setattr(services, "MAX_OWNED_ORGANIZATIONS", 1)
    user = make_user("busy@example.com")
    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def create(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            try:
                services.create_organization(f"Racer {index}", user)
                outcomes.append("created")
            except services.OrganizationLimitError:
                outcomes.append("refused")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=create, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(outcomes) == ["created", "refused", "refused", "refused"]
    assert Membership.objects.filter(user=user, role=Role.OWNER).count() == 1


@pytest.mark.django_db
def test_the_cap_still_allows_creation_below_it_and_other_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services, "MAX_OWNED_ORGANIZATIONS", 1)
    first, second = make_user("a@example.com"), make_user("b@example.com")
    services.create_organization("One", first)
    with pytest.raises(services.OrganizationLimitError):
        services.create_organization("Two", first)
    services.create_organization("Other user's", second)  # unaffected
    # A personal organization (created at signup) is exempt from the check itself.
    third = make_user("c@example.com")
    services.create_organization("Personal", third, personal=True)
    services.create_organization("Personal again", third, personal=True)

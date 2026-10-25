# File: apps/api/tests/test_web_streams.py
"""Concurrent-stream caps (3.7): counted per user and per organization, released exactly once.

Why: a cap that leaks a slot on one exit path eventually locks a user out of streaming; a cap that
double-releases lets a user open more than the limit. So the lease is exercised through acquire,
release, a second release, the refused case (which must hold nothing) and a cache outage (which
must refuse, not bypass). The positive twin of every refusal is the same call just under the cap.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.core.cache import cache
from django.db import connection

from uadas_api.web import streams
from uadas_api.web.errors import ApiError

ORG, OTHER_ORG = uuid.uuid4(), uuid.uuid4()
USER, OTHER_USER = uuid.uuid4(), uuid.uuid4()


def _take(
    user: uuid.UUID = USER, org: uuid.UUID = ORG, **caps: int
) -> streams.StreamLease:
    caps = {"user_cap": 2, "org_cap": 3, **caps}
    return streams.acquire("job", user, org, max_seconds=60, **caps)


def test_a_user_can_hold_up_to_the_cap_and_one_more_is_a_429() -> None:
    held = [_take(), _take()]
    with pytest.raises(ApiError) as refused:
        _take()
    assert refused.value.status_code == 429
    held[0].release()
    _take()  # the twin: a freed slot is usable again


def test_a_refused_attempt_holds_nothing() -> None:
    a, b = _take(), _take()
    for _ in range(5):
        with pytest.raises(ApiError):
            _take()
    a.release()
    b.release()
    # five refusals left no residue: the user's slots and the organization's are all free again
    leases = [_take(user_cap=3, org_cap=3) for _ in range(3)]
    assert len(leases) == 3


def test_release_is_idempotent_so_two_exit_paths_cannot_double_free() -> None:
    first, second = _take(), _take()
    first.release()
    first.release()
    first.release()
    with pytest.raises(
        ApiError
    ):  # still one held + this = the cap is 2, so the third is refused
        _take(), _take()
    second.release()


def test_the_organization_cap_is_shared_by_its_users_and_is_independent_of_other_organizations() -> (
    None
):
    users = [uuid.uuid4() for _ in range(3)]
    held = [_take(user, user_cap=5, org_cap=3) for user in users]
    with pytest.raises(ApiError) as refused:
        _take(uuid.uuid4(), user_cap=5, org_cap=3)
    assert refused.value.status_code == 429
    _take(
        uuid.uuid4(), OTHER_ORG, user_cap=5, org_cap=3
    )  # another organization is unaffected
    held[0].release()
    _take(uuid.uuid4(), user_cap=5, org_cap=3)  # the twin: a freed organization slot


def test_the_user_cap_is_per_organization_and_per_kind() -> None:
    _take(), _take()
    _take(org=OTHER_ORG)  # the same user in another organization
    _take(OTHER_USER)  # another user in the same organization
    streams.acquire(
        "assistant", USER, ORG, user_cap=1, org_cap=1, max_seconds=60
    )  # another kind


def test_a_cache_outage_refuses_with_503_and_holds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("redis is down")

    monkeypatch.setattr(cache, "incr", boom)
    with pytest.raises(ApiError) as refused:
        _take()
    assert refused.value.status_code == 503
    monkeypatch.undo()
    _take(), _take()  # nothing leaked by the failed attempt: both slots are free


def test_a_counter_that_expired_does_not_break_release_or_acquire() -> None:
    lease = _take()
    cache.clear()  # every counter expires at once
    lease.release()  # nothing to give back: must not raise
    _take(), _take()


@pytest.mark.django_db
def test_release_connections_closes_an_idle_connection_but_never_inside_a_transaction() -> (
    None
):
    connection.ensure_connection()
    assert connection.connection is not None
    # the test itself runs in a transaction (django_db): the helper must leave it alone
    streams.release_connections()
    assert connection.connection is not None and connection.in_atomic_block

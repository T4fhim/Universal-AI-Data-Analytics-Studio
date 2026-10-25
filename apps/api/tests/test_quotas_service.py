# File: apps/api/tests/test_quotas_service.py
"""The quota service: reserve, charge, release -- exact at the limit, idempotent, race-free.

Why: a quota that can be overshot by two concurrent requests, double-billed by a retry, or leaked
by a failure is worse than none (it refuses honest users and admits dishonest ones). Each guard here
has a positive twin -- the nearest case that must still be *allowed* -- so a service that refused
everything could not pass. The threaded test at the bottom needs real row locks (PostgreSQL;
SQLite serialises writers, so the race cannot occur there) and runs in CI's ``api-test`` job.
"""

from __future__ import annotations

import datetime
import threading
from typing import Any

import pytest
from django.db import connection, connections
from factories import factory_for, make_organization

from uadas_api.accounts.models import Organization
from uadas_api.quotas import service
from uadas_api.quotas.choices import STANDING_PERIOD, UsageKind
from uadas_api.quotas.errors import QuotaExceededError
from uadas_api.quotas.models import OrganizationQuota, UsageCounter, UsageLedger
from uadas_api.workspaces.models import DatasetRecord

ROWS = UsageKind.ROWS.value
BYTES = UsageKind.STORAGE_BYTES.value
SECONDS = UsageKind.JOB_SECONDS.value
TOKENS = UsageKind.LLM_TOKENS.value

OCTOBER = datetime.datetime(2026, 10, 25, 12, 0, tzinfo=datetime.UTC)
NOVEMBER = datetime.datetime(2026, 11, 2, 9, 0, tzinfo=datetime.UTC)


@pytest.fixture
def limits(settings: Any) -> Any:
    """Set the deployment default for some kinds, e.g. ``limits(rows=10)``."""

    def apply(**by_kind: int | None) -> None:
        settings.UADAS_QUOTA = {
            **settings.UADAS_QUOTA,
            **{f"max_{kind}": value for kind, value in by_kind.items()},
        }

    return apply


@pytest.fixture
def org() -> Organization:
    return make_organization()


def used(
    organization: Organization, kind: str, now: datetime.datetime | None = None
) -> int:
    return service.usage_for(organization, kind, now=now)


# ----------------------------------------------------------------- reserve: the limit


@pytest.mark.django_db
def test_a_reservation_exactly_at_the_limit_is_allowed(
    org: Organization, limits: Any
) -> None:
    limits(rows=10)
    result = service.reserve(org, ROWS, 10, "a")
    assert result.applied is True
    assert used(org, ROWS) == 10


@pytest.mark.django_db
def test_one_over_the_limit_is_refused_and_leaves_nothing_behind(
    org: Organization, limits: Any
) -> None:
    limits(rows=10)
    with pytest.raises(QuotaExceededError) as raised:
        service.reserve(org, ROWS, 11, "a")
    assert raised.value.kind == ROWS
    assert used(org, ROWS) == 0
    # The refused charge's ledger row was rolled back with it: the key is free to use again.
    assert not UsageLedger.objects.for_organization(org).filter(source_key="a").exists()
    assert service.reserve(org, ROWS, 10, "a").applied is True


@pytest.mark.django_db
def test_reservations_add_up_to_the_limit_and_the_next_one_is_refused(
    org: Organization, limits: Any
) -> None:
    limits(storage_bytes=100)
    service.reserve(org, BYTES, 60, "a")
    service.reserve(org, BYTES, 40, "b")  # 60 + 40 == 100: exactly full
    assert used(org, BYTES) == 100
    with pytest.raises(QuotaExceededError):
        service.reserve(org, BYTES, 1, "c")
    assert used(org, BYTES) == 100


@pytest.mark.django_db
def test_a_zero_amount_reservation_fits_even_when_full(
    org: Organization, limits: Any
) -> None:
    limits(rows=5)
    service.reserve(org, ROWS, 5, "a")
    assert service.reserve(org, ROWS, 0, "empty").applied is True


@pytest.mark.django_db
def test_no_limit_means_unlimited_but_usage_is_still_counted(org: Organization) -> None:
    service.reserve(org, ROWS, 10**12, "a")
    assert used(org, ROWS) == 10**12
    assert service.remaining(org, ROWS) is None


@pytest.mark.django_db
def test_the_limit_is_per_organization(org: Organization, limits: Any) -> None:
    other = make_organization()
    limits(rows=10)
    service.reserve(org, ROWS, 10, "a")
    # The other organization's own allowance is untouched by org's usage.
    assert service.reserve(other, ROWS, 10, "a").applied is True
    assert used(other, ROWS) == 10 and used(org, ROWS) == 10


@pytest.mark.django_db
def test_an_organization_override_beats_the_deployment_default(
    org: Organization, limits: Any
) -> None:
    limits(rows=10)
    OrganizationQuota.objects.create(organization=org, kind=ROWS, limit=3)
    with pytest.raises(QuotaExceededError):
        service.reserve(org, ROWS, 4, "a")
    assert service.reserve(org, ROWS, 3, "a").applied is True
    # ... and a larger override lifts a smaller default (the positive twin).
    bigger = make_organization()
    OrganizationQuota.objects.create(organization=bigger, kind=ROWS, limit=50)
    assert service.reserve(bigger, ROWS, 50, "a").applied is True


@pytest.mark.django_db
def test_an_override_for_one_kind_leaves_the_other_kinds_on_the_default(
    org: Organization, limits: Any
) -> None:
    limits(rows=10, storage_bytes=10)
    OrganizationQuota.objects.create(organization=org, kind=ROWS, limit=1000)
    assert service.limit_for(org, ROWS) == 1000
    assert service.limit_for(org, BYTES) == 10
    assert service.limit_for(org, TOKENS) is None


# ------------------------------------------------------------------ reserve: idempotency


@pytest.mark.django_db
def test_replaying_a_source_key_adds_nothing(org: Organization, limits: Any) -> None:
    limits(rows=10)
    first = service.reserve(org, ROWS, 4, "same")
    again = service.reserve(org, ROWS, 4, "same")
    assert (first.applied, again.applied) == (True, False)
    assert used(org, ROWS) == 4
    assert (
        UsageLedger.objects.for_organization(org).filter(source_key="same").count() == 1
    )


@pytest.mark.django_db
def test_a_replay_is_not_refused_even_when_the_organization_is_now_full(
    org: Organization, limits: Any
) -> None:
    limits(rows=10)
    service.reserve(org, ROWS, 4, "mine")
    service.reserve(org, ROWS, 6, "someone-else")  # now exactly full
    assert (
        service.reserve(org, ROWS, 4, "mine").applied is False
    )  # my share is already held
    with pytest.raises(QuotaExceededError):  # while a *new* key is refused (the twin)
        service.reserve(org, ROWS, 1, "new")


@pytest.mark.django_db
def test_the_same_key_for_a_different_kind_is_a_different_charge(
    org: Organization,
) -> None:
    service.reserve(org, ROWS, 1, "k")
    assert service.reserve(org, BYTES, 1, "k").applied is True


@pytest.mark.django_db
def test_the_same_key_in_another_organization_is_a_different_charge(
    org: Organization,
) -> None:
    service.reserve(org, ROWS, 1, "k")
    assert service.reserve(make_organization(), ROWS, 1, "k").applied is True


# --------------------------------------------------------------------------- release


@pytest.mark.django_db
def test_release_gives_the_amount_back_and_lets_another_charge_fit(
    org: Organization, limits: Any
) -> None:
    limits(storage_bytes=10)
    service.reserve(org, BYTES, 10, "upload-1")
    with pytest.raises(QuotaExceededError):
        service.reserve(org, BYTES, 1, "upload-2")
    assert service.release(org, BYTES, "upload-1") is True
    assert used(org, BYTES) == 0
    assert service.reserve(org, BYTES, 10, "upload-2").applied is True


@pytest.mark.django_db
def test_release_is_idempotent_and_never_subtracts_twice(org: Organization) -> None:
    service.reserve(org, BYTES, 5, "a")
    service.reserve(org, BYTES, 7, "b")
    assert service.release(org, BYTES, "a") is True
    assert service.release(org, BYTES, "a") is False
    assert used(org, BYTES) == 7  # b's share is untouched


@pytest.mark.django_db
def test_releasing_a_key_that_was_never_charged_is_a_no_op(org: Organization) -> None:
    service.reserve(org, BYTES, 5, "a")
    assert service.release(org, BYTES, "nope") is False
    assert used(org, BYTES) == 5


@pytest.mark.django_db
def test_a_released_key_can_be_reserved_again_and_is_charged_anew(
    org: Organization, limits: Any
) -> None:
    limits(rows=10)
    service.reserve(org, ROWS, 10, "a")
    service.release(org, ROWS, "a")
    assert service.reserve(org, ROWS, 10, "a").applied is True
    assert used(org, ROWS) == 10
    assert (
        service.reserve(org, ROWS, 10, "a").applied is False
    )  # and then it is a replay again


@pytest.mark.django_db
def test_a_revived_key_still_respects_the_limit(org: Organization, limits: Any) -> None:
    limits(rows=10)
    service.reserve(org, ROWS, 6, "a")
    service.release(org, ROWS, "a")
    service.reserve(org, ROWS, 8, "b")
    with pytest.raises(QuotaExceededError):
        service.reserve(org, ROWS, 6, "a")  # 8 + 6 > 10
    # The refused revival rolled back: the key is still released, not half-charged.
    assert (
        UsageLedger.objects.for_organization(org).get(source_key="a").released is True
    )
    assert used(org, ROWS) == 8


@pytest.mark.django_db
def test_rekey_renames_a_charge_and_refuses_a_taken_name(org: Organization) -> None:
    service.reserve(org, BYTES, 5, "hold")
    assert service.rekey(org, BYTES, "hold", "upload:final") is True
    assert (
        service.release(org, BYTES, "upload:final") is True
    )  # reachable by its new name
    service.reserve(org, BYTES, 5, "hold-2")
    service.reserve(org, BYTES, 5, "taken")
    assert service.rekey(org, BYTES, "hold-2", "taken") is False
    assert service.rekey(org, BYTES, "missing", "elsewhere") is False


# ------------------------------------------------------------------------- charge


@pytest.mark.django_db
def test_charge_is_never_refused_but_the_next_check_is(
    org: Organization, limits: Any
) -> None:
    limits(job_seconds=100)
    service.assert_available(org, SECONDS)  # nothing used yet
    service.charge(org, SECONDS, 90, "job:1:1")
    service.assert_available(org, SECONDS)  # 90 < 100: still room for new work
    service.charge(org, SECONDS, 60, "job:2:1")  # past the limit, recorded in full
    assert used(org, SECONDS) == 150
    with pytest.raises(QuotaExceededError) as raised:
        service.assert_available(org, SECONDS)
    assert raised.value.kind == SECONDS


@pytest.mark.django_db
def test_charge_is_idempotent_per_key(org: Organization) -> None:
    assert service.charge(org, SECONDS, 30, "job:1:1").applied is True
    assert service.charge(org, SECONDS, 30, "job:1:1").applied is False
    assert used(org, SECONDS) == 30
    assert (
        service.charge(org, SECONDS, 30, "job:1:2").applied is True
    )  # the next attempt
    assert used(org, SECONDS) == 60


@pytest.mark.django_db
def test_assert_available_passes_without_a_limit_and_with_room(
    org: Organization, limits: Any
) -> None:
    service.charge(org, TOKENS, 10**9, "t")
    service.assert_available(org, TOKENS)  # unlimited
    limits(llm_tokens=10**9 + 1)
    service.assert_available(org, TOKENS)  # one token left is room


@pytest.mark.django_db
def test_remaining_counts_down_and_stops_at_zero(
    org: Organization, limits: Any
) -> None:
    limits(llm_tokens=100)
    assert service.remaining(org, TOKENS) == 100
    service.charge(org, TOKENS, 30, "a")
    assert service.remaining(org, TOKENS) == 70
    service.charge(org, TOKENS, 200, "b")
    assert service.remaining(org, TOKENS) == 0


# ------------------------------------------------------------------------- windows


@pytest.mark.django_db
def test_monthly_usage_starts_again_in_a_new_month(
    org: Organization, limits: Any
) -> None:
    limits(job_seconds=100)
    service.charge(org, SECONDS, 100, "oct", now=OCTOBER)
    with pytest.raises(QuotaExceededError):
        service.assert_available(org, SECONDS, now=OCTOBER)
    service.assert_available(org, SECONDS, now=NOVEMBER)  # a fresh month: nothing used
    assert used(org, SECONDS, now=NOVEMBER) == 0
    assert used(org, SECONDS, now=OCTOBER) == 100  # October's is kept


@pytest.mark.django_db
def test_standing_usage_does_not_roll_over(org: Organization, limits: Any) -> None:
    limits(rows=10)
    service.reserve(org, ROWS, 10, "a", now=OCTOBER)
    with pytest.raises(QuotaExceededError):
        service.reserve(org, ROWS, 1, "b", now=NOVEMBER)
    assert (
        UsageCounter.objects.for_organization(org).get(kind=ROWS).period_start
        == STANDING_PERIOD
    )


@pytest.mark.django_db
def test_releasing_a_past_months_charge_gives_back_that_months_window(
    org: Organization,
) -> None:
    service.charge(org, SECONDS, 40, "oct", now=OCTOBER)
    service.charge(org, SECONDS, 5, "nov", now=NOVEMBER)
    assert service.release(org, SECONDS, "oct", now=NOVEMBER) is True
    assert used(org, SECONDS, now=OCTOBER) == 0
    assert used(org, SECONDS, now=NOVEMBER) == 5


# ----------------------------------------------------------------------- arguments


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("kind", "amount", "key"),
    [
        ("nonsense", 1, "k"),
        (ROWS, -1, "k"),
        (ROWS, True, "k"),
        (ROWS, 1.5, "k"),
        (ROWS, 1, ""),
        (ROWS, 1, "k" * 161),
    ],
)
def test_bad_arguments_are_refused(
    org: Organization, kind: str, amount: Any, key: str
) -> None:
    with pytest.raises(ValueError, match=r"usage|source key|kind"):
        service.reserve(org, kind, amount, key)
    assert used(org, ROWS) == 0
    assert (
        service.reserve(org, ROWS, 1, "k" * 160).applied is True
    )  # the longest valid key


# ------------------------------------------------- a deleted dataset gives its share back


def _charged_dataset(org: Organization) -> DatasetRecord:
    dataset = factory_for(DatasetRecord).create(org)
    service.charge(org, ROWS, 100, service.rows_key(dataset.pk))
    service.reserve(org, BYTES, 1000, service.upload_key(dataset.pk))
    return dataset


@pytest.mark.django_db
def test_deleting_a_dataset_releases_its_rows_and_bytes_and_only_its_own(
    org: Organization,
) -> None:
    doomed, kept = _charged_dataset(org), _charged_dataset(org)
    assert (used(org, ROWS), used(org, BYTES)) == (200, 2000)
    doomed.delete()
    assert (used(org, ROWS), used(org, BYTES)) == (100, 1000)
    kept.refresh_from_db()  # the other dataset is untouched and still held
    assert service.release(org, ROWS, service.rows_key(kept.pk)) is True


@pytest.mark.django_db
def test_deleting_a_dataset_that_was_never_charged_changes_nothing(
    org: Organization,
) -> None:
    held = _charged_dataset(org)
    factory_for(DatasetRecord).create(org).delete()  # e.g. a derived (cleaning) dataset
    assert (used(org, ROWS), used(org, BYTES)) == (100, 1000)
    assert held.pk is not None


# ---------------------------------------------------------------------- the race


@pytest.mark.django_db(transaction=True)
def test_concurrent_reservations_cannot_overshoot_the_limit(limits: Any) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("row locks are a PostgreSQL behaviour; CI's api-test job runs this")
    limits(rows=5)
    organization = make_organization()
    threads_n = 12
    barrier = threading.Barrier(threads_n)
    outcomes: list[str] = []

    def reserve(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            try:
                service.reserve(organization, ROWS, 1, f"racer-{index}")
                outcomes.append("held")
            except QuotaExceededError:
                outcomes.append("refused")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=reserve, args=(i,)) for i in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(outcomes) == ["held"] * 5 + ["refused"] * (threads_n - 5)
    assert used(organization, ROWS) == 5  # exactly the limit: never one over
    assert (
        UsageLedger.objects.for_organization(organization).count() == 5
    )  # refusals left no row


@pytest.mark.django_db(transaction=True)
def test_concurrent_replays_of_one_key_charge_once(limits: Any) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("row locks are a PostgreSQL behaviour; CI's api-test job runs this")
    organization = make_organization()
    threads_n = 8
    barrier = threading.Barrier(threads_n)
    applied: list[bool] = []

    def charge() -> None:
        try:
            barrier.wait(timeout=10)
            applied.append(service.charge(organization, SECONDS, 30, "job:1:1").applied)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=charge) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(applied) == [False] * (threads_n - 1) + [True]
    assert used(organization, SECONDS) == 30

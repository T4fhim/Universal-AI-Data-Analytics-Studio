# File: apps/api/tests/test_quotas_models.py
"""The quota tables and the closed kind set: structure the service relies on.

Why: a ``kind`` selects a counter row, a deployment-default setting and a window; a kind added to
the enum without the other two would silently meter nothing. And the database must hold the
invariants the service assumes (no negative counters, one ledger row per key), because Python-level
checks are bypassable by a raw write. Tenant isolation of the three tables is covered generically by
``test_tenant_isolation.py`` (discovery), not repeated here.
"""

from __future__ import annotations

import datetime

import pytest
from django.db import IntegrityError, transaction
from factories import factory_for, make_organization

from uadas_api.quotas.choices import (
    REFUSAL,
    STANDING_PERIOD,
    WINDOW_OF,
    UsageKind,
    Window,
    period_start,
)
from uadas_api.quotas.models import OrganizationQuota, UsageCounter, UsageLedger
from uadas_api.settings import _quota


@pytest.mark.parametrize("kind", UsageKind.values)
def test_every_kind_has_a_window_a_refusal_sentence_and_a_deployment_setting(
    kind: str,
) -> None:
    assert kind in WINDOW_OF
    assert kind in REFUSAL
    assert f"max_{kind}" in _quota.parse_quota({})


def test_the_window_table_names_only_known_kinds() -> None:
    assert set(WINDOW_OF) == set(UsageKind.values) == set(REFUSAL)


def test_refusal_sentences_carry_no_number_or_key() -> None:
    for sentence in REFUSAL.values():
        assert not any(ch.isdigit() for ch in sentence)


def test_a_standing_kind_has_one_fixed_period_and_a_monthly_kind_follows_the_month() -> (
    None
):
    moment = datetime.datetime(2026, 12, 31, 23, 59, tzinfo=datetime.UTC)
    assert period_start(UsageKind.ROWS.value, moment) == STANDING_PERIOD
    assert period_start(UsageKind.LLM_TOKENS.value, moment) == datetime.date(
        2026, 12, 1
    )
    # UTC, whatever zone the caller's clock is in: 01:00 on 1 Jan in UTC+2 is still December.
    plus_two = datetime.timezone(datetime.timedelta(hours=2))
    local = datetime.datetime(2027, 1, 1, 1, 0, tzinfo=plus_two)
    assert period_start(UsageKind.JOB_SECONDS.value, local) == datetime.date(
        2026, 12, 1
    )
    assert {w for w in WINDOW_OF.values()} == {Window.STANDING, Window.MONTHLY}


@pytest.mark.django_db
def test_a_counter_cannot_go_negative_in_the_database() -> None:
    org = make_organization()
    with pytest.raises(IntegrityError), transaction.atomic():
        factory_for(UsageCounter).create(org, used=-1)
    assert factory_for(UsageCounter).create(org, used=0).used == 0  # the twin


@pytest.mark.django_db
def test_an_unknown_kind_is_refused_by_the_database() -> None:
    org = make_organization()
    for model in (UsageCounter, UsageLedger, OrganizationQuota):
        with pytest.raises(IntegrityError), transaction.atomic():
            factory_for(model).create(org, kind="bogus")
        factory_for(model).create(org, kind=UsageKind.ROWS.value)  # the twin


@pytest.mark.django_db
def test_a_ledger_row_is_released_if_and_only_if_it_has_a_release_time() -> None:
    org = make_organization()
    with pytest.raises(IntegrityError), transaction.atomic():
        factory_for(UsageLedger).create(org, released=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        factory_for(UsageLedger).create(
            org, released=False, released_at=datetime.datetime.now(datetime.UTC)
        )
    factory_for(UsageLedger).create(
        org, released=True, released_at=datetime.datetime.now(datetime.UTC)
    )
    factory_for(UsageLedger).create(org)  # the twin: an ordinary live charge

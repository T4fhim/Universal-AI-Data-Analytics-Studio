# File: apps/api/tests/test_jobs_checks.py
"""The queue's system checks: they pass on the shipped configuration and fail on each override.

Why: the checks exist to catch a *later* weakening of a safe configuration (a settings module that
re-adds pickle, a test's ``override_settings`` that outlived it). A check that never fails proves
nothing, so every error id has a test that provokes it and one that shows the shipped settings do
not.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any

import pytest
from django.core.checks import CheckMessage, Error, Warning

from uadas_api.jobs import checks
from uadas_api.sandbox import runner

Check = Callable[..., list[CheckMessage]]


def ids(messages: list[CheckMessage]) -> list[str]:
    return [m.id for m in messages if m.id]


def test_the_shipped_configuration_raises_no_error() -> None:
    assert ids(checks.check_queue_is_json_only_and_late_acked()) == []


def test_pickle_in_accepted_content_is_an_error(settings: Any) -> None:
    settings.CELERY_ACCEPT_CONTENT = ["json", "pickle"]
    assert ids(checks.check_queue_is_json_only_and_late_acked()) == ["uadas_jobs.E001"]


@pytest.mark.parametrize(
    "name",
    ["CELERY_TASK_SERIALIZER", "CELERY_RESULT_SERIALIZER", "CELERY_EVENT_SERIALIZER"],
)
def test_any_non_json_serializer_is_an_error(settings: Any, name: str) -> None:
    setattr(settings, name, "pickle")
    assert "uadas_jobs.E001" in ids(checks.check_queue_is_json_only_and_late_acked())


@pytest.mark.parametrize(
    "name", ["CELERY_TASK_ACKS_LATE", "CELERY_TASK_REJECT_ON_WORKER_LOST"]
)
def test_losing_late_acknowledgement_is_an_error(settings: Any, name: str) -> None:
    setattr(settings, name, False)
    assert "uadas_jobs.E002" in ids(checks.check_queue_is_json_only_and_late_acked())


def test_a_visibility_timeout_shorter_than_the_longest_task_is_an_error(
    settings: Any,
) -> None:
    jobs = dict(settings.UADAS_JOBS)
    jobs["eager"] = (
        False  # the check is moot in eager mode (there is no broker to redeliver)
    )
    settings.UADAS_JOBS = jobs
    settings.CELERY_TASK_TIME_LIMIT = 600
    settings.CELERY_BROKER_TRANSPORT_OPTIONS = {
        "visibility_timeout": 650
    }  # < 600 + backoff
    assert "uadas_jobs.E003" in ids(checks.check_queue_is_json_only_and_late_acked())
    settings.CELERY_BROKER_TRANSPORT_OPTIONS = {
        "visibility_timeout": 600 + jobs["retry_backoff_max"] + 1
    }
    assert "uadas_jobs.E003" not in ids(
        checks.check_queue_is_json_only_and_late_acked()
    )


def test_eager_mode_is_a_deployment_warning(settings: Any) -> None:
    found = checks.check_deployment()
    assert any(
        isinstance(m, Warning) and m.id == "uadas_jobs.W001" for m in found
    )  # test settings are eager
    jobs = dict(settings.UADAS_JOBS)
    jobs["eager"] = False
    settings.UADAS_JOBS = jobs
    settings.CELERY_TASK_ALWAYS_EAGER = False
    assert "uadas_jobs.W001" not in ids(checks.check_deployment())


def test_an_unenforceable_platform_is_a_deployment_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checks, "limits_enforceable", lambda *a, **k: False)
    assert "uadas_jobs.W002" in ids(checks.check_deployment())
    monkeypatch.setattr(checks, "limits_enforceable", lambda *a, **k: True)
    assert "uadas_jobs.W002" not in ids(checks.check_deployment())


# ---------------------------------------------------------------- the child starts


def test_the_sandbox_child_starts_and_answers_in_this_installation() -> None:
    assert ids(checks.check_sandbox_child_starts()) == []


def test_a_child_that_cannot_start_is_an_error_with_the_user_site_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "default_child_command",
        lambda: [sys.executable, "-I", "-c", "import no_such_module_xyz"],
    )
    (message,) = checks.check_sandbox_child_starts()
    assert isinstance(message, Error) and message.id == "uadas_jobs.E004"
    assert message.hint is not None and "--user" in message.hint


def test_a_missing_interpreter_is_also_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner, "default_child_command", lambda: ["/no/such/python", "-I"]
    )
    assert ids(checks.check_sandbox_child_starts()) == ["uadas_jobs.E004"]


def _sandbox(settings: Any, **overrides: Any) -> None:
    settings.UADAS_SANDBOX = {**settings.UADAS_SANDBOX, **overrides}


def _as_euid(monkeypatch: pytest.MonkeyPatch, euid: int) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: euid, raising=False)


def test_a_root_worker_with_nothing_separating_the_child_is_an_error(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as_euid(monkeypatch, 0)
    _sandbox(settings, child_uid=None, isolation_acknowledged="")
    assert ids(checks.check_sandbox_isolation()) == ["uadas_jobs.E005"]


def test_a_root_worker_is_accepted_with_a_dedicated_uid_or_an_acknowledged_container(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as_euid(monkeypatch, 0)
    monkeypatch.setattr(checks, "can_switch_identity", lambda: True)
    _sandbox(settings, child_uid=61234, child_gid=61234, isolation_acknowledged="")
    assert ids(checks.check_sandbox_isolation()) == []
    _sandbox(
        settings, child_uid=None, child_gid=None, isolation_acknowledged="container"
    )
    assert ids(checks.check_sandbox_isolation()) == []


def test_an_unprivileged_worker_needs_no_isolation_statement(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as_euid(monkeypatch, 1000)
    _sandbox(settings, child_uid=None, isolation_acknowledged="")
    assert ids(checks.check_sandbox_isolation()) == []


def test_a_dedicated_uid_the_worker_cannot_switch_to_is_an_error(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as_euid(monkeypatch, 1000)
    _sandbox(settings, child_uid=61234, child_gid=61234)
    monkeypatch.setattr(checks, "can_switch_identity", lambda: False)
    assert ids(checks.check_sandbox_isolation()) == ["uadas_jobs.E006"]
    monkeypatch.setattr(checks, "can_switch_identity", lambda: True)
    assert ids(checks.check_sandbox_isolation()) == []


def test_a_demanded_network_namespace_the_host_refuses_is_an_error(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as_euid(monkeypatch, 1000)
    _sandbox(settings, network_isolation="unshare")
    monkeypatch.setattr(checks, "probe_network_isolation", lambda: False)
    assert ids(checks.check_sandbox_isolation()) == ["uadas_jobs.E007"]
    monkeypatch.setattr(checks, "probe_network_isolation", lambda: True)
    assert ids(checks.check_sandbox_isolation()) == []


def test_the_network_probe_only_runs_when_the_namespace_is_demanded(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as_euid(monkeypatch, 1000)

    def never() -> bool:
        raise AssertionError("probed although the namespace is not demanded")

    monkeypatch.setattr(checks, "probe_network_isolation", never)
    for mode in ("", "container", "none-acknowledged"):
        _sandbox(settings, network_isolation=mode)
        assert ids(checks.check_sandbox_isolation()) == []


def test_a_child_that_answers_with_anything_but_a_protocol_error_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = 'print(\'{"ok": true, "source_format": "csv", "row_count": 1, "column_count": 1, "columns": []}\')'
    monkeypatch.setattr(
        runner, "default_child_command", lambda: [sys.executable, "-I", "-c", code]
    )
    assert ids(checks.check_sandbox_child_starts()) == ["uadas_jobs.E004"]

# File: tests/ui/actions/test_action_registry.py
"""Tests for the Qt-free action registry.

No QApplication anywhere in this file -- ActionSpec/register_action/
get_action/list_actions are plain data and a dict, exactly like
src.visualization.chart_registry's own test tier.
"""

from __future__ import annotations

import pytest

from src.core.exceptions import ServiceError
from src.ui.actions.action_registry import (
    ActionCategory,
    ActionSpec,
    Requirement,
    get_action,
    list_actions,
    register_action,
    unregister_action,
)


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap in an empty registry for each test.

    Without this, tests here would either collide with the real
    builtin_actions.py registrations (if that module happens to already be
    imported elsewhere in the suite) or pollute it for tests that run
    after these -- matching the same isolation concern
    src.visualization.chart_registry's own tests would have if it defined
    a fixture like this (it currently does not need one because nothing
    else mutates its registry in tests).
    """
    import src.ui.actions.action_registry as registry_module

    monkeypatch.setattr(registry_module, "_REGISTRY", {})


def _make_spec(action_id: str = "test.action", **overrides) -> ActionSpec:
    defaults = dict(
        action_id=action_id,
        label="Test Action",
        category=ActionCategory.PROJECT,
    )
    defaults.update(overrides)
    return ActionSpec(**defaults)


def test_register_then_get_round_trips() -> None:
    spec = _make_spec()
    register_action(spec)
    assert get_action("test.action") is spec


def test_register_duplicate_id_raises_service_error() -> None:
    register_action(_make_spec())
    with pytest.raises(ServiceError, match="already registered"):
        register_action(_make_spec())


def test_get_unknown_action_raises_service_error() -> None:
    with pytest.raises(ServiceError, match="Unknown action id"):
        get_action("does.not.exist")


def test_unregister_removes_the_action() -> None:
    register_action(_make_spec())
    unregister_action("test.action")
    with pytest.raises(ServiceError):
        get_action("test.action")


def test_unregister_unknown_id_is_a_silent_no_op() -> None:
    unregister_action("never.registered")  # must not raise


def test_list_actions_returns_a_copy_not_the_live_registry() -> None:
    register_action(_make_spec())
    snapshot = list_actions()
    snapshot["test.action"] = "corrupted"
    assert get_action("test.action") != "corrupted"


def test_action_spec_defaults() -> None:
    spec = _make_spec()
    assert spec.icon_name is None
    assert spec.shortcut is None
    assert spec.requires == frozenset()
    assert spec.predicate is None
    assert spec.checkable is False
    assert spec.palette_visible is True
    assert spec.stage is None


def test_action_spec_is_frozen() -> None:
    spec = _make_spec()
    with pytest.raises(AttributeError):
        spec.label = "changed"  # type: ignore[misc]


def test_requirement_members_are_distinct() -> None:
    assert Requirement.PROJECT_OPEN != Requirement.ACTIVE_DATASET

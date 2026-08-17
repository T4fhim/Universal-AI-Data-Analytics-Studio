# File: tests/ui/actions/test_action_binder.py
"""Tests for ActionBinder: construction, binding, enablement, icons.

Needs a real QApplication (QAction/QMenu/QWidget all require one) -- the
qapp fixture from tests/ui/conftest.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from src.core.exceptions import ServiceError
from src.ui.actions.action_binder import ActionBinder
from src.ui.actions.action_registry import (
    ActionCategory,
    ActionSpec,
    Requirement,
    register_action,
)
from src.ui.theme.icon_provider import IconProvider
from src.ui.theme.tokens import DARK_TOKENS, LIGHT_TOKENS


@dataclass
class _FakeContext:
    """A minimal stand-in for ActionContext -- only satisfies()/attribute
    access ActionBinder.refresh_enablement actually needs, avoiding the
    real class's service-object construction for tests that only care
    about enablement mechanics, not what feeds it.
    """

    project_open: bool = False
    active_dataset: bool = False

    def satisfies(self, requirement: Requirement) -> bool:
        if requirement is Requirement.PROJECT_OPEN:
            return self.project_open
        if requirement is Requirement.ACTIVE_DATASET:
            return self.active_dataset
        raise AssertionError(requirement)


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.ui.actions.action_registry as registry_module

    monkeypatch.setattr(registry_module, "_REGISTRY", {})
    register_action(
        ActionSpec(
            action_id="test.always_on",
            label="Always On",
            category=ActionCategory.PROJECT,
        )
    )
    register_action(
        ActionSpec(
            action_id="test.needs_project",
            label="Needs Project",
            category=ActionCategory.PROJECT,
            requires=frozenset({Requirement.PROJECT_OPEN}),
        )
    )
    register_action(
        ActionSpec(
            action_id="test.needs_predicate",
            label="Needs Predicate",
            category=ActionCategory.PROJECT,
            predicate=lambda ctx: ctx.active_dataset,
        )
    )
    register_action(
        ActionSpec(
            action_id="test.with_icon",
            label="With Icon",
            category=ActionCategory.PROJECT,
            icon_name="save",
            shortcut="Ctrl+Shift+T",
            status_tip="A test action",
        )
    )


def test_bind_constructs_a_qaction_with_spec_fields(qapp: QApplication) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    action = binder.bind("test.with_icon", lambda: None)
    assert action.text() == "With Icon"
    assert action.statusTip() == "A test action"
    assert not action.shortcut().isEmpty()


def test_bind_returns_the_same_qaction_action_for_returns(
    qapp: QApplication,
) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    bound = binder.bind("test.always_on", lambda: None)
    reused = binder.action_for("test.always_on")
    assert bound is reused


def test_triggering_the_action_calls_the_bound_handler(qapp: QApplication) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    calls = []
    action = binder.bind("test.always_on", lambda: calls.append(1))
    action.trigger()
    assert calls == [1]


def test_assert_all_bound_raises_when_something_is_unbound(
    qapp: QApplication,
) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    binder.bind("test.always_on", lambda: None)
    # test.needs_project, test.needs_predicate, test.with_icon never bound.
    with pytest.raises(ServiceError, match="no bound handler"):
        binder.assert_all_bound()


def test_assert_all_bound_passes_when_everything_is_bound(qapp: QApplication) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    for action_id in (
        "test.always_on",
        "test.needs_project",
        "test.needs_predicate",
        "test.with_icon",
    ):
        binder.bind(action_id, lambda: None)
    binder.assert_all_bound()  # must not raise


def test_assert_all_bound_counts_actions_referenced_only_via_build_menu(
    qapp: QApplication,
) -> None:
    """A registered action referenced only through build_menu/action_for
    (never bind()) is still unbound -- having a QAction constructed is not
    the same as having a handler.
    """
    window = QWidget()
    binder = ActionBinder(window)
    menu = QMenu(window)
    binder.build_menu(menu, ("test.always_on",))  # constructed, not bound
    with pytest.raises(ServiceError, match="test.always_on"):
        binder.assert_all_bound()


def test_build_menu_inserts_separators_for_none(qapp: QApplication) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    menu = QMenu(window)
    binder.build_menu(menu, ("test.always_on", None, "test.with_icon"))
    actions = menu.actions()
    assert len(actions) == 3
    assert actions[1].isSeparator()


def test_refresh_enablement_applies_requires(qapp: QApplication) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    action = binder.bind("test.needs_project", lambda: None)

    binder.refresh_enablement(_FakeContext(project_open=False))
    assert action.isEnabled() is False

    binder.refresh_enablement(_FakeContext(project_open=True))
    assert action.isEnabled() is True


def test_refresh_enablement_applies_predicate(qapp: QApplication) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    action = binder.bind("test.needs_predicate", lambda: None)

    binder.refresh_enablement(_FakeContext(active_dataset=False))
    assert action.isEnabled() is False

    binder.refresh_enablement(_FakeContext(active_dataset=True))
    assert action.isEnabled() is True


def test_refresh_enablement_leaves_unconstrained_actions_enabled(
    qapp: QApplication,
) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    action = binder.bind("test.always_on", lambda: None)
    binder.refresh_enablement(_FakeContext())
    assert action.isEnabled() is True


def test_binder_without_icon_provider_produces_actions_with_no_icon(
    qapp: QApplication,
) -> None:
    window = QWidget()
    binder = ActionBinder(window, icon_provider=None)
    action = binder.bind("test.with_icon", lambda: None)
    assert action.icon().isNull()


def test_binder_with_icon_provider_sets_the_icon(qapp: QApplication) -> None:
    window = QWidget()
    provider = IconProvider(DARK_TOKENS)
    binder = ActionBinder(window, icon_provider=provider)
    action = binder.bind("test.with_icon", lambda: None)
    assert not action.icon().isNull()


def test_icons_changed_re_sets_icon_on_theme_switch(qapp: QApplication) -> None:
    window = QWidget()
    provider = IconProvider(DARK_TOKENS)
    binder = ActionBinder(window, icon_provider=provider)
    action = binder.bind("test.with_icon", lambda: None)
    icon_before = action.icon().cacheKey()

    provider.set_tokens(LIGHT_TOKENS)  # emits icons_changed -> _refresh_icons
    icon_after = action.icon().cacheKey()

    # A different theme recolours the icon to a different QPixmap, so the
    # cache key (which QIcon derives from its underlying pixmap data)
    # changes -- proving _refresh_icons actually re-set it rather than
    # leaving the dark-theme icon on screen after switching to light.
    assert icon_before != icon_after

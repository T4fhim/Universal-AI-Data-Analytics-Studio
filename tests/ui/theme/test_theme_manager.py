# File: tests/ui/theme/test_theme_manager.py
"""Tests for ThemeManager as a QObject: signal emission, density, errors.

Milestone 15 promoted ThemeManager from a plain class to a QObject
specifically so icon and chart theming could react to a theme switch --
these tests exist to prove that promotion actually works, not just that the
stylesheet still applies.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from src.core.exceptions import ServiceError
from src.ui.theme.tokens import Density
from src.ui.theme_manager import ThemeManager


@pytest.fixture()
def manager(qapp: QApplication) -> ThemeManager:
    return ThemeManager(qapp)


def test_current_theme_is_none_before_first_apply(manager: ThemeManager) -> None:
    assert manager.current_theme() is None
    assert manager.current_tokens() is None


def test_apply_theme_sets_current_theme_and_application_stylesheet(
    manager: ThemeManager, qapp: QApplication
) -> None:
    manager.apply_theme("dark")
    assert manager.current_theme() == "dark"
    assert qapp.styleSheet() != ""


def test_apply_theme_emits_theme_changed_with_the_name(manager: ThemeManager) -> None:
    received: list[str] = []
    manager.theme_changed.connect(received.append)
    manager.apply_theme("light")
    assert received == ["light"]


def test_unknown_theme_raises_service_error_and_does_not_change_state(
    manager: ThemeManager,
) -> None:
    manager.apply_theme("dark")
    with pytest.raises(ServiceError, match="Unknown theme"):
        manager.apply_theme("not-a-real-theme")
    assert manager.current_theme() == "dark"  # unchanged


def test_current_tokens_reflects_the_applied_theme(manager: ThemeManager) -> None:
    manager.apply_theme("light")
    tokens = manager.current_tokens()
    assert tokens is not None
    assert tokens.name == "light"


def test_set_density_reapplies_and_reemits_when_a_theme_is_active(
    manager: ThemeManager,
) -> None:
    manager.apply_theme("dark")
    received: list[str] = []
    manager.theme_changed.connect(received.append)

    manager.set_density(Density.COMPACT)

    assert received == ["dark"], "density change must re-notify icon/chart consumers"
    assert manager.current_tokens().density is Density.COMPACT


def test_set_density_before_any_apply_does_not_raise(manager: ThemeManager) -> None:
    manager.set_density(Density.COMFORTABLE)  # no theme applied yet
    assert manager.current_theme() is None


def test_set_density_to_the_same_value_is_a_noop(manager: ThemeManager) -> None:
    manager.apply_theme("dark")
    received: list[str] = []
    manager.theme_changed.connect(received.append)

    manager.set_density(Density.COZY)  # already the default

    assert received == [], "no-op density change should not re-emit theme_changed"


def test_high_contrast_theme_applies_successfully(manager: ThemeManager) -> None:
    manager.apply_theme("high_contrast")
    assert manager.current_tokens().name == "high_contrast"


# -- Milestone 28: base font size and reduced motion ---------------------------------------------


def test_set_base_font_size_reapplies_and_scales_tokens(manager: ThemeManager) -> None:
    manager.apply_theme("dark")
    received: list[str] = []
    manager.theme_changed.connect(received.append)

    manager.set_base_font_size(18)

    assert received == ["dark"]
    tokens = manager.current_tokens()
    assert tokens.font_size_md == 18
    assert (
        tokens.font_size_sm == 17
    )  # -1 delta preserved from the dark theme's defaults
    assert tokens.font_size_lg == 21  # +3 delta preserved


def test_set_base_font_size_before_any_apply_does_not_raise(
    manager: ThemeManager,
) -> None:
    manager.set_base_font_size(16)
    assert manager.current_theme() is None


def test_set_base_font_size_to_the_same_value_is_a_noop(manager: ThemeManager) -> None:
    manager.apply_theme("dark")
    manager.set_base_font_size(18)
    received: list[str] = []
    manager.theme_changed.connect(received.append)

    manager.set_base_font_size(18)

    assert received == []


def test_set_reduced_motion_emits_reduced_motion_changed(manager: ThemeManager) -> None:
    received: list[bool] = []
    manager.reduced_motion_changed.connect(received.append)

    manager.set_reduced_motion(True)

    assert received == [True]
    assert manager.reduced_motion() is True


def test_set_reduced_motion_to_the_same_value_is_a_noop(manager: ThemeManager) -> None:
    manager.set_reduced_motion(True)
    received: list[bool] = []
    manager.reduced_motion_changed.connect(received.append)

    manager.set_reduced_motion(True)

    assert received == []


def test_set_reduced_motion_does_not_touch_the_stylesheet(
    manager: ThemeManager,
) -> None:
    """Motion has no QSS representation -- see ThemeManager's own module docstring."""
    manager.apply_theme("dark")
    received: list[str] = []
    manager.theme_changed.connect(received.append)

    manager.set_reduced_motion(True)

    assert received == []

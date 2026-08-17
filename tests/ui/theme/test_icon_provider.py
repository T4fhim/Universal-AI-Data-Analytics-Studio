# File: tests/ui/theme/test_icon_provider.py
"""Tests for IconProvider: recolouring, caching, missing-icon fallback.

Needs a real QApplication (for QPixmap), hence the qapp fixture from
tests/ui/conftest.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.theme.icon_provider import IconProvider
from src.ui.theme.tokens import DARK_TOKENS, LIGHT_TOKENS


@pytest.fixture()
def provider(qapp: QApplication) -> IconProvider:
    return IconProvider(DARK_TOKENS)


def test_every_bundled_icon_renders_without_error(provider: IconProvider) -> None:
    names = provider.available_icons()
    assert len(names) > 0, "resources/icons is empty"
    for name in names:
        icon = provider.icon(name)
        assert not icon.isNull(), f"icon '{name}' failed to render"


def test_missing_icon_degrades_to_empty_icon_not_a_crash(provider: IconProvider) -> None:
    icon = provider.icon("this-does-not-exist")
    assert icon.isNull()


def test_same_request_is_served_from_cache(provider: IconProvider) -> None:
    first = provider.icon("save")
    second = provider.icon("save")
    assert first.cacheKey() == second.cacheKey()


def test_set_tokens_to_same_theme_is_a_noop(provider: IconProvider) -> None:
    first = provider.icon("save")
    provider.set_tokens(DARK_TOKENS)  # same theme name
    second = provider.icon("save")
    assert first.cacheKey() == second.cacheKey()


def test_set_tokens_to_new_theme_clears_the_cache_and_emits(
    provider: IconProvider,
) -> None:
    provider.icon("save")  # populate cache under dark
    received: list[None] = []
    provider.icons_changed.connect(lambda: received.append(None))

    provider.set_tokens(LIGHT_TOKENS)

    assert received, "icons_changed did not fire on a real theme switch"
    assert provider._cache == {}  # noqa: SLF001 -- verifying the cache actually cleared


def test_icon_accepts_an_explicit_color_override(provider: IconProvider) -> None:
    themed = provider.icon("save", color=DARK_TOKENS.text_primary)
    danger = provider.icon("save", color=DARK_TOKENS.danger)
    assert themed.cacheKey() != danger.cacheKey()


def test_available_icons_is_sorted(provider: IconProvider) -> None:
    names = provider.available_icons()
    assert names == sorted(names)


def test_missing_icons_directory_returns_empty_list_not_error(
    qapp: QApplication, tmp_path: Path
) -> None:
    empty_provider = IconProvider(DARK_TOKENS, icons_dir=tmp_path / "does-not-exist")
    assert empty_provider.available_icons() == []

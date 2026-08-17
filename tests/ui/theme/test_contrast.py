# File: tests/ui/theme/test_contrast.py
"""Proves every theme meets WCAG 2.2 Level AA, rather than asserting it does.

This is the test that makes the token layer worth having. Colours in the
previous hand-maintained QSS files were never checked against anything, and
running these assertions against them for the first time found two genuine
failures: the dark theme's focus ring scored 2.83 against a 3:1 floor
(1.4.11), and the standard Okabe-Ito palette's blue scored 2.87 on the dark
chart ground. Both are fixed in :mod:`src.ui.theme.tokens`, and both would
have shipped without this file.

Needs no ``QApplication`` -- contrast is a property of two colours, not of a
widget -- so it runs in the fast, Qt-free tier.
"""

from __future__ import annotations

import pytest

from src.ui.a11y.contrast_manifest import CONTRAST_REQUIREMENTS
from src.ui.theme.contrast import (
    AA_NON_TEXT,
    contrast_ratio,
    parse_hex,
    relative_luminance,
)
from src.ui.theme.tokens import TOKENS_BY_NAME, ThemeTokens

_THEMES = list(TOKENS_BY_NAME.values())
_THEME_IDS = list(TOKENS_BY_NAME)


@pytest.mark.parametrize("tokens", _THEMES, ids=_THEME_IDS)
@pytest.mark.parametrize(
    "requirement",
    CONTRAST_REQUIREMENTS,
    ids=lambda r: f"{r.foreground}-on-{r.background}",
)
def test_token_pairing_meets_wcag_aa(tokens: ThemeTokens, requirement) -> None:
    foreground = getattr(tokens, requirement.foreground)
    background = getattr(tokens, requirement.background)
    ratio = contrast_ratio(foreground, background)
    assert ratio >= requirement.minimum, (
        f"[{tokens.name}] {requirement.rationale}: "
        f"{requirement.foreground} ({foreground}) on "
        f"{requirement.background} ({background}) is {ratio:.2f}:1, "
        f"below the required {requirement.minimum}:1."
    )


@pytest.mark.parametrize("tokens", _THEMES, ids=_THEME_IDS)
def test_chart_colors_are_distinguishable_from_their_ground(
    tokens: ThemeTokens,
) -> None:
    """Every series colour must clear 3:1 against the plot background.

    Checked per-theme rather than once, because a single palette cannot
    serve both grounds -- which is exactly why ``chart_categorical`` is a
    per-theme token instead of a module constant.
    """
    failures = [
        (color, round(contrast_ratio(color, tokens.surface_1), 2))
        for color in tokens.chart_categorical
        if contrast_ratio(color, tokens.surface_1) < AA_NON_TEXT
    ]
    assert not failures, (
        f"[{tokens.name}] chart colours below {AA_NON_TEXT}:1 against "
        f"surface_1 ({tokens.surface_1}): {failures}"
    )


@pytest.mark.parametrize("tokens", _THEMES, ids=_THEME_IDS)
def test_stage_hues_are_visible_on_their_ground(tokens: ThemeTokens) -> None:
    """The stage rail's status dots are non-text indicators, so 3:1 applies."""
    failures = [
        (hue, round(contrast_ratio(hue, tokens.surface_1), 2))
        for hue in tokens.stage_hues
        if contrast_ratio(hue, tokens.surface_1) < AA_NON_TEXT
    ]
    assert not failures, f"[{tokens.name}] stage hues below 3:1: {failures}"


def test_contrast_ratio_is_symmetric() -> None:
    """Argument order must not matter -- callers rely on this."""
    assert contrast_ratio("#ffffff", "#000000") == contrast_ratio("#000000", "#ffffff")


def test_black_on_white_is_the_maximum_ratio() -> None:
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)


def test_identical_colors_have_no_contrast() -> None:
    assert contrast_ratio("#3a5fc4", "#3a5fc4") == pytest.approx(1.0)


def test_luminance_bounds() -> None:
    assert relative_luminance("#000000") == pytest.approx(0.0)
    assert relative_luminance("#ffffff") == pytest.approx(1.0)


@pytest.mark.parametrize("bad", ["3a5fc4", "#abc", "#gggggg", "", "rgb(1,2,3)"])
def test_parse_hex_rejects_anything_but_full_six_digit_hex(bad: str) -> None:
    """Short form and named colours are rejected on purpose.

    Every token is authored as ``#rrggbb``; accepting other spellings would
    create a second way to write the same value and invite drift.
    """
    with pytest.raises(ValueError):
        parse_hex(bad)

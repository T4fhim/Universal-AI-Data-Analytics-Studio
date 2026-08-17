# File: tests/ui/theme/test_plotly_theme.py
"""Tests for the Plotly layout/config translation.

No QApplication needed -- these return plain dicts with no Qt involvement.
"""

from __future__ import annotations

import pytest

from src.ui.theme.plotly_theme import plotly_config, plotly_layout
from src.ui.theme.tokens import DARK_TOKENS, LIGHT_TOKENS, TOKENS_BY_NAME


@pytest.mark.parametrize(
    "tokens", list(TOKENS_BY_NAME.values()), ids=list(TOKENS_BY_NAME)
)
def test_layout_paper_and_plot_background_are_not_transparent(tokens) -> None:
    """A transparent paper would show the QWebEngineView's own white backing
    through on dark themes -- see the module docstring for why this matters.
    """
    layout = plotly_layout(tokens)
    assert layout["paper_bgcolor"] == tokens.surface_1
    assert layout["plot_bgcolor"] == tokens.surface_1
    assert layout["paper_bgcolor"] != "rgba(0,0,0,0)"


def test_layout_colorway_matches_theme_chart_colors() -> None:
    layout = plotly_layout(DARK_TOKENS)
    assert layout["colorway"] == list(DARK_TOKENS.chart_categorical)


def test_dark_and_light_layouts_differ() -> None:
    assert plotly_layout(DARK_TOKENS) != plotly_layout(LIGHT_TOKENS)


def test_layout_font_family_has_no_stray_quotes() -> None:
    """tokens.font_family is CSS-quoted for QSS; Plotly's font.family is not CSS."""
    layout = plotly_layout(DARK_TOKENS)
    assert '"' not in layout["font"]["family"]


def test_config_disables_the_plotly_logo() -> None:
    assert plotly_config(DARK_TOKENS)["displaylogo"] is False


def test_config_keeps_the_mode_bar_always_visible() -> None:
    """Hiding the mode bar until hover would make zoom/pan/download
    unreachable without a mouse -- a WCAG 2.1.1 failure.
    """
    assert plotly_config(DARK_TOKENS)["displayModeBar"] is True

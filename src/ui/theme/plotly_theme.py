# File: src/ui/theme/plotly_theme.py
"""Translates design tokens into a Plotly layout template.

Charts render inside a ``QWebEngineView`` (see
:mod:`src.ui.widgets.chart_view`), which is a separate rendering engine that
Qt's stylesheet cannot reach. Without this module a chart keeps Plotly's
default white canvas and its default ten-colour qualitative palette, so
switching the application to the dark theme leaves a glaring white rectangle
in the middle of the window -- and the series colours are whatever Plotly
picked, not the colourblind-safe ramp
:mod:`src.ui.theme.tokens` validated.

Returns a plain ``dict`` rather than a ``plotly.graph_objects.layout.Template``
so that this module has no Plotly import. The dict is applied by the chart
layer, which already depends on Plotly, and keeping it out of here means the
theme package stays importable by tests that have no interest in charts.

Milestone 16 pushes the output of :func:`plotly_layout` across the
``QWebChannel`` bridge as a ``Plotly.relayout`` call, so a theme switch
recolours open charts in place instead of reloading the page.
"""

from __future__ import annotations

from typing import Any

from src.ui.theme.tokens import ThemeTokens


def plotly_layout(tokens: ThemeTokens) -> dict[str, Any]:
    """Return a Plotly ``layout`` dict matching ``tokens``.

    Both ``paper_bgcolor`` (the area around the plot) and ``plot_bgcolor``
    (inside the axes) are set to ``surface_1`` rather than leaving the paper
    transparent. A transparent paper shows the ``QWebEngineView``'s own
    default white backing through, which defeats the purpose on dark themes.
    """
    return {
        "paper_bgcolor": tokens.surface_1,
        "plot_bgcolor": tokens.surface_1,
        "font": {
            "family": tokens.font_family.replace('"', ""),
            "size": tokens.font_size_md,
            "color": tokens.text_primary,
        },
        "title": {"font": {"size": tokens.font_size_lg, "color": tokens.text_primary}},
        "colorway": list(tokens.chart_categorical),
        "xaxis": _axis(tokens),
        "yaxis": _axis(tokens),
        "legend": {
            "bgcolor": tokens.surface_1,
            "bordercolor": tokens.border,
            "borderwidth": 1,
            "font": {"color": tokens.text_primary},
        },
        "hoverlabel": {
            "bgcolor": tokens.surface_2,
            "bordercolor": tokens.border_strong,
            "font": {"color": tokens.text_primary, "size": tokens.font_size_sm},
        },
        "margin": {"l": 56, "r": 24, "t": 48, "b": 48},
    }


def _axis(tokens: ThemeTokens) -> dict[str, Any]:
    """Return the shared axis styling both axes use.

    Gridlines use ``border`` rather than ``text_secondary``: a gridline is
    decoration behind the data, and WCAG 1.4.11 does not require 3:1 for it,
    whereas a gridline at text contrast visually competes with the series
    it is meant to sit behind.
    """
    return {
        "gridcolor": tokens.border,
        "zerolinecolor": tokens.border_strong,
        "linecolor": tokens.border_strong,
        "tickfont": {"color": tokens.text_secondary, "size": tokens.font_size_sm},
        "title": {"font": {"color": tokens.text_primary}},
    }


def plotly_config(tokens: ThemeTokens) -> dict[str, Any]:
    """Return the Plotly ``config`` object for a chart in this theme.

    ``displaylogo`` is off and the mode bar is always visible: hiding the
    mode bar until hover makes zoom, pan, and download unreachable for anyone
    who is not using a mouse, which would fail WCAG 2.1.1.
    """
    return {
        "displaylogo": False,
        "displayModeBar": True,
        "responsive": True,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        "toImageButtonOptions": {"format": "png", "scale": 2},
    }

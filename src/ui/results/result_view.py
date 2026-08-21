# File: src/ui/results/result_view.py
"""Shared, Qt-free display-formatting helpers every renderer in :mod:`~src.ui.results.renderers`
may use.

Per the plan's R5 mitigation ("`results/renderers/` imports only `src.analysis`/
`src.forecasting`/`result_view` and never Qt"): renderers format numbers into display strings
themselves (see :mod:`~src.ui.results.base_result_renderer`'s own docstring on why a
:class:`~src.ui.results.base_result_renderer.MetricSection` already carries a formatted
``value``, not a raw ``float``), and this module is where that formatting logic is shared rather
than copy-pasted per renderer file -- a p-value or a percentage should read the same way whether
it came from a t-test or a chi-square test. Kept dependency-free (standard library only) so it
can sit on the Qt-free side of the renderer/widget boundary :mod:`~src.ui.results.
base_result_renderer` documents, alongside those renderers rather than alongside
:class:`~src.ui.results.result_card.ResultCard`.
"""

from __future__ import annotations


def format_p_value(p_value: float) -> str:
    """Format a p-value to 4 decimal places -- enough precision to distinguish 0.049 from
    0.051 across the conventional 0.05 threshold without implying false precision beyond it.
    """
    return f"{p_value:.4f}"


def format_percent(fraction: float, *, decimals: int = 1) -> str:
    """Format a ``0.0``-``1.0`` fraction as a percentage string, e.g. ``0.847`` -> ``"84.7%"``."""
    return f"{fraction * 100:.{decimals}f}%"


def format_number(value: float, *, decimals: int = 4) -> str:
    """Format a plain numeric result to ``decimals`` places."""
    return f"{value:.{decimals}f}"


def significance_caption(p_value: float, significant: bool) -> str:
    """The standard "p = ..., significant/not significant at 0.05" caption used by every
    hypothesis-test renderer's p-value :class:`~src.ui.results.base_result_renderer.MetricSection`.
    """
    verdict = (
        "statistically significant" if significant else "not statistically significant"
    )
    return f"p = {format_p_value(p_value)} -- {verdict} at the 0.05 level."

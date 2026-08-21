# File: src/ui/results/renderers/__init__.py
"""Concrete :class:`~src.ui.results.base_result_renderer.BaseResultRenderer` subclasses.

One module per family of :mod:`src.analysis` result types, grouped the way the plan's M22
section lists them (``profiling``, ``statistical_tests``, ``regression``, ``multivariate``,
``correlation``, ``generic``) rather than one-file-per-dataclass -- a t-test and an ANOVA result
share enough shape (statistic, p-value, significance flag) that splitting them into separate
files would mean more import boilerplate in :mod:`~src.ui.results.result_renderer_registry` for
no real gain in either readability or testability.

Renderers here do not self-register (contrast :mod:`~src.plugins.plugin_manager`, which
registers a plugin's own chart/operation classes at load time) -- registration is centralized in
:func:`~src.ui.results.result_renderer_registry._register_builtins`, matching
:func:`~src.visualization.chart_registry._register_builtins`'s and :func:`~src.cleaning.
operation_registry._register_builtins`'s own "one place lists every built-in" shape rather than
scattering a ``register_renderer(...)`` call across N files.
"""

from __future__ import annotations

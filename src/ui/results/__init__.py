# File: src/ui/results/__init__.py
"""Result rendering: turns ~2,000 orphaned :mod:`src.analysis` lines into product (milestone 22).

Two layers, per the plan's A5 ("Result rendering"):

1. :mod:`~src.ui.results.base_result_renderer` / :mod:`~src.ui.results.renderers` -- pure,
   Qt-free functions. A :class:`~src.ui.results.base_result_renderer.BaseResultRenderer`
   subclass converts one analysis-result dataclass (``TTestResult``, ``CorrelationResult``, ...)
   into a list of :class:`~src.ui.results.base_result_renderer.ResultSection` dataclasses --
   plain data, testable with zero ``QApplication``.
2. :class:`~src.ui.results.result_card.ResultCard` / :class:`~src.ui.results.explanation_panel.
   ExplanationPanel` -- the only place in this package that touches Qt, theming, or
   accessibility. Every renderer's ``sections()`` output funnels through the same widget-building
   code, instead of each result type growing its own bespoke display panel.

This package is display-only, matching :mod:`src.ui.workbench`'s own shape (see that package's
``__init__`` docstring): it holds no service references and imports nothing from
:mod:`src.ui.controllers` -- ``tests/ui/test_import_layering.py``'s ``_WIDGET_LIKE_PACKAGES``
tuple includes ``"results"`` for exactly this reason.
"""

from __future__ import annotations

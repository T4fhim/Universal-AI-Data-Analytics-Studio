# File: src/ui/web/__init__.py
"""QWebEngineView plumbing shared by chart rendering.

Split out from :mod:`src.ui.widgets.chart_view` in milestone 16 so the two
concerns -- staging the static HTML/JS/plotly.min.js assets onto disk
(:mod:`~src.ui.web.web_assets`) and the Python<->JS event channel
(:mod:`~src.ui.web.chart_bridge`) -- are each independently testable without
constructing a :class:`~PySide6.QtWebEngineWidgets.QWebEngineView` (see
``tests/ui/widgets/test_chart_view.py`` and the R6 risk note in
``plans/ui-overhaul-pioneering-adaptive-workbench.md``: offscreen
``QWebEngineView`` can hang or fail to initialize, so as much of this
subsystem as possible is written and tested as plain functions/QObjects that
do not require one).
"""

from __future__ import annotations

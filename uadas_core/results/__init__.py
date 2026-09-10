# File: uadas_core/results/__init__.py
"""Qt-free result rendering: analysis/forecast result dataclasses -> a list of
plain ``ResultSection`` dataclasses (see ``base_result_renderer``), testable with
zero QApplication. Lifted out of ``src/ui/results/`` in web-transition Phase 1.5;
the Qt display layer (``src/ui/results/result_card.py`` /
``explanation_panel.py``) still lives in the desktop shell and consumes this.
"""

from __future__ import annotations

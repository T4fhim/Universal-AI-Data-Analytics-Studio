# File: src/ui/results/result_card.py
"""``ResultCard``: the one place in :mod:`~src.ui.results` that touches Qt (milestone 22).

Converts whatever list of :class:`~src.ui.results.base_result_renderer.ResultSection` values a
:class:`~src.ui.results.base_result_renderer.BaseResultRenderer` returns into a widget tree.
Every renderer funnels through the same six ``isinstance`` branches here instead of each result
type growing its own bespoke display panel -- the exact duplication A5's own section says this
split exists to avoid ("all Qt, theming, and accessibility code lives in exactly one place
instead of once per result type").

``ResultCard`` never imports a specific renderer or result dataclass -- it only knows
:class:`~src.ui.results.base_result_renderer.ResultSection` and calls
:func:`~src.ui.results.result_renderer_registry.get_renderer` to find out how to render whatever
:meth:`display` is handed. That keeps this widget usable from any stage page (Analyze, Explore,
the future chat-panel tool-result rendering M21 depends on this milestone for) without a
per-caller import list.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.expertise_level import ExpertiseLevel
from src.ui.a11y.accessible import describe
from src.ui.results.base_result_renderer import (
    AssumptionsSection,
    FigureSection,
    KeyValueSection,
    MetricSection,
    ProseSection,
    ResultSection,
    TableSection,
)
from src.ui.results.result_renderer_registry import get_renderer
from src.ui.widgets.chart_view import ChartView

# Object-name / accessible-name prefix stamped on every section widget this card builds, plus a
# `resultSectionKind` dynamic property naming which ResultSection subclass produced it -- a test
# can find "the AssumptionsSection widget" via `findChildren` + property lookup without needing
# ResultCard to expose a bespoke accessor method per section kind.
_SECTION_KIND_PROPERTY = "resultSectionKind"


class ResultCard(QWidget):
    """Renders one analysis result as a titled card of sections.

    Holds no service references and imports nothing from :mod:`src.ui.controllers` --
    ``tests/ui/test_import_layering.py``'s ``_WIDGET_LIKE_PACKAGES`` includes ``"results"``.
    A caller (a stage page, eventually the chat panel per M21) constructs one, calls
    :meth:`display` with a real result object, and embeds it in its own layout.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultCard")

        layout = QVBoxLayout(self)

        self._title_label = QLabel(self)
        self._title_label.setObjectName("resultCardTitle")
        self._title_label.setWordWrap(True)
        font = self._title_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self._title_label.setFont(font)
        layout.addWidget(self._title_label)

        self._headline_label = QLabel(self)
        self._headline_label.setObjectName("resultCardHeadline")
        self._headline_label.setWordWrap(True)
        layout.addWidget(self._headline_label)

        self._sections_layout = QVBoxLayout()
        layout.addLayout(self._sections_layout)
        layout.addStretch(1)

        # One entry per section widget built by the most recent display() call -- cleared and
        # rebuilt each time rather than mutated in place, since a renderer's sections() output
        # can change shape entirely between calls (different result type, different
        # ExpertiseLevel), and diffing an old section tree against a new one would add real
        # complexity for a card that is cheap to rebuild from scratch.
        self.section_widgets: list[QWidget] = []

    def display(self, result: Any, level: ExpertiseLevel) -> None:
        """Resolve ``result``'s renderer and rebuild this card from its output.

        Args:
            result: Any analysis result object -- resolved to a renderer via
                :func:`~src.ui.results.result_renderer_registry.get_renderer`, which never
                raises (see that function's own docstring), so this method cannot fail on an
                unrecognized result type either.
            level: Which :class:`~src.core.expertise_level.ExpertiseLevel` to render for.
        """
        renderer = get_renderer(type(result))
        title = renderer.title(result)
        headline = renderer.headline(result, level)
        sections = renderer.sections(result, level)

        self._title_label.setText(title)
        self._headline_label.setText(headline)
        describe(
            self,
            name=f"Result: {title}",
            description=headline,
            help_anchor=renderer.help_anchor(),
            focusable=False,  # a container, not a control to tab to itself
        )

        self._clear_sections()
        for section in sections:
            widget = _build_section_widget(section, self)
            self._sections_layout.addWidget(widget)
            self.section_widgets.append(widget)

    def _clear_sections(self) -> None:
        while self._sections_layout.count():
            item = self._sections_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.section_widgets.clear()


def _build_section_widget(section: ResultSection, parent: QWidget) -> QWidget:
    box = QGroupBox(section.title, parent)
    box.setProperty(_SECTION_KIND_PROPERTY, type(section).__name__)
    box.setObjectName(f"resultSection_{type(section).__name__}")
    inner = QVBoxLayout(box)

    if isinstance(section, KeyValueSection):
        for label, value in section.items:
            item_label = QLabel(f"{label}: {value}", box)
            item_label.setWordWrap(True)
            inner.addWidget(item_label)
        describe(box, name=section.title, focusable=False)

    elif isinstance(section, MetricSection):
        value_label = QLabel(section.value, box)
        value_font = value_label.font()
        value_font.setBold(True)
        value_font.setPointSize(value_font.pointSize() + 4)
        value_label.setFont(value_font)
        inner.addWidget(value_label)
        if section.caption:
            caption_label = QLabel(section.caption, box)
            caption_label.setWordWrap(True)
            inner.addWidget(caption_label)
        describe(
            box,
            name=section.title,
            description=f"{section.value}. {section.caption}".strip(),
            focusable=False,
        )

    elif isinstance(section, ProseSection):
        text_label = QLabel(section.text, box)
        text_label.setWordWrap(True)
        inner.addWidget(text_label)
        describe(box, name=section.title, description=section.text, focusable=False)

    elif isinstance(section, AssumptionsSection):
        bullet_text = "\n".join(f"• {a}" for a in section.assumptions)
        text_label = QLabel(bullet_text, box)
        text_label.setWordWrap(True)
        inner.addWidget(text_label)
        describe(
            box,
            name=section.title,
            description="; ".join(section.assumptions),
            focusable=False,
        )

    elif isinstance(section, TableSection):
        table = QTableWidget(len(section.rows), len(section.columns), box)
        table.setHorizontalHeaderLabels(list(section.columns))
        table.verticalHeader().setVisible(False)
        for row_index, row in enumerate(section.rows):
            for col_index, cell in enumerate(row):
                table.setItem(row_index, col_index, QTableWidgetItem(cell))
        table.resizeColumnsToContents()
        describe(
            table,
            name=f"{section.title} table",
            description=f"{len(section.rows)} row(s), {len(section.columns)} column(s).",
        )
        inner.addWidget(table)

    elif isinstance(section, FigureSection):
        chart = ChartView(box)
        chart.display_figure(section.figure)
        chart.setMinimumHeight(320)
        describe(chart, name=section.title, focusable=False)
        inner.addWidget(chart)

    else:  # pragma: no cover -- ResultSection is a closed union; unreachable in practice.
        text_label = QLabel(repr(section), box)
        text_label.setWordWrap(True)
        inner.addWidget(text_label)

    return box

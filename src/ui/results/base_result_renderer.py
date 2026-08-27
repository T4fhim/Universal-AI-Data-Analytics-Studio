# File: src/ui/results/base_result_renderer.py
"""The `ResultSection` vocabulary and the `Base*`-shaped renderer contract (milestone 22).

Mirrors :class:`~src.readers.base_reader.BaseReader`, :class:`~src.cleaning.base_operation.
BaseOperation`, and :class:`~src.visualization.base_chart.BaseChart` exactly, per CLAUDE.md's
"``Base*`` extension-point pattern": stateless, classmethod-only -- a renderer is never
instantiated, it is held as a class in :mod:`~src.ui.results.result_renderer_registry`'s
registry, the same way a chart class is held in ``chart_registry``.

The one deliberate departure from those three is *what* a renderer returns. ``BaseChart.build``
returns a ``go.Figure`` -- a widget-adjacent object the caller embeds directly. A result
renderer instead returns a list of :class:`ResultSection` values: small frozen dataclasses that
describe *what to show*, not *how to show it*. Qt lives nowhere in this module -- not an import,
not a type hint. That is what lets ``TTestResultRenderer.sections(result, ExpertiseLevel.
BEGINNER)`` be asserted against with plain ``==`` in a test that never touches ``QApplication``
(see ``tests/ui/results/``), and what keeps :class:`~src.ui.results.result_card.ResultCard` the
*only* place in this package that converts a section into a widget -- one Qt/theming/
accessibility code path instead of one per result type, exactly as the plan's A5 section
requires.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.core.expertise_level import ExpertiseLevel


@dataclass(frozen=True)
class KeyValueSection:
    """A short list of label/value pairs -- e.g. row count, column count, duplicate rows.

    Attributes:
        title: Heading shown above the pairs.
        items: ``(label, value)`` pairs, in display order. ``value`` is already a display
            string (renderers format numbers themselves) rather than a raw ``float``/``int`` --
            keeping formatting decisions ("3 decimal places", "as a percentage") in the renderer
            that knows the semantics, not pushed down into :class:`~src.ui.results.result_card.
            ResultCard`, which would then need to special-case every field name to format it
            sensibly.
    """

    title: str
    items: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class TableSection:
    """A small tabular result -- a contingency table, a per-column profile, a coefficient list.

    Attributes:
        title: Heading shown above the table.
        columns: Column headers, in display order.
        rows: One tuple per row, each already display-formatted strings -- same rationale as
            :attr:`KeyValueSection.items`.
    """

    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class FigureSection:
    """An embedded Plotly figure -- e.g. a PCA scree plot or a cluster scatter, when a renderer
    builds one. Holds the figure object itself (``Any`` rather than ``plotly.graph_objects.
    Figure`` here, to keep this module importing nothing beyond the standard library and
    :mod:`src.core` -- the figure's real type is enforced at the renderer call site, where
    ``plotly`` is already an ordinary dependency)."""

    title: str
    figure: Any


@dataclass(frozen=True)
class ProseSection:
    """Free-text prose -- a plain-language summary, a caveat, a list of ambiguous columns."""

    title: str
    text: str


@dataclass(frozen=True)
class MetricSection:
    """One headline number with an optional caption -- e.g. "p-value: 0.032" / "significant at 0.05"."""

    title: str
    value: str
    caption: str = ""


@dataclass(frozen=True)
class AssumptionsSection:
    """The method's assumptions, named but not necessarily verified (see :class:`~src.analysis.
    explanation.Explanation.assumptions`'s own docstring for why "named, not verified").

    A dedicated dataclass rather than reusing :class:`ProseSection` with bullet-joined text: the
    acceptance criterion "renders ... an ``AssumptionsSection``" (see the plan's M22 section)
    means a test needs to assert an ``AssumptionsSection`` instance is present in
    ``sections()``'s output specifically, not merely that *some* prose section happens to
    mention assumptions.
    """

    title: str
    assumptions: tuple[str, ...]


ResultSection = (
    KeyValueSection
    | TableSection
    | FigureSection
    | ProseSection
    | MetricSection
    | AssumptionsSection
)


class BaseResultRenderer(ABC):
    """Abstract base every concrete result renderer inherits from.

    Stateless and classmethod-only -- see this module's own docstring for why this mirrors
    :class:`~src.visualization.base_chart.BaseChart` rather than being instantiated.
    """

    @classmethod
    @abstractmethod
    def title(cls, result: Any) -> str:
        """Short heading for the result -- e.g. "Independent T-Test", "Dataset Profile"."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def headline(cls, result: Any, level: ExpertiseLevel) -> str:
        """One-sentence takeaway, phrased for ``level`` -- e.g. a BEGINNER headline names the
        conclusion in plain language, an ENGINEER headline is terser and may reference the
        statistic directly. Shown above every :class:`ResultSection` in :class:`~src.ui.
        results.result_card.ResultCard`."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def sections(cls, result: Any, level: ExpertiseLevel) -> list[ResultSection]:
        """The result's content, as pure data. ``level`` may change *which* sections appear
        (e.g. a beginner view omitting a technical coefficient table) but never changes what a
        section's own fields mean -- a :class:`MetricSection` always carries an
        already-formatted display value regardless of level."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def help_anchor(cls) -> str:
        """Manual anchor F1 should open when this renderer's card has focus -- read the same
        way :class:`~src.ui.workbench.stage_page.StagePage.help_anchor` is, via
        :func:`~src.ui.a11y.accessible.describe`'s ``help_anchor`` keyword."""
        raise NotImplementedError

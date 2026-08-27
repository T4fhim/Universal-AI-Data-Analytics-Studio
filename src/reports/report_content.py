# File: src/reports/report_content.py
"""The shared, format-independent shape every report exporter renders from.

:class:`ReportContent` plays the same role for :mod:`src.reports` that
a dataframe plays for :mod:`src.visualization`'s
:class:`~src.visualization.base_chart.BaseChart` subclasses: it is the
one input every exporter (PDF, HTML, Word, Excel) accepts, so adding a
fifth format later means writing one new
:class:`~src.reports.base_exporter.BaseReportExporter` subclass, not
teaching :class:`~src.services.report_service.ReportService` a new
output shape. Built by :class:`~src.services.report_service.
ReportService.build_report_content`, which is the module that actually
knows how to read an :class:`~src.services.
analysis_orchestrator_service.AnalysisLog` — this module has no
dependency on that service or on :mod:`src.services` at all, keeping
the same one-way dependency direction (services depend on this
package, not the reverse) that :mod:`src.visualization` keeps with
respect to :mod:`src.services.workspace_service`.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.core.expertise_level import ExpertiseLevel

if TYPE_CHECKING:
    import plotly.graph_objects as go


@dataclass
class ReportSection:
    """One pipeline stage's result, already summarized for rendering.

    One :class:`ReportSection` corresponds to one
    :class:`~src.services.analysis_orchestrator_service.
    AnalysisLogEntry` — :class:`~src.services.report_service.
    ReportService` does the summarizing (turning ``outputs`` into
    ``summary_lines``, resolving a ``visualization_id`` into an actual
    ``figure``) exactly once, so every exporter renders the same
    already-shaped content rather than each re-deriving its own reading
    of the raw log entry.

    Attributes:
        stage_label: Human-readable stage name (e.g. ``"Analyze"``),
            not the raw
            :class:`~src.services.analysis_orchestrator_service.
            PipelineStage` enum member.
        tool_name: Which :mod:`src.ai.tool_registry` tool produced this
            section, or ``None`` for an EXPLAIN entry (which records an
            interpretation directly, not a tool call — see
            :class:`~src.services.analysis_orchestrator_service.
            AnalysisLogEntry`).
        timestamp: ISO 8601 UTC timestamp the stage ran at.
        summary_lines: Plain-text ``"key: value"`` lines describing
            what the stage's tool call produced.
        figure: The visualization this stage produced, if any. ``None``
            both when the stage produced no chart and when it did but
            the visualization has since been closed in
            :class:`~src.services.workspace_service.WorkspaceService`
            (a normal, non-cascading state — see that class's own
            docstring — not an error this dataclass needs to represent
            specially).
        explanation_text: The AI's plain-language interpretation of
            this stage's result, if one was recorded. Empty string for
            every stage except EXPLAIN entries and any other stage a
            caller separately attached an explanation to.
    """

    stage_label: str
    tool_name: str | None
    timestamp: str
    summary_lines: list[str] = field(default_factory=list)
    figure: go.Figure | None = None
    explanation_text: str = ""


@dataclass
class ReportContent:
    """Everything one report needs to render, independent of output format.

    Attributes:
        title: Report title, shown as the document's main heading.
        dataset_name: The source dataset's display name.
        dataset_summary: Plain key/value pairs describing the dataset
            itself (row/column counts, source format, column names) —
            deliberately a plain ``dict`` rather than a full
            :class:`~src.services.workspace_service.Dataset` reference,
            since every exporter only ever needs to display these few
            facts, not the underlying dataframe.
        expertise_level: Which
            :class:`~src.core.expertise_level.ExpertiseLevel` this
            report was generated for. Recorded as display metadata
            only — see :meth:`~src.services.report_service.
            ReportService.build_report_content`'s own docstring for why
            this does not regenerate ``explanation_text`` at a
            different register.
        sections: One :class:`ReportSection` per included pipeline
            stage, in the order they originally ran.
        generated_at: ISO 8601 UTC timestamp this content was
            assembled, defaulted at construction time so callers don't
            need to supply it themselves.
    """

    title: str
    dataset_name: str
    dataset_summary: dict[str, Any]
    expertise_level: ExpertiseLevel
    sections: list[ReportSection] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat()
    )

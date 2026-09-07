# File: uadas_core/reports/__init__.py
"""Report generation: turning a dataset's AnalysisLog into a shareable document.

Milestone 13. Mirrors :mod:`uadas_core.readers`, :mod:`uadas_core.cleaning`, and
:mod:`uadas_core.visualization`: a stateless ``Base*`` extension point
(:class:`~uadas_core.reports.base_exporter.BaseReportExporter`) with one
concrete class per supported output format, plus a shared data shape
(:class:`~uadas_core.reports.report_content.ReportContent`) every exporter
renders from. Assembling a :class:`~uadas_core.reports.report_content.
ReportContent` from a running session's state is
:class:`~uadas_core.services.report_service.ReportService`'s job, not this
package's — this package only knows how to lay out already-assembled
content, the same way :mod:`uadas_core.visualization`'s chart classes only
know how to build a ``Figure`` from a dataframe already handed to them.
"""

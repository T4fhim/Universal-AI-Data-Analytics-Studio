# File: src/reports/__init__.py
"""Report generation: turning a dataset's AnalysisLog into a shareable document.

Milestone 13. Mirrors :mod:`src.readers`, :mod:`src.cleaning`, and
:mod:`src.visualization`: a stateless ``Base*`` extension point
(:class:`~src.reports.base_exporter.BaseReportExporter`) with one
concrete class per supported output format, plus a shared data shape
(:class:`~src.reports.report_content.ReportContent`) every exporter
renders from. Assembling a :class:`~src.reports.report_content.
ReportContent` from a running session's state is
:class:`~src.services.report_service.ReportService`'s job, not this
package's — this package only knows how to lay out already-assembled
content, the same way :mod:`src.visualization`'s chart classes only
know how to build a ``Figure`` from a dataframe already handed to them.
"""

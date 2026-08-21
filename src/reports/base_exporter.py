# File: src/reports/base_exporter.py
"""The shared interface every report format exporter implements.

Same stateless-classmethod shape as :class:`~src.readers.base_reader.
BaseReader`, :class:`~src.cleaning.base_operation.BaseOperation`, and
:class:`~src.visualization.base_chart.BaseChart`: no concrete exporter
is ever instantiated, since each is consumed as a class held in
:mod:`src.services.report_service`'s format registry, not as an
object. Unlike ``BaseOperation.apply`` (which must never mutate its
input), ``export`` has an unavoidable side effect by design — writing
``output_path`` — which is the entire point of a report exporter, so
this base class does not attempt to enforce a "returns new state"
contract the way the cleaning package does.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.reports.report_content import ReportContent


class BaseReportExporter(ABC):
    """Abstract base class every report format exporter inherits from."""

    @classmethod
    @abstractmethod
    def export(cls, report_content: ReportContent, output_path: Path, **kwargs) -> Path:
        """Render ``report_content`` to ``output_path`` in this exporter's format.

        Args:
            report_content: What to render — see
                :class:`~src.reports.report_content.ReportContent`.
            output_path: Where to write the file. The parent directory
                must already exist; exporters do not create
                directories themselves (matching
                :class:`~src.readers.base_reader.BaseReader`'s own
                "does not manage paths beyond reading/writing the one
                it was given" convention).
            **kwargs: Format-specific rendering options. No exporter in
                this package currently accepts any — the parameter
                exists so a future format-specific option (e.g. PDF
                page size) does not require changing this base
                signature.

        Returns:
            ``output_path``, unchanged — lets every call site use the
            same ``path = SomeExporter.export(...)`` idiom regardless
            of which concrete exporter ran.

        Raises:
            ServiceError: If rendering or writing the file fails.
        """
        raise NotImplementedError

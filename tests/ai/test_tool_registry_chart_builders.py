# File: tests/ai/test_tool_registry_chart_builders.py
"""B-4 acceptance test for web-transition 1.3's ``_CHART_BUILDERS`` live fix.

Before 1.3, :mod:`uadas_core.ai.tool_registry` froze a name -> chart-class
snapshot (``_CHART_BUILDERS``) at module import and baked ``build_chart``'s
``chart_type`` enum into the ``TOOLS`` list literal from it. A chart type a
plugin registered during ``bootstrap()`` -- which runs *after* this module is
imported -- therefore never reached the schema the assistant sees, nor
``_build_chart``'s dispatch. These tests pin the fix: both now read the chart
registry live via :func:`uadas_core.ai.tool_registry._chart_builders`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from uadas_core.ai.tool_registry import (
    _build_chart,
    _chart_builders,
    get_anthropic_tool_schemas,
)
from uadas_core.visualization.chart_registry import (
    ChartRegistration,
    register_chart,
    unregister_chart,
)
from uadas_core.visualization.distribution_charts import HistogramChart

_PROBE = "_b4_probe_chart"


@pytest.fixture()
def probe_chart() -> Iterator[str]:
    """Register a chart type the way a plugin would, after tool_registry imported."""
    register_chart(_PROBE, ChartRegistration(HistogramChart, ("column",)))
    try:
        yield _PROBE
    finally:
        unregister_chart(_PROBE)


def test_chart_builders_is_a_live_view_of_the_registry(probe_chart: str) -> None:
    assert probe_chart in _chart_builders()


def test_plugin_chart_reaches_the_build_chart_tool_enum(probe_chart: str) -> None:
    build_chart = next(
        s for s in get_anthropic_tool_schemas() if s["name"] == "build_chart"
    )
    enum = build_chart["input_schema"]["properties"]["chart_type"]["enum"]
    assert probe_chart in enum


def test_get_anthropic_tool_schemas_does_not_mutate_the_shared_tools_entry(
    probe_chart: str,
) -> None:
    from uadas_core.ai.tool_registry import TOOLS

    frozen = next(t for t in TOOLS if t.name == "build_chart")
    _ = get_anthropic_tool_schemas()
    # The live copy must not have written the probe back into the module-level
    # ToolDefinition's own input_schema.
    assert probe_chart not in frozen.input_schema["properties"]["chart_type"]["enum"]


def test_build_chart_handler_dispatches_a_post_import_registered_chart(
    probe_chart: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handler resolves a post-import-registered chart to its builder and calls it.

    Positive-path assertion: the probe is registered with ``HistogramChart``, so
    ``_build_chart`` must look it up live and invoke ``HistogramChart.build`` with
    the dataset's dataframe -- not raise ``Unknown chart_type``.
    """
    import plotly.graph_objects as go

    calls: list[tuple[object, dict[str, object]]] = []
    sentinel = go.Figure()

    def _record(dataframe: object, **kwargs: object) -> go.Figure:
        calls.append((dataframe, kwargs))
        return sentinel

    monkeypatch.setattr(HistogramChart, "build", staticmethod(_record))

    class _StubDataset:
        dataframe = "DATAFRAME_SENTINEL"

    result = _build_chart(_StubDataset(), probe_chart)

    assert result is sentinel
    assert calls == [("DATAFRAME_SENTINEL", {})]

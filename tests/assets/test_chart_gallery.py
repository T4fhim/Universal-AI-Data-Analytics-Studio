# File: tests/assets/test_chart_gallery.py
"""Guards for the web chart gallery (``apps/web/src/charts/gallery-figures.json``).

The gallery draws every chart type the core registers, before and after the Instrument skin.
Three things can drift without any other test noticing: a chart added to the registry that the
gallery has no spec for, the generated figures going stale against the chart classes, and the
generated Plotly template not fitting one of the chart types (Plotly validates a template
against a trace only when it is applied to a figure that has one).
"""

from __future__ import annotations

import importlib.util
import json
import sys

import plotly.graph_objects as go
import pytest

from uadas_core.core.constants import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "build_chart_gallery.py"
GALLERY = PROJECT_ROOT / "apps" / "web" / "src" / "charts" / "gallery-figures.json"
TEMPLATE = PROJECT_ROOT / "assets" / "design-tokens" / "plotly-template.json"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("build_chart_gallery", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_chart_gallery"] = module
    spec.loader.exec_module(module)
    return module


def _document() -> dict:
    return json.loads(GALLERY.read_text(encoding="utf-8"))


def _all_figures() -> dict[str, dict]:
    document = _document()
    return {
        **document["charts"],
        **{f"ref:{k}": v for k, v in document["references"].items()},
    }


def test_gallery_has_exactly_the_registered_charts_and_declared_variants(gen) -> None:
    gen.chart_registry._register_builtins()
    registered = set(gen.chart_registry.list_charts())
    assert set(_document()["charts"]) == registered | set(gen.VARIANTS)
    assert {chart for chart, _, _ in gen.VARIANTS.values()} <= registered


def test_gallery_figures_are_current(gen) -> None:
    assert (
        GALLERY.read_text(encoding="utf-8") == gen.render()
    ), "stale: run python scripts/build_chart_gallery.py"


def test_every_figure_has_data() -> None:
    for name, figure in _all_figures().items():
        assert figure["data"], f"{name} has no traces"


def test_the_template_applies_to_every_chart_type() -> None:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for name, figure in _all_figures().items():
        skinned = go.Figure(figure)
        skinned.update_layout(template=template)  # raises on a property a trace rejects
        assert skinned.layout.template.layout.plot_bgcolor == "#111111", name

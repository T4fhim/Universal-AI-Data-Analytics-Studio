# File: tests/assets/test_design_tokens.py
"""Guards for the Instrument design tokens (``assets/design-tokens/instrument.json``).

Why this exists: the same token source feeds the web CSS, the Plotly template and a
contrast audit (``scripts/build_design_tokens.py``). Four things can silently go wrong
and none would fail a normal test run: a token edit that breaks accessibility contrast, a
generated file that no longer matches its source, CSS that *looks* complete but contains a
broken variable (a duplicate, a self-reference, a ``var()`` with no declaration -- the
browser just falls back to an inherited value), and a variable the existing web shell still
uses disappearing. These tests pin all four, plus the one measured rule the theme is built
on (a region fill is its key colour at 50 % over the pane colour it was measured against).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from collections import Counter

import plotly.graph_objects as go
import pytest

from uadas_core.core.constants import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "build_design_tokens.py"
WEB_SRC = PROJECT_ROOT / "apps" / "web" / "src"
CSS_FILES = (
    "theme/tokens.css",
    "theme/token-page.css",
    "index.css",
    "workbench/workbench.css",
    "components/components.css",
    "components/grid.css",
    "charts/charts.css",
    "workbench/views/views.css",
)

# Fills measured on the reference screenshot (plans/phase-4-design-reference.md, T3), against
# the key colour recovered from its swatch. Prediction error was at most 9 per channel.
MEASURED_FILLS = {
    "red": "#752121",
    "green": "#215721",
    "purple": "#513f63",
    "pink": "#7b4b6f",
    "yellow": "#696927",
}
FILL_TOLERANCE = 9  # per channel; the measurement itself is +-3 on JPEG data


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("build_design_tokens", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_design_tokens"] = module
    spec.loader.exec_module(module)
    return module


def test_every_contrast_pair_passes(gen) -> None:
    src = gen.load_source()
    _, results = gen.build(src)
    bad = gen.failures(results)
    assert (
        bad == []
    ), f"contrast failures: {[(r['pair'], r['ratio'], r['min']) for r in bad]}"
    keys, order = src["region"]["keys"], src["region"]["series_order"]
    assert len(results) == len(src["checks"]) + 2 * len(keys) + len(order)


def test_generated_artefacts_are_current(gen) -> None:
    outputs, _ = gen.build()
    for path, text in outputs.items():
        assert (
            path.is_file()
        ), f"{path} is missing: run python scripts/build_design_tokens.py"
        assert (
            path.read_text(encoding="utf-8") == text
        ), f"{path.name} is stale: run python scripts/build_design_tokens.py"


def test_region_fill_is_the_key_at_half_opacity_over_the_measured_base(gen) -> None:
    src = gen.load_source()
    flat = gen.flatten(src)
    fills = gen.region_fills(src, flat)
    base = flat[src["region"]["fill_over"]]
    assert src["region"]["fill_opacity"] == 0.5
    for name, pair in fills.items():  # exact, not approximate
        assert pair["fill"] == gen.blend(pair["key"], base, 0.5), name
    for name, measured in MEASURED_FILLS.items():  # and close to what the image shows
        got = gen.hex_to_rgb(fills[name]["fill"])
        want = gen.hex_to_rgb(measured)
        assert max(abs(g - w) for g, w in zip(got, want)) <= FILL_TOLERANCE, name


def test_plotly_template_is_valid() -> None:
    template = json.loads(
        (PROJECT_ROOT / "assets" / "design-tokens" / "plotly-template.json").read_text(
            encoding="utf-8"
        )
    )
    fig = go.Figure(layout={"template": template})  # raises on an unknown property
    assert fig.layout.template.layout.plot_bgcolor == "#111111"
    assert len(fig.layout.template.layout.colorway) == 10


def test_css_has_no_duplicate_cyclic_or_undeclared_variables() -> None:
    declared: Counter[str] = Counter()
    used: set[str] = set()
    for name in CSS_FILES:
        text = (WEB_SRC / name).read_text(encoding="utf-8")
        declared.update(re.findall(r"(--[a-z0-9-]+)\s*:", text))
        used |= set(re.findall(r"var\((--[a-z0-9-]+)", text))
        selfref = re.findall(r"(--[a-z0-9-]+)\s*:\s*var\(\1\)", text)
        assert selfref == [], f"{name}: self-referencing variable {selfref}"
    tokens = (WEB_SRC / "theme" / "tokens.css").read_text(encoding="utf-8")
    twice = [
        v
        for v, n in Counter(re.findall(r"(--[a-z0-9-]+)\s*:", tokens)).items()
        if n > 1
    ]
    assert twice == [], f"tokens.css declares twice: {twice}"
    # inline styles in the components can read and set custom properties
    for tsx in WEB_SRC.rglob("*.tsx"):
        text = tsx.read_text(encoding="utf-8")
        used |= set(re.findall(r"var\((--[a-z0-9-]+)", text))
        declared.update(re.findall(r"""['"](--[a-z0-9-]+)['"]\s*:""", text))
    undeclared = sorted(used - set(declared))
    assert undeclared == [], f"var() targets with no declaration: {undeclared}"


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda s: s["region"]["series_order"].pop(), "series_order"),
        (
            lambda s: s["checks"].append(["text.nope", "surface.pane", 4.5]),
            "unknown token",
        ),
        (lambda s: s["region"].update({"fill_over": "surface.nope"}), "unknown token"),
    ],
)
def test_validate_rejects_a_source_that_would_emit_a_wrong_palette(
    gen, edit, message
) -> None:
    src = copy.deepcopy(gen.load_source())
    edit(src)
    with pytest.raises(ValueError, match=message):
        gen.validate(src, gen.flatten(src))

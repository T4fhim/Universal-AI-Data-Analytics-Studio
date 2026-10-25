---
name: dataviz-development
description: DORMANT until the Phase 4 web UI exists — do not auto-trigger; there is no UI or chart-rendering layer in this repo to apply it to (the Qt desktop UI was removed in Phase 2.5). Holds the repository's chart-implementation conventions (BaseChart contract, chart families, categorical cardinality, visualization lineage) for when web chart rendering is built; to add a BaseChart implementation today use the add-extension skill.
---

# Data Visualization Development

> **DORMANT.** The Qt/PySide6 UI this skill was written alongside was removed in Phase 2.5 (the last
> commit containing it is `8d3ec4d`), and no UI exists until the Phase 4 web UI. The `BaseChart`
> conventions below still describe `uadas_core/visualization/` accurately, but the rendering
> boundary (previously `pyside6-development`) has no current implementation: the surviving chart
> host page and bridge contract are in `assets/ui-contract/ui-behaviour-rules.md` ("Chart bridge")
> and `resources/web/chart_host.html` / `chart_bridge.js`.

This skill contains only visualization conventions specific to this repository.

For general chart design, chart selection, color, accessibility, and visual
communication, use Claude Code's built-in `dataviz` skill.

For displaying Plotly figures in a UI, see `assets/ui-contract/ui-behaviour-rules.md` ("Chart
bridge"); the Qt rendering layer it was written for is gone.

## BaseChart Contract

Concrete charts belong under:

`uadas_core/visualization/`

They should follow the project's `BaseChart` architecture.

Before modifying or adding a chart:

1. Inspect `uadas_core/visualization/base_chart.py`.
2. Subclass `BaseChart`.
3. Preserve the project's classmethod/stateless chart pattern.
4. Return a Plotly `go.Figure`.
5. Validate required columns using the existing shared validation mechanism.
6. Preserve the project's exception conventions for invalid or unchartable
   input.

Do not introduce a parallel chart abstraction or wrapper around Plotly figures
without an architectural reason.

## Chart Family Organization

Keep chart implementations organized by visualization/data family.

Existing locations include:

- `uadas_core/visualization/categorical_charts.py`
- `uadas_core/visualization/continuous_charts.py`
- `uadas_core/visualization/distribution_charts.py`
- `uadas_core/visualization/dashboard_renderer.py`

Prefer adding a chart to the existing appropriate family rather than creating
one module per chart class.

Inspect the existing neighboring implementations before introducing a new
pattern.

## Categorical Cardinality

The categorical chart implementation uses:

`_MAX_CATEGORIES = 15`

High-cardinality categorical data is grouped into an `"Other"` category using
the existing preparation logic.

This is a deliberate readability convention, not a universal statistical
rule.

When adding another categorical visualization that has the same high-
cardinality problem:

- reuse the existing preparation logic where applicable
- preserve the 15-category convention
- do not silently introduce a different cutoff

If a new visualization genuinely requires different behavior, document the
reason rather than creating an unexplained second threshold.

## Visualization Lineage

The project's visualization model records information about how a
visualization was created.

Relevant fields include:

- `Visualization.chart_type`
- `Visualization.chart_parameters`

These are intended to preserve enough information to understand or rebuild a
visualization against updated data.

When wiring a newly created chart into the workspace layer:

- populate the chart type appropriately
- preserve the parameters used to construct it
- inspect `uadas_core/services/workspace_service.py` and existing call sites before changing the
  representation

Do not discard chart construction metadata simply because no consumer
currently uses every field.

## Plotly Rendering Boundary

This skill stops at producing a valid Plotly figure.

It does not define how the figure is rendered in a UI; no rendering layer exists
until the Phase 4 web UI. The recorded contract for the surviving chart host page
(load it once, then push every figure/theme update through `Plotly.newPlot` /
`react` / `relayout`, never a new page load per chart) is in
`assets/ui-contract/ui-behaviour-rules.md`, section "Chart bridge".

## Design Boundary

Do not duplicate the general visualization methodology supplied by the
built-in `dataviz` skill.

That includes:

- general chart-selection heuristics
- color guidance
- accessibility guidance
- visual hierarchy
- interaction design
- general data-storytelling principles

Use the built-in skill for those decisions.

This skill only defines repository-specific implementation conventions.

## Verification

When adding or modifying a chart:

1. Inspect the relevant existing chart family first.
2. Confirm the `BaseChart` contract is preserved.
3. Check categorical-cardinality behavior where applicable.
4. Confirm required columns are validated.
5. Confirm the returned object is a Plotly `go.Figure`.
6. Check visualization metadata when integrating with the workspace layer.
7. Run applicable tests (`python -m pytest tests/visualization -q`).
8. Invoke `milestone-verification` when the change constitutes a milestone or
   substantial feature.

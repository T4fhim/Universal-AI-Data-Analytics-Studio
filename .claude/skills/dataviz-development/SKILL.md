---
name: dataviz-development
description: Project-specific visualization development rules for Universal AI Data Analytics Studio. Use when adding or modifying BaseChart implementations, categorical/continuous/distribution charts, Plotly figures, or visualization workspace integration.
---

# Data Visualization Development

This skill contains only visualization conventions specific to this repository.

For general chart design, chart selection, color, accessibility, and visual
communication, use Claude Code's built-in `dataviz` skill.

For displaying Plotly figures inside PySide6/QWebEngineView, use the
`pyside6-development` skill.

## BaseChart Contract

Concrete charts belong under:

`src/visualization/`

They should follow the project's `BaseChart` architecture.

Before modifying or adding a chart:

1. Inspect `src/visualization/base_chart.py`.
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

- `src/visualization/categorical_charts.py`
- `src/visualization/continuous_charts.py`
- `src/visualization/distribution_charts.py`
- `src/visualization/dashboard_renderer.py`

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
- inspect `workspace_service.py` and existing call sites before changing the
  representation

Do not discard chart construction metadata simply because the current UI does
not yet use every field.

## Plotly Rendering Boundary

This skill stops at producing a valid Plotly figure.

It does not define how the figure is rendered inside the desktop application.

For:

- `QWebEngineView`
- temporary HTML files
- `setUrl()`
- Qt widget lifecycle
- chart dock integration

use `pyside6-development`.

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
7. Run applicable tests or manual verification.
8. For UI-integrated chart changes, invoke `milestone-verification` when the
   change constitutes a milestone or substantial feature.

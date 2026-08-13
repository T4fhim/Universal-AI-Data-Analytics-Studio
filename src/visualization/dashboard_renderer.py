# File: src/visualization/dashboard_renderer.py
"""Combines a Dashboard's tiles into a single multi-chart figure.

Uses ``plotly.subplots.make_subplots`` to build one grid figure from
several independently-built figures — each tile's traces are copied
into the corresponding subplot cell. This is a genuinely different
operation from anything in milestone 5a: those chart builders each
produce one complete, standalone figure; this combines several
already-built figures' *traces* into a shared grid, which needs
different Plotly machinery entirely.

A tile whose visualization was closed after the dashboard was created
(see :meth:`~src.services.workspace_service.WorkspaceService.
get_dashboard_tiles`'s own docstring for why this can happen) is
skipped with an empty, labeled placeholder cell rather than causing
the whole render to fail — one missing chart should not make an
otherwise-intact dashboard unusable.
"""

from __future__ import annotations

from plotly.subplots import make_subplots

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.services.workspace_service import Dashboard

_logger = get_logger(__name__)


def render_dashboard(
    dashboard: Dashboard,
    resolved_tiles: list[tuple],
):
    """Render ``dashboard`` into one combined Plotly figure.

    Args:
        dashboard: The dashboard being rendered.
        resolved_tiles: The result of
            :meth:`~src.services.workspace_service.WorkspaceService.
            get_dashboard_tiles` — ``(DashboardTile, Visualization |
            None)`` pairs. Passed in rather than resolved internally,
            since resolving them requires a
            :class:`~src.services.workspace_service.WorkspaceService`
            instance and this function is pure rendering logic with no
            other reason to depend on that service.

    Raises:
        ServiceError: If ``dashboard`` has no tiles at all.
    """
    if not dashboard.tiles:
        raise ServiceError(
            f"Dashboard '{dashboard.name}' has no tiles to render."
        )

    max_row = max(t.row for t, _viz in resolved_tiles)
    max_col = max(t.column for t, _viz in resolved_tiles)
    row_count = max_row + 1
    col_count = max_col + 1

    subplot_titles = [""] * (row_count * col_count)
    for tile, visualization in resolved_tiles:
        grid_index = tile.row * col_count + tile.column
        subplot_titles[grid_index] = (
            visualization.name if visualization else "(visualization closed)"
        )

    combined = make_subplots(
        rows=row_count,
        cols=col_count,
        subplot_titles=subplot_titles,
    )

    skipped_count = 0
    for tile, visualization in resolved_tiles:
        if visualization is None:
            skipped_count += 1
            continue
        for trace in visualization.figure.data:
            combined.add_trace(trace, row=tile.row + 1, col=tile.column + 1)

    combined.update_layout(title=dashboard.name, showlegend=False)

    _logger.info(
        "Rendered dashboard '%s': %d tile(s), %d skipped (closed visualization).",
        dashboard.name,
        len(dashboard.tiles),
        skipped_count,
    )

    return combined

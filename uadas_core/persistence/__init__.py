# File: uadas_core/persistence/__init__.py
"""Workspace persistence: the save/load round-trip for datasets, visualizations,
and dashboards.

New in web-transition Phase 1.6. It exists because
:func:`uadas_core.services.project_service.ProjectService.record_datasets`
persists only ``{name, source_path}`` per dataset and *explicitly drops derived
datasets* (a derived frame has no ``source_path`` to re-read from) — so a
project with cleaned/transformed data could not be reopened intact. This
package closes that gap with a serialization layer that sits *alongside*
:class:`~uadas_core.services.workspace_service.WorkspaceService` rather than
inside it.

:class:`~uadas_core.persistence.persistence_service.PersistenceService` is a
stateless ``bootstrap()`` singleton whose two verbs
(``save_workspace`` / ``load_workspace``) take and return plain data, so the
desktop shell's ``ProjectController`` can run them on a worker thread without
touching the non-thread-safe live :class:`WorkspaceService`; state is installed
back into that singleton on the UI thread via
:meth:`WorkspaceService.load_snapshot`. Figures are never stored — they are
re-derived on load through :mod:`uadas_core.visualization.chart_registry`,
because a figure is a pure function of (frame + params) and persisting one only
creates stale-figure bugs.

Qt-free by construction (``lint-imports`` contract
``uadas-core-qt-and-framework-free``); it imports ``chart_registry`` directly,
with no injection seam.
"""

from __future__ import annotations

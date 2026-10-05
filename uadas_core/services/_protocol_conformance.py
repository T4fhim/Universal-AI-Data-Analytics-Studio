# File: uadas_core/services/_protocol_conformance.py
"""Static proof that the concrete core types satisfy the Protocols that replaced them.

Why this exists: the core session seam removed two import-linter exemptions by typing
collaborators as Protocols instead of importing the concrete classes --
:class:`~uadas_core.ai.assistant_service.AssistantWorkspace` (what ``AssistantService``
needs from a workspace) and :class:`~uadas_core.core.application_state.ProjectLike` /
``DatasetLike`` / ``VisualizationLike`` (what ``ApplicationState`` holds). A Protocol is
only checked where something is *assigned* to it, and no production module assigns a
``WorkspaceService`` to an ``AssistantWorkspace`` (callers elsewhere do, outside the CI
mypy scope), so without this module a drift -- renaming ``add_dataset``, dropping
``Dataset.dataset_id`` -- would pass CI silently and fail at runtime.

Nothing here runs: the whole body sits under ``TYPE_CHECKING`` so the module has no
import-time effect, and ``mypy`` (this package is in CI's clean-package list) fails the
build if any assignment below stops type-checking. It lives in ``services`` because that
layer may import ``ai``, ``models`` and ``core`` -- the three packages involved.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uadas_core.ai.assistant_service import AssistantWorkspace
    from uadas_core.core.application_state import (
        ApplicationState,
        DatasetLike,
        ProjectLike,
        VisualizationLike,
    )
    from uadas_core.models import Dataset, Project, Visualization
    from uadas_core.services.workspace_service import WorkspaceService

    def _conformance(
        workspace: WorkspaceService,
        dataset: Dataset,
        project: Project,
        visualization: Visualization,
        state: ApplicationState,
    ) -> None:
        # The assistant's view of a workspace.
        _assistant_workspace: AssistantWorkspace = workspace
        # What ApplicationState holds, assigned both ways it is used (set and get).
        _dataset_like: DatasetLike = dataset
        _project_like: ProjectLike = project
        _visualization_like: VisualizationLike = visualization
        state.set_active_dataset(dataset)
        state.set_active_project(project)
        state.set_active_visualization(visualization)

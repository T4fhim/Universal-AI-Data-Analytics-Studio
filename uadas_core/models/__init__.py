# File: uadas_core/models/__init__.py
"""The Qt-free, service-free value types the rest of uadas_core is built on.

Extracted in the desktop->web transition's Phase 2.2 (D1) from
:mod:`uadas_core.services.workspace_service` (:class:`Dataset`,
:class:`Visualization`, :class:`DashboardTile`, :class:`Dashboard`) and
:mod:`uadas_core.services.project_service` (:class:`Project`) -- these were
plain dataclasses with no service-layer behaviour, stranded in the services
layer only because that is where the service that manages them happened to
live. Pulling them out is what lets ``uadas_core.core`` sit at the bottom of
the layered-import stack (Phase 2.3's ``layers`` contract): a type used by
:mod:`uadas_core.core.application_state` no longer forces ``core`` to import
``services``.

Every call site imports from **this package**, e.g. ``from uadas_core.models
import Dataset`` -- never ``uadas_core.models.workspace`` or
``uadas_core.models.project`` directly -- so a future split of either file
into more of them stays invisible to every importer, and the ``layers``
contract sees one clean ``<caller> -> uadas_core.models`` edge rather than
two.
"""

from __future__ import annotations

from uadas_core.models.project import Project
from uadas_core.models.workspace import Dashboard, DashboardTile, Dataset, Visualization

__all__ = ["Dashboard", "DashboardTile", "Dataset", "Project", "Visualization"]

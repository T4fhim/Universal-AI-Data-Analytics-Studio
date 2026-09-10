---
title: "Save Project"
anchors:
  - project/save
---

# Save Project

**File > Save Project**, or **Ctrl+S**. Enabled only when a project is open.

Writes the active project's current state to its existing file path
(`uadas_core.services.project_service.ProjectService.save_project`): every loaded dataset's name and
source path (see [New Project](new.md) for what is and is not stored), and each dataset's
recorded analysis log, so a later [Open Project](open.md) restores exactly what had already
run against it.

If the active project has never been saved before (it has no path yet -- true immediately
after [New Project](new.md)), this behaves exactly like [Save As](save-as.md): a file dialog
asks where to save it.

## Autosave

If enabled in [Settings](../settings.md), the application also saves the active project
automatically at a configurable interval, using this exact same save path -- autosave never
prompts for a filename, so it only takes effect once a project has already been saved at least
once manually. Autosave is silent when there is nothing to save (no open project, or a project
that has never been given a path) rather than interrupting you with a dialog on a timer.

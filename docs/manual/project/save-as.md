---
title: "Save Project As"
anchors:
  - project/save-as
---

# Save Project As

**File > Save Project As...**, or **Ctrl+Shift+S**. Enabled only when a project is open.

Prompts for a destination `*.uads.json` file and saves the active project there
(`uadas_core.services.project_service.ProjectService.save_project` with an explicit path), the same
content [Save](save.md) writes. The chosen path becomes the project's path going forward --
a subsequent plain **Save** writes to this new location, not the old one.

The saved file is added to **File > Open Recent**.

See [New Project](new.md) for exactly what is (and is not) included in the saved file --
in particular, datasets produced by a cleaning operation rather than loaded from a file are
named in a warning dialog if any are skipped.

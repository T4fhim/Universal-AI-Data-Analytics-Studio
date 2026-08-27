---
title: "Open Project"
anchors:
  - project/open
---

# Open Project

**File > Open Project...**, or **Ctrl+O**.

Loads a `*.uads.json` project file (`src.services.project_service.ProjectService.open_project`)
and makes it the active project. Every dataset recorded in the file is then re-read from its
original source path and added to the workspace -- this happens on a background worker thread,
so the window stays responsive while several files are re-read.

## What can go wrong, and what you'll see

- If the project file itself is missing, unreadable, or not valid JSON, a dialog names the
  problem and nothing changes -- the previously active project (if any) is left alone.
- If a recorded dataset's source file has moved, been deleted, or now has more than one table
  (for a multi-table format -- see [readers](../data/open-dataset.md) -- which was not
  recorded, since a project only stores a path, not which table was previously selected within
  it), that dataset is skipped and named in a warning dialog once the rest have loaded. The
  project still opens.

Opening a project also restores its previously recorded analysis log for each dataset (which
pipeline stages have already run against it), so the workbench's stage rail and guidance panel
reflect real prior work rather than starting blank.

The **File > Open Recent** submenu lists previously opened projects by path for quick re-access
without a file dialog.

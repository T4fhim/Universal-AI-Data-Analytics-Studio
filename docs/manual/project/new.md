---
title: "New Project"
anchors:
  - project/new
---

# New Project

**File > New Project**, or **Ctrl+N**.

Creates a fresh, empty project (`src.services.project_service.ProjectService.new_project`) and
makes it the active project. The new project has no path on disk yet -- it exists only in
memory until you save it (see [Save](save.md) and [Save As](save-as.md)); if you close the
application without saving, it is discarded.

A new project has no datasets. The workbench stays on the Welcome page (it only switches to a
pipeline stage once a *dataset* is active, not merely a project) -- use
[Open Dataset](../data/open-dataset.md) or
[Connect to Database](../data/connect-database.md) next.

## What a project actually stores

A project file (`*.uads.json`) is metadata, not a copy of your data: the project's name, and
for each dataset that was loaded from a file, its display name and source file path. When you
reopen a project, each recorded dataset is re-read from its original source path -- if that
file has moved or changed, reloading will fail or produce different data, since nothing about
the file's original contents is embedded in the project itself.

Datasets produced by a cleaning operation (not loaded directly from a file) have no source
path and are **not** included in a saved project -- saving warns you by name which datasets
were left out, rather than silently dropping them.

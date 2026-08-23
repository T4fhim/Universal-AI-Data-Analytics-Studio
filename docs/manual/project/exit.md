---
title: "Exit"
anchors:
  - project/exit
---

# Exit

**File > Exit**, or **Ctrl+Q**.

Closes the main window. Before doing so, the application detaches the logging panel's log
handler and closes every live database connection opened this session
(`src.services.database_connection_service.DatabaseConnectionService.close_all_connections`).

This action does not prompt to save an open project with unsaved changes -- there is currently
no "unsaved changes" tracking in the project model to prompt from. If autosave is enabled (see
[Settings](../settings.md)), your most recent changes since the last autosave interval may
still be lost on exit; save manually first ([Save](save.md)) if you want to be certain.

Deliberately excluded from the command palette (see [the AI layer](../ai/overview.md)'s
sibling, the command palette, opened with **Ctrl+K**): a fuzzy-search palette mis-click quitting
the whole application is a disproportionate risk that a deliberate **File > Exit** menu
navigation does not carry.

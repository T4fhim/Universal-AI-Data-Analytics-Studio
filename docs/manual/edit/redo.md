---
title: "Redo"
anchors:
  - edit/redo
---

# Redo

**Edit > Redo**, or **Ctrl+Y**. Enabled only immediately after an [Undo](undo.md), before any
new cleaning operation is applied.

Re-applies the most recently undone cleaning operation via `src.ui.command_stack.CommandStack`,
switching the active dataset forward to the derived dataset undo had stepped back from. Applying
a *new* cleaning operation after an undo clears the redo history, the same convention any
standard undo/redo stack follows -- there is no branching history to redo into more than one
possible "forward."

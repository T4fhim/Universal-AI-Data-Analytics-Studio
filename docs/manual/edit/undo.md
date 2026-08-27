---
title: "Undo"
anchors:
  - edit/undo
---

# Undo

**Edit > Undo**, or **Ctrl+Z**. Enabled only when there is a cleaning operation to undo.

Reverts the most recently applied [cleaning operation](../pipeline/clean.md) via
`src.ui.command_stack.CommandStack`. Because cleaning operations never mutate a dataset in
place -- every operation returns a new, derived `Dataset` and leaves the original untouched --
"undo" here means switching the active dataset back to the parent it was derived from, not
reverting in-place edits. The derived dataset is not deleted; it simply stops being active,
and remains reachable via the dataset lineage view on the Clean stage page if you want to
return to it without redoing the operation.

This history is per-session, not saved with the project: reopening a project does not restore
an undo/redo stack, only the datasets and analysis log that already existed at save time.

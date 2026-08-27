---
title: "Drop Missing Values"
anchors:
  - cleaning.drop_missing_values
---

# Drop Missing Values

`src.cleaning.missing_values.DropMissingValues`.

Removes rows containing a missing value, in the columns you specify -- or in **any** column if
none are specified, matching pandas' own `dropna()` default so the common "just clean up
everything" case does not require enumerating every column name.

Like every cleaning operation, this never modifies your dataset in place: it returns a new,
derived dataset. See [the Clean stage](../pipeline/clean.md) for what that means in practice
(before/after comparison, lineage, undo/redo).

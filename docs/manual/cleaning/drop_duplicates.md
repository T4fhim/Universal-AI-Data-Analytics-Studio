---
title: "Drop Duplicates"
anchors:
  - cleaning.drop_duplicates
---

# Drop Duplicates

`src.cleaning.duplicates.DropDuplicates`.

Removes duplicate rows, considering the columns you specify -- or every column if none are
specified (two rows are duplicates only if every column matches, matching pandas' own
`drop_duplicates()` default). Always keeps the **first** occurrence of each duplicate group;
this is not currently configurable.

The [Dataset Profile](../results/dataset_profile.md) from the Understand stage reports a
duplicate row count up front, so you know whether this operation is worth running before you
run it.

Like every cleaning operation, this returns a new, derived dataset rather than modifying yours
in place. See [the Clean stage](../pipeline/clean.md).

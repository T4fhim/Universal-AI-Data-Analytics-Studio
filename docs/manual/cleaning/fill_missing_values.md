---
title: "Fill Missing Values"
anchors:
  - cleaning.fill_missing_values
---

# Fill Missing Values

`src.cleaning.missing_values.FillMissingValues`.

Replaces missing values with a fill value you supply, in the columns you specify -- or every
column if none are specified.

The fill value is applied as-is, with **no type coercion**: filling a numeric column with a
text value is permitted and will produce a mixed-type column -- avoiding that is your
responsibility, the same way a reader reports a mixed-type column rather than silently
correcting it.

Like every cleaning operation, this returns a new, derived dataset rather than modifying yours
in place. See [the Clean stage](../pipeline/clean.md).

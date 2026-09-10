---
title: "Convert Type"
anchors:
  - cleaning.convert_type
---

# Convert Type

`uadas_core.cleaning.type_conversion.ConvertType`.

Converts a column's data type -- the direct follow-up to any reader's ambiguous-type warning
(see [Open Dataset](../data/open-dataset.md) and [Dataset Profile](../results/dataset_profile.md)):
every reader can report that a column has an ambiguous type, but none of them attempt to fix
it. This operation is where that fix lives. Target types: `numeric`, `integer`, `string`,
`boolean`, `datetime`.

**Failed conversions are never silent.** Converting a value that cannot be parsed as the target
type produces a missing value there (matching pandas' own "coerce" behavior), but this
operation always reports exactly how many values failed and, when there are few enough to be
genuinely useful in a message, samples what they actually were -- a result showing "0 values
failed" and a result silently discarding twelve of them look identical unless the operation
says which happened.

Like every cleaning operation, this returns a new, derived dataset rather than modifying yours
in place. See [the Clean stage](../pipeline/clean.md).

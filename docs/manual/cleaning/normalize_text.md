---
title: "Normalize Text"
anchors:
  - cleaning.normalize_text
---

# Normalize Text

`src.cleaning.text_normalization.NormalizeText`.

Trims leading/trailing whitespace (on by default) and optionally normalizes casing (`lower`,
`upper`, or `title` -- each word capitalized; unchanged by default) in the columns you specify.

**Columns are required here** -- unlike the other cleaning operations, this one does not
default to "all columns" or attempt to auto-detect which columns are text. A column with an
`object`/string dtype is not reliably "meant to be text": readers can assign that dtype to
columns that are actually ambiguous numeric data (see any reader's ambiguous-type warning).
Silently applying case normalization to a column you did not intend to treat as text is a real
risk of corrupting data in a way that would not be immediately obvious, so this operation makes
its scope an explicit choice rather than a heuristic guess.

Like every cleaning operation, this returns a new, derived dataset rather than modifying yours
in place. See [the Clean stage](../pipeline/clean.md).

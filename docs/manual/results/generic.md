---
title: "Generic Result"
anchors:
  - results.generic
---

# Generic Result

The fallback result card, shown for a result type with no dedicated renderer registered. Two
real cases handle most of what reaches it, rather than every unrecognized shape falling through
to raw text:

- **A plain table** ([Aggregate](../pipeline/explore.md) and
  [Cross-tabulate](../pipeline/explore.md) have no dedicated result dataclass of their own --
  both return a plain data table, which this renderer turns into a real table section.)
- **A plain key/value mapping** -- shown as a simple list of labeled values.

Anything else falls back to a plain-text display of the result's own representation. This
renderer is deliberately unpolished for that last case rather than raising an error: a result
card that can never fail to render *something* is what lets the rest of the result-rendering
system guarantee it never crashes on an unexpected result type.

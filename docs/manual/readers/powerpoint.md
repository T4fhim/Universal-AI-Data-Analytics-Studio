---
title: "PowerPoint Reader"
anchors:
  - readers.powerpoint
---

# PowerPoint Reader

`src.readers.powerpoint_reader.PowerPointReader` -- `.pptx`.

Multi-table, like [the Excel reader](excel.md), but the "tables" here are PowerPoint table
shapes scattered across slides rather than worksheets -- a deck can have zero, one, or many
table shapes on any slide, so every slide is scanned once to enumerate them, rather than
assuming a fixed structure the way a workbook's sheet list is fixed.

Each table's first row is assumed to be its header, the same convention
[the Excel reader](excel.md) uses, with the same documented limitation: a title row above the
real header is not detected.

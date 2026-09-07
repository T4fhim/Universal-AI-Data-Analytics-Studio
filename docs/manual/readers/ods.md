---
title: "OpenDocument Spreadsheet Reader"
anchors:
  - readers.ods
---

# OpenDocument Spreadsheet Reader

`uadas_core.readers.ods_reader.OdsReader` -- `.ods`.

Same multi-table shape as [the Excel reader](excel.md) (one sheet per read) -- the two formats
differ only in container format, not in the "workbook with one or more worksheets" concept, so
this reader reuses pandas' own `read_excel`/`ExcelFile` entry points with the ODF engine rather
than reimplementing sheet enumeration.

Deliberately does **not** attempt the Excel reader's merged-cell detection: that used
`openpyxl`, which cannot open `.ods` files, and ODS's own merged-region API differs enough that
duplicating that detection for a much less common format was judged not worth the added
surface area.

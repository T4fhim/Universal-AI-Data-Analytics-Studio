---
title: "HTML Reader"
anchors:
  - readers.html
---

# HTML Reader

`src.readers.html_reader.HtmlReader` -- `.html`, `.htm`.

Multi-table, the same conceptual shape as [the Excel reader](excel.md), except the "tables"
here are whichever `<table>` elements `pandas.read_html` finds in the document (backed by
`lxml`/`beautifulsoup4`) -- an arbitrary HTML page can have zero, one, or many, in no particular
structure the way a workbook's sheet list has.

Each table's first row is assumed to be its header, matching `pandas.read_html`'s own default
and this application's header-row convention elsewhere.

---
title: "Excel Reader"
anchors:
  - readers.excel
---

# Excel Reader

`src.readers.excel_reader.ExcelReader` -- `.xlsx`, `.xls`.

Multi-table: an Excel workbook can contain more than one worksheet, each a candidate table --
you are asked which sheet to load if there is more than one.

## Two situations handled explicitly

- **Merged cells.** In a merged cell block, Excel stores the value only in the top-left cell;
  every other cell in the block reads as empty. This is standard spreadsheet authoring, not
  corrupted data -- but it produces a column or row of missing values that could be mistaken for
  genuinely missing data. This reader detects merged regions and records a warning naming which
  are present, without attempting to "fix" the shape by forward-filling values -- that would be
  a content-altering judgment call for a cleaning operation to make, not a reader.
- **Header row assumption.** Row 1 of the selected sheet is assumed to be the header row,
  matching pandas' own default. A spreadsheet with a title row, a blank row, or other content
  before the real header is not detected automatically -- the resulting dataset will have
  columns named after whatever was actually in row 1, which is honest, inspectable behavior
  rather than a silent misread.

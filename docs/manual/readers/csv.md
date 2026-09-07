---
title: "CSV / TSV Reader"
anchors:
  - readers.csv
---

# CSV / TSV Reader

`uadas_core.readers.csv_reader.CsvReader` -- `.csv`, `.tsv`.

Handles the general "delimited text" case, not just literal comma-separated files: the
delimiter is detected via Python's `csv.Sniffer` rather than assumed to be a comma, so a
tab-separated or semicolon-separated file (both common exports from regional spreadsheet
software) is read correctly rather than parsed as one giant unsplit column.

## Warnings, not hard failures

- **Rows with the wrong field count.** A row with too few or too many fields compared to the
  header is skipped, and the number of skipped rows is recorded as a warning -- rather than
  either silently succeeding with misaligned data, or refusing to load an otherwise-good file
  over a handful of bad rows.
- **Ambiguous-type columns.** A column pandas could not confidently infer a single type for
  (mixed numeric and text values) is recorded as a warning naming the column, so you know it
  may need [Convert Type](../cleaning/convert_type.md), rather than this reader silently
  guessing what the "right" type was.

Single-table: a CSV/TSV file has no worksheet or sheet concept, so there is nothing to choose
between after opening it.

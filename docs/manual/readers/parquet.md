---
title: "Parquet Reader"
anchors:
  - readers.parquet
---

# Parquet Reader

`uadas_core.readers.parquet_reader.ParquetReader` -- `.parquet`.

Single-table, and unusually simple: Parquet is a typed, columnar format with no
encoding-detection or delimiter-sniffing concern like [the CSV reader](csv.md)'s, and no
header-row ambiguity like [the Excel reader](excel.md)'s -- the file's own embedded schema is
authoritative. `pandas.read_parquet` picks whichever of `pyarrow`/`fastparquet` is available
automatically.

---
title: "Feather Reader"
anchors:
  - readers.feather
---

# Feather Reader

`uadas_core.readers.feather_reader.FeatherReader` -- `.feather`.

Single-table, and as simple as [the Parquet reader](parquet.md) for the same reason: Feather is
also a typed, columnar format backed by `pyarrow` with an authoritative embedded schema and no
encoding/delimiter ambiguity to resolve.

---
title: "JSON Reader"
anchors:
  - readers.json
---

# JSON Reader

`src.readers.json_reader.JsonReader` -- `.json`.

JSON does not guarantee tabular structure the way a CSV file's rows and columns do. This
reader handles three shapes, in order of how directly tabular they are:

1. **A JSON array of flat objects** -- `[{"a": 1, "b": 2}, ...]` -- the direct tabular case.
   Each object becomes a row, each key a column.
2. **A single JSON object with array-valued keys of equal length** --
   `{"a": [1, 2, 3], "b": [4, 5, 6]}` -- the "columnar" shape some tools export.
3. **A JSON array of nested objects** -- objects containing objects or arrays as values --
   flattened via `pandas.json_normalize`, which turns nested keys into dotted column names
   (`address.city`, `address.zip`).

A document that is none of the above (a single non-array, non-columnar object; a deeply
irregular array where objects have wildly different shapes) is rejected with a message
describing what was found, rather than forced into a table that was never meant to be one.

Single-table.

---
title: "Text Reader"
anchors:
  - readers.text
---

# Text Reader

`uadas_core.readers.text_reader.TextReader` -- `.txt`.

A `.txt` file has no inherent tabular structure. This reader handles the two situations that
actually occur in practice, honestly rather than forcing every text file into the same shape:

1. **A delimited file with a `.txt` extension.** Checked first, using the same delimiter
   sniffing [the CSV reader](csv.md) uses -- if a consistent delimiter is detected across the
   file, the CSV reader handles it entirely, since at that point it *is* a CSV file in every
   way that matters.
2. **Genuinely unstructured text** -- prose, logs, a single column of values with no consistent
   delimiter. No fake structure is invented here: the result is a single-column dataset where
   each row is one line of the file, a real and useful representation (filter, search, or count
   lines against it) rather than a rejection dressed up as success.

Single-table.

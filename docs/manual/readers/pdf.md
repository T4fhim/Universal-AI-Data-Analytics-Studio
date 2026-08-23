---
title: "PDF Reader"
anchors:
  - readers.pdf
---

# PDF Reader

`src.readers.pdf_reader.PdfReader` -- `.pdf`.

A genuinely different kind of reader from the format-native ones: a PDF is a page-layout
format that may contain zero, one, or many tables embedded among arbitrary prose and images.
This reader's job is table *extraction*, not simple parsing -- **finding zero tables in a
text-only PDF is a normal, valid outcome, not an error.**

Uses `camelot-py`, purpose-built for table extraction, with two backends:

- **Lattice** -- uses a PDF's visible grid lines to locate table boundaries precisely; requires
  Ghostscript (a system-level dependency not assumed to be installed).
- **Stream** -- infers table boundaries from whitespace alignment; no Ghostscript dependency,
  but measurably less precise -- testing found it can sweep nearby non-tabular text (a document
  title sitting directly above a table) into the extracted result as spurious rows.

This reader tries lattice first and falls back to stream only if lattice is unavailable or
finds nothing, preferring the more precise result whenever it can be produced.

Multi-table; zero tables found is valid, not an error.

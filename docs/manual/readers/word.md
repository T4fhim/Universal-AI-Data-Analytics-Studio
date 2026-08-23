---
title: "Word Reader"
anchors:
  - readers.word
---

# Word Reader

`src.readers.word_reader.WordReader` -- `.docx`.

Faces the same fundamental problem as [the PDF reader](pdf.md) -- a document may contain zero,
one, or many tables embedded among prose -- but the extraction itself is more straightforward:
`python-docx` exposes a document's tables as an already-parsed list directly, with no
whitespace-guessing and no risk of misreading ordinary paragraph text as a table.

Same conventions as other multi-table readers in this application:

- **Zero tables is a valid, non-error outcome** -- a prose-only document is not malformed.
- **Row 1 is assumed to be the header row** -- nothing in a Word table's structure reliably
  marks a row as a header (Word's own "repeat as header row" print-pagination hint is a
  formatting choice, not dependably set).

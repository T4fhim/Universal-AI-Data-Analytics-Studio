---
title: "Archive Reader"
anchors:
  - readers.archive
---

# Archive Reader

`uadas_core.readers.archive_reader.ArchiveReader` -- `.zip`, `.gz`, `.gzip`.

Not a format in its own right the way every other reader is -- a ZIP or GZIP file's actual
tabular content is whatever format is *inside* it. This reader's real job is decompressing to a
temporary location and then delegating to the same reader-selection logic
[Open Dataset](../data/open-dataset.md) uses for a plain file, rather than reimplementing
CSV/JSON/Excel/etc. parsing a second time.

- **ZIP archives** are multi-table: one "table" per inner file this reader can find an
  appropriate reader for. An unreadable inner file (say, an `.exe` bundled alongside a `.csv`)
  is silently excluded from the table list rather than failing the whole archive.
- **GZIP files** are single-table by construction -- gzip compresses exactly one stream, so
  there is nothing to enumerate.

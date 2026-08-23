---
title: "Open Dataset"
anchors:
  - data/open-dataset
---

# Open Dataset

**File > Open Dataset...**, or **Ctrl+Shift+O**.

Loads a file into the workspace as a new, active `Dataset`. The right reader is chosen
automatically from the file's extension (`src.readers.reader_registry.get_reader_for_path`) --
there is nothing to configure about *which* reader is used, only, for a multi-table source,
*which table* within it. Sixteen formats are supported:

| Format | Extensions | Reader | Notes |
|---|---|---|---|
| [CSV / TSV](../readers/csv.md) | `.csv`, `.tsv` | `CsvReader` | Delimiter auto-detected. |
| [JSON](../readers/json.md) | `.json` | `JsonReader` | Flat, columnar, or nested. |
| [Text](../readers/text.md) | `.txt` | `TextReader` | Delimited data, or one column of lines. |
| [Excel](../readers/excel.md) | `.xlsx`, `.xls` | `ExcelReader` | Multi-table (one per sheet). |
| [SQLite](../readers/sqlite.md) | `.db`, `.sqlite`, `.sqlite3` | `SqliteReader` | Multi-table. |
| [PDF](../readers/pdf.md) | `.pdf` | `PdfReader` | Table extraction; zero tables is valid. |
| [Word](../readers/word.md) | `.docx` | `WordReader` | Multi-table; zero tables is valid. |
| [XML](../readers/xml.md) | `.xml` | `XmlReader` | Repeated-sibling-element detection. |
| [Image (OCR)](../readers/image.md) | `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tiff`, `.tif` | `ImageReader` | Probabilistic; confidence warnings. |
| [OpenDocument Spreadsheet](../readers/ods.md) | `.ods` | `OdsReader` | Multi-table. |
| [YAML](../readers/yaml.md) | `.yaml`, `.yml` | `YamlReader` | Same shapes as JSON. |
| [Parquet](../readers/parquet.md) | `.parquet` | `ParquetReader` | Typed, columnar. |
| [Feather](../readers/feather.md) | `.feather` | `FeatherReader` | Typed, columnar. |
| [PowerPoint](../readers/powerpoint.md) | `.pptx` | `PowerPointReader` | Multi-table (table shapes on slides). |
| [HTML](../readers/html.md) | `.html`, `.htm` | `HtmlReader` | Multi-table (`<table>` elements). |
| [Archive](../readers/archive.md) | `.zip`, `.gz`, `.gzip` | `ArchiveReader` | Delegates to the reader for the file(s) inside. |

## Multi-table sources

If the chosen file can contain more than one table (Excel, SQLite, Word, PowerPoint, HTML, or a
ZIP archive containing several files), you are asked which one to load. A source with exactly
one table, or a single-table format, skips this step.

## Warnings, not silent failures

Several readers load a file successfully but attach warnings rather than either failing
outright or silently guessing: a CSV with rows of the wrong field count, an Excel sheet with
merged cells, a column pandas could not confidently type. These appear after loading rather
than blocking it -- see each reader's own page for exactly what it warns about and why.

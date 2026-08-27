---
title: "Generate Report"
anchors:
  - report/generate
---

# Generate Report

**Analysis > Generate Report...**, or from the **Report** stage page. Requires an active
dataset.

Exports the active dataset's recorded analysis log as a document, via
`src.services.report_service.ReportService`. This does not compute anything new -- a report is
a replay of what has already run (Reproducible Analysis's own underlying data), shaped into
whichever format you choose:

- **PDF** (`pdf`)
- **HTML** (`html`)
- **Word** (`docx`)
- **Excel** (`xlsx`)

## Options

- **Title** -- defaults to `"<dataset name> Report"`.
- **Sections to include** -- one checkbox per pipeline stage that has at least one recorded
  entry for this dataset; a stage with no recorded run has nothing to include and is not
  offered. If no stage has run yet, the report will still be generated, containing only the
  dataset summary.
- **Explain results for** -- the expertise level (Beginner/Intermediate/Advanced/Engineer)
  results and any AI explanations are phrased at in the generated document.
- **Save to** -- required before generating; the file extension is derived from the chosen
  format.

Generation (including rasterizing any chart images via `kaleido`) runs on a background worker,
so the window stays responsive for a report covering many stages or charts.

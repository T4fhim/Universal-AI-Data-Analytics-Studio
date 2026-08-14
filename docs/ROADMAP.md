# Roadmap

This document is derived only from evidence already in the repository: git history, module
docstrings (which consistently cite the milestone that introduced them), [CLAUDE.md](../CLAUDE.md),
and [SPECIFICATION.md](../SPECIFICATION.md). It does not invent requirements, timelines, or
features beyond what these sources already state.

## Development model

The project is built **milestone by milestone**, not as a single pass. Each milestone is
expected to be complete and integrated with everything before it — not a stub — but later
milestones' functionality genuinely does not exist until reached. This is stated explicitly in
CLAUDE.md and confirmed throughout `src/`'s own docstrings, which cite the specific milestone
that introduced or extended each module.

## Milestones completed, reconstructed from module docstrings

The following sequence is what the codebase's own docstrings document as already built. Not
every milestone is separately git-tagged; this is reconstructed from in-code citations
(`grep -rn "milestone" src/`), not from commit messages alone.

- **1a** — Core bootstrap: `AppConfig`, logging configuration, `Application`/`bootstrap()`
  skeleton (initially a placeholder `run()` body).
- **1b-i** — `SettingsService`, `ProjectService`, `WorkspaceService` (initial, minimal form)
  introduced and registered into the dependency container.
- **1b-ii** — `MainWindow` assembled from menu bar, toolbar, status bar, `DockManager`,
  `ThemeManager`, and `WelcomeWidget` as initial central content; `Application.run()` extended
  from its 1a placeholder to actually construct `QApplication` and enter the Qt event loop.
- **2a** — First three file readers: CSV/TSV, JSON, plain text. `Dataset` extended from a
  name/path placeholder to hold real loaded data. Type-inference ambiguous-column detection
  introduced (`src/readers/type_inference.py`), revised twice during this milestone per its own
  docstring.
- **2b** — Excel and SQLite readers — the first two formats with a genuine multi-table concept,
  which is why `BaseReader.list_tables()` and `read()`'s `table_name` parameter were added at
  this point rather than in 2a.
- **2c-i** — PDF and Word readers; `main_window.py`'s dataset file-open filter extended to
  include them.
- **2c-ii** — XML and Image readers added, bringing the reader count to nine total (per
  `reader_registry.py`'s own comment: "across all nine readers as of milestone 2c-ii").
- **3a** — Cleaning operations introduced: `BaseOperation`, duplicate removal, missing-value
  handling, text normalization, type conversion. `Dataset` gained its lineage fields
  (`parent_dataset_id`, `derivation_description`) at this point specifically to support these
  operations' "never mutate in place" contract.
- **3b** — `ProjectService` extended to track which datasets are source-file-backed, per its own
  docstring ("as of milestone 3b — which source-file-backed" datasets a project references).
- **Analysis module** (`src/analysis/`) — column/dataset profiling, correlation, aggregation,
  crosstab. No explicit milestone number is cited in this package's own docstrings, but its
  module docstring states it depends on `core`, `services`, and `readers`, placing it after the
  reader milestones above.
- **Forecasting module** (`src/forecasting/`) — exponential smoothing and Prophet-based
  forecasting. Likewise undated in its own docstrings.
- **5a** — Chart-building backend: `BaseChart`, categorical (bar/pie), continuous, and
  distribution chart types, plus dashboard composition (`dashboard_renderer.py`) — backend only,
  no UI embedding yet at this point per `src/visualization/__init__.py`'s own docstring.
- **5b** — Chart UI embedding: `ChartView` (QWebEngineView-based rendering via temp-file HTML),
  the Chart dock in `DockManager`, and `CreateVisualizationDialog`. `Visualization`'s
  `chart_type`/`chart_parameters` fields are recorded at this point for a not-yet-built
  "rebuild against updated data" feature, per `workspace_service.py`'s own docstring.
- **AI assistant layer** (`src/ai/`) — `BaseLLMProvider` abstraction (Anthropic, Gemini, Groq
  providers), `tool_registry.py` (wraps existing cleaning/analysis/forecasting functions as
  LLM-callable tools, inventing no new capability), and `AssistantService` (the provider-neutral
  tool-dispatch loop). Per `tool_registry.py`'s own docstring, every tool it exposes "calls
  directly into a function already built and tested in an earlier milestone."

## What is explicitly not built yet

Stated directly in CLAUDE.md: several `src/` subpackages remain empty directories awaiting
their milestone —

- `database/`
- `models/`
- `plugins/`
- `workers/`
- `reports/`
- `resources/` (partially used today only for `resources/styles/*.qss` theme files, referenced
  directly by `ThemeManager` rather than through a `src/resources/` module)

Also not yet built, evidenced directly by repository state rather than a docstring claim:

- **Automated test coverage.** `tests/` is empty despite `pytest` being a declared dependency in
  `requirements.txt`.
- **Enforced formatting/linting.** `black`, `isort`, and `mypy` are declared dependencies with
  no committed configuration file and no CI gate.
- **Undo/redo for cleaning operations.** The lineage fields added in milestone 3a
  (`parent_dataset_id`, `derivation_description`) are descriptive metadata for UI display only —
  per `workspace_service.py`'s own docstring, this is "not a machine-replayable operation
  record," and building that replay capability is explicitly deferred to a milestone that
  doesn't exist yet.
- **Visualization rebuild.** `Visualization.chart_type`/`chart_parameters` are recorded (as of
  milestone 5b) but nothing yet consumes them to actually rebuild a chart against updated data.

## Broader intended scope (not committed, not yet started)

[SPECIFICATION.md](../SPECIFICATION.md) describes a much larger eventual feature set — additional
file formats (SPSS, Stata, SAS, MATLAB, NetCDF, DICOM, CAD, HDF5 via a future plugin system),
additional statistical methods (ANOVA, regression, chi-square, t-tests, PCA, clustering,
association rules), additional chart types (treemap, sunburst, radar, parallel coordinates,
waterfall, funnel, candlestick, geographic maps, 3D scatter/surface, animated charts), database
connectivity (MySQL, PostgreSQL, SQL Server, Oracle, DuckDB), and full report export (PDF, Word,
Excel, interactive HTML dashboards). This is recorded here only as SPECIFICATION.md's own stated
scope — it is explicitly a superset of what exists in `src/` today (per CLAUDE.md's own
instruction not to assume something described there already exists), and nothing in this
document should be read as a committed timeline for building it.

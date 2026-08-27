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
- **6** — Async foundation: `src/workers/base_worker.py` (`BaseWorker`/`WorkerSignals` over
  `QThreadPool`), used to move dataset reads, project reload, dashboard rendering, AI turns, and
  report generation off the UI thread.
- **7** — Provider-agnostic AI config: `ai.providers` profile list (replacing a single
  provider/api key pair), Groq multi-key rotation.
- **8** — Progressive Expertise: `src/core/expertise_level.py`'s `ExpertiseLevel` enum, and
  `src/analysis/explanation.py`'s `Explanation` shape the AI layer fills in about an
  already-computed result.
- **9** — Guided Universal Data Scientist pipeline: `AnalysisOrchestratorService`,
  `PipelineStage`, `AnalysisLog`/`AnalysisLogEntry` (the Reproducible Analysis record every later
  reporting feature replays).
- **10** — Foundational UI overhaul: AI chat panel, multi-chart tabs, tree-based Dataset Explorer,
  wired Console dock.
- **11** — Statistics & forecasting expansion: `src/analysis/` gained t-tests, ANOVA, chi-square,
  linear regression, normality checks, PCA, k-means; `src/forecasting/` gained linear-regression,
  ARIMA (`pmdarima`), and Random Forest forecasters plus `model_comparison.py`'s Automatic Model
  Competition across all five methods; `src/visualization/` gained Heatmap/Bubble/Treemap/Radar/
  Waterfall/Funnel charts and `chart_recommender.py`'s Smart Visualization Selection.
- **12** — Plugin system: `src/plugins/` (`PluginManifest`, `discover_plugins`, `PluginManager`),
  plus the shared `chart_registry.py`/`operation_registry.py`/extended `reader_registry.py` every
  plugin category registers into.
- **13** — Reporting: `src/reports/` (`BaseReportExporter` and PDF/HTML/Word/Excel exporters,
  each rendering a shared `ReportContent`), `src/services/report_service.py` (replays a dataset's
  `AnalysisLog` into a report — Reproducible Analysis and Reporting share the same underlying
  data), and the "Generate Report" wizard in the Analysis menu.
- **14** — Additional readers/database connectivity: seven more `src/readers/` formats (ODS,
  YAML, Parquet, Feather, PowerPoint, HTML tables, ZIP/GZIP), bringing the reader count to
  sixteen; `src/database/` (`BaseDatabaseConnection` — a second deliberate exception to the
  stateless `Base*` pattern alongside `BaseLLMProvider` — with PostgreSQL/MySQL/SQL Server/
  Oracle/DuckDB connectors, `ConnectionProfile` deliberately holding no password field, and
  `DatabaseReader`, which does not subclass `BaseReader` since a live connection has no path to
  dispatch on); the "Connect to Database" dialog.

## What is explicitly not built yet

`src/models/` remains an empty directory awaiting its milestone — no milestone in the plan this
project has followed so far (`plans/defining-features-what-stateless-zebra.md`) names what it is
for.

- `resources/` remains partially used only for `resources/styles/*.qss` theme files, referenced
  directly by `ThemeManager` rather than through a `src/resources/` module.

Also not yet built, evidenced directly by repository state rather than a docstring claim:

- **Enforced formatting/linting.** `black`, `isort`, and `mypy` are declared dependencies with
  no committed configuration file and no CI gate.
- **Undo/redo for cleaning operations.** The lineage fields added in milestone 3a
  (`parent_dataset_id`, `derivation_description`) are descriptive metadata for UI display only —
  per `workspace_service.py`'s own docstring, this is "not a machine-replayable operation
  record," and building that replay capability is explicitly deferred to a milestone that
  doesn't exist yet.
- **Visualization rebuild.** `Visualization.chart_type`/`chart_parameters` are recorded (as of
  milestone 5b) but nothing yet consumes them to actually rebuild a chart against updated data.
- **Association rules.** Explicitly deferred in milestone 11 (no `mlxtend` dependency).
- **Report-format plugin extensibility and a `forecast_models`/`ai_providers` plugin category.**
  Both deliberately excluded from milestone 12's plugin system — see
  `src/plugins/plugin_manifest.py`'s `SUPPORTED_CATEGORIES` and `src/services/report_service.py`'s
  own docstrings for why.
- **Orchestrator REPORT-stage UI.** `AnalysisOrchestratorService` is registered in the dependency
  container but was never resolved by any UI code before milestone 13 — "Generate Report" is
  reachable via the Analysis menu only, not a pipeline-stage checkpoint.

`tests/` (empty at the point CLAUDE.md's own commands section was written) now has real
coverage — see git history for the milestone-by-milestone test additions.

## Broader intended scope (not committed, not yet started)

[SPECIFICATION.md](../SPECIFICATION.md) describes a larger eventual feature set beyond even
milestone 14 — additional file formats (SPSS, Stata, SAS, MATLAB, NetCDF, DICOM, CAD, HDF5 via a
third-party plugin), association-rule mining, and further chart types (sunburst, parallel
coordinates, candlestick, geographic maps, 3D scatter/surface, animated charts) among them. This
is recorded here only as SPECIFICATION.md's own stated scope — it is explicitly a superset of
what exists in `src/` today (per CLAUDE.md's own
instruction not to assume something described there already exists), and nothing in this
document should be read as a committed timeline for building it.

## Visual verification

Prior milestones were verified either by informally running `python main.py` and looking at it,
or by trusting the test suite alone — neither leaves an artifact a reviewer (or another agent, in
a later session with no memory of what the screen actually looked like) can inspect after the
fact. `scripts/screenshot_app_state.py` (added in the M27 remediation pass) closes that gap: it
boots the real `Application`/`bootstrap()`/`MainWindow` composition path offscreen
(`QT_QPA_PLATFORM=offscreen`) and saves a PNG via `QWidget.grab()`.

```powershell
python scripts/screenshot_app_state.py --output out.png
python scripts/screenshot_app_state.py --output out.png --new-project
python scripts/screenshot_app_state.py --output out.png --open-dataset path/to/file.csv
```

See that script's own module docstring for the full rationale (why it mirrors
`Application.run()`'s construction sequence rather than a simplified stand-in, why
`--open-dataset` stubs `QFileDialog` rather than skipping `DatasetController.open_dataset()`
entirely, and why it never calls `QApplication.exec()`). The coordinator should run this after
any future milestone that changes what the application looks like, the same way it already runs
the test suite and `mypy`/`black`/`isort` after every milestone.

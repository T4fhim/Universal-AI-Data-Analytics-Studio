# Universal AI Data Analytics Studio — Defining-Features Roadmap

## Context

The app currently has a solid, disciplined skeleton (DI container, `Base*` extension points, workspace
model, 9 readers, 5 cleaning ops, 4 analysis functions, 2 forecasting methods, 6 chart types, a fully
built but *UI-less* AI tool-calling layer) but stops well short of the product vision in the prompt: a
"Universal Data Scientist" that takes anyone from raw file to a decision-ready report, adapts to their
expertise level, explains itself, and does this through a genuinely polished interactive desktop UI.

This plan turns that feature list into a sequenced set of milestones (continuing the repo's own
`milestone N` convention — current work runs through the AI-assistant milestone, so this plan starts at
**Milestone 6**) that a future implementation pass can execute one at a time, each integrated and
demoable before the next starts. It reuses existing extension points (`BaseReader`, `BaseOperation`,
`BaseChart`, `BaseLLMProvider`, `ToolDefinition`) rather than inventing parallel mechanisms, and treats
`src/database/`, `src/models/`, `src/plugins/`, `src/workers/`, `src/reports/` as the empty stubs they
already are — this is the plan that fills them in.

Two decisions lock the shape of everything below (confirmed with the user):
- **Sequenced milestones**, not parallel tracks — each builds on the last, matching existing convention.
- **Universal Data Scientist Mode ships as a guided, human-checkpointed pipeline**, not a one-click
  autonomous run — matches the "Human-in-the-Loop" principle and avoids requiring a full async rewrite
  before anything can ship.
- **UI gets a foundational redesign** (design tokens, icons, threading, real explorers, AI chat panel,
  multi-chart viewing) — not just point-fixes — because the current UI (~1,644 lines, text-only, zero
  threading, no AI surface) can't carry the feature list otherwise.

AI provider: Groq (free tier) is the default going forward; the plan adds **multi-key rotation** so the
user can supply several Groq API keys and the app fails over automatically when one is rate-limited.
`GroqProvider` already exists (`src/ai/llm_provider.py`) — no new SDK integration needed, only the
rotation/config layer around it.

---

## Cross-cutting architecture additions (apply throughout, not a separate milestone)

These four rules get touched by nearly every milestone below, so they're stated once:

1. **New config keys**: every new setting (AI provider list, expertise level, plugin paths, report
   defaults) must update `_default_config_dict`, `_TOP_LEVEL_SCHEMA`/`_NESTED_SCHEMA`, and
   `AppConfig.from_dict` together in `src/core/config.py` — per CLAUDE.md, all three every time.
2. **New session-wide services** (e.g. `AnalysisOrchestratorService`, `ReportService`, `PluginManager`)
   register in `src/core/bootstrap.py` alongside the existing `SettingsService`/`ProjectService`/
   `WorkspaceService`, resolved from the `DependencyContainer` — never constructed ad hoc in UI code.
3. **New extension-point implementations** (readers, cleaning ops, charts, forecast models, AI providers,
   report exporters) follow the existing stateless-classmethod `Base*` shape and register in the
   package's registry (`reader_registry.py` is the existing model; cleaning/charts currently lack a
   registry and should gain one once the plugin milestone needs dynamic discovery — see Milestone 12).
4. **Cleaning/derivation immutability** is preserved everywhere new — no new code path mutates a
   `Dataset` in place; new-Dataset-with-lineage stays the only pattern.

---

## Milestone 6 — Async foundation (`src/workers/`)

**Why first:** every later milestone (autonomous pipeline stages, AI streaming, large-file reads,
background report generation) needs the UI thread free. Doing this now avoids retrofitting threading
into six later milestones.

- Fill `src/workers/`: a `BaseWorker`/`WorkerSignals` pair (`QRunnable` + `QThreadPool`, or a light
  `QThread` wrapper — follow whichever the `pyside6-development` skill's documented teardown pattern
  extends most naturally) with `started`/`progress`/`result`/`error`/`finished` signals.
- Route existing synchronous hot spots through it first, as the proof case: dataset reads in
  `main_window.py` (`_on_open_dataset`), dashboard rendering, and project reload — each currently blocks
  the GUI thread with no progress indication.
- Add a reusable progress-indication widget (status bar busy indicator + optional modal-less progress in
  the affected dock) — feeds into the Milestone 10 UI work but is needed here to make blocking ops visibly
  non-blocking.
- No new config keys. No new services beyond the worker infrastructure itself.

## Milestone 7 — Provider-agnostic AI config + Groq multi-key rotation

**Why:** unlocks "Local-First AI" (Ollama) and "Provider-Agnostic AI" properly, and delivers the
multi-key Groq rotation the user asked for, before building anything that depends on the AI layer being
reliable.

- Extend `src/core/config.py`'s `ai` section from a single `provider`/`api_key_env_var` pair to a list of
  provider profiles, e.g. `ai.providers: [{name, provider_type, api_key_env_var, model}]` plus
  `ai.active_provider_index`/`ai.rotation_enabled` — update `_default_config_dict`,
  `_TOP_LEVEL_SCHEMA`/`_NESTED_SCHEMA`, `AppConfig.from_dict` together (rule above).
- Add `OllamaProvider(BaseLLMProvider)` in `src/ai/llm_provider.py` next to the existing three, following
  the same `send`/`append_*` shape (local HTTP to `http://localhost:11434`, no API key needed) — delivers
  "Local-First AI" directly.
- Add rotation logic to `AssistantService` (or a thin new `ProviderRotationService` it holds): on a
  rate-limit/429 error from `_execute_tool`'s surrounding call, advance to the next configured provider
  profile of the same `provider_type` (or next available type) and retry once, surfacing which provider
  is active to the UI rather than failing the turn. This is additive to the existing
  try/except-and-report pattern in `_execute_tool`, not a rewrite of it.
- Config UI: extend `src/ui/dialogs/settings_dialog.py` with an AI tab — list of provider profiles
  (add/remove/reorder), rotation toggle, per-provider model override. (First UI surface the AI layer gets
  at all, ahead of the full chat panel in Milestone 10.)

## Milestone 8 — Expertise levels + explanation framework

**Why:** "Progressive Expertise" and "Explain Everything" are prerequisites for every later
AI-interpretation feature (autonomous analysis, recommendations, reports) — build the shared shape once,
reuse it everywhere downstream, rather than bolting per-feature explanation text on later.

- Add `ExpertiseLevel` enum (Beginner/Student/Analyst/Researcher/Engineer/Decision-maker) to
  `src/core/` (small shared type, not a service) and a config key `ai.expertise_level` (default
  `"beginner"`), following the three-place config-update rule.
- Define a shared `Explanation` dataclass (`what`, `why_it_matters`, `how_calculated`,
  `confidence_or_uncertainty`, `assumptions`, `limitations`, `alternative_approaches`) — likely in
  `src/analysis/` since it's the natural home next to `dataset_profile.py`/`column_profile.py`, or a new
  `src/analysis/explanation.py`. This is a **data shape**, not new statistics — the deterministic
  analysis/forecasting functions already compute the numbers; this dataclass is what the AI's
  interpretation layer fills in and the UI renders, keeping the "AI interprets, doesn't invent numbers"
  separation from the defining-features list intact.
- Update `_SYSTEM_PROMPT` in `assistant_service.py` to read the configured expertise level and adjust
  register/depth of replies accordingly (still text output — no new tool needed for this part).
- UI: add an expertise-level selector (toolbar dropdown or settings) that's read by both the AI system
  prompt and by result-rendering panels once Milestone 10 exists to render them.

## Milestone 9 — Guided Universal Data Scientist pipeline (orchestration)

**Why:** this is the headline feature (raw file → understanding → analysis → prediction → report,
autonomous-but-checkpointed) and the reason Milestones 6–8 exist first (needs async, reliable AI, and the
explanation shape already in place).

- New service `AnalysisOrchestratorService` in `src/services/`, registered in `bootstrap.py`. Encodes the
  `UPLOAD → UNDERSTAND → CLEAN → EXPLORE → ANALYZE → VISUALIZE → PREDICT → EXPLAIN → REPORT → REPRODUCE`
  workflow as an explicit state machine over one active `Dataset`, where each stage:
  1. Runs deterministic work already implemented (`dataset_profile`, cleaning ops, `analysis/*`,
     `forecasting/*`, chart builders) — **no new statistics invented here**, this milestone is glue.
  2. Asks the AI layer (`AssistantService`, extended with new tools per point below) to propose *what* to
     run next and interpret the result using the `Explanation` shape from Milestone 8.
  3. Surfaces the proposal to the user for approve/skip/modify before the next stage runs (the
     human-in-the-loop checkpoint) — this is a UI concern completed in Milestone 10, but the orchestrator
     API must be designed stage-by-stage (`propose_next_stage()` / `run_stage(approved_params)`) to make
     that checkpoint possible rather than presenting an opaque black box.
- Extend `src/ai/tool_registry.py` with the two currently-missing tool categories flagged during
  exploration: forecasting tools (`forecast_exponential_smoothing`, `forecast_prophet` — already
  implemented in `src/forecasting/`, just not wired in) and a chart-building tool (wraps
  `BaseChart.build` subclasses) — these are required for the AI to actually drive VISUALIZE/PREDICT
  stages rather than only CLEAN/EXPLORE as today.
- **Automatic Model Competition**: when the PREDICT stage applies, the orchestrator runs all applicable
  forecasting/regression models (see Milestone 11 for the expanded model set) against the same
  validated series, ranks them by an appropriate error metric (e.g. MAPE/RMSE via a small new
  `src/forecasting/model_comparison.py`), and has the AI explain *why* the winner was chosen — reusing
  `ForecastResult` for each candidate rather than a new result shape.
- **Reasoning & Recommendation Engine**: expose the orchestrator's "what would be useful next" logic as a
  standing panel (Milestone 10), not just inside the guided pipeline — so recommendations keep flowing
  even outside a full pipeline run, satisfying that item on the feature list without a second engine.
- **Reproducible Analysis**: each stage's inputs/outputs/AI proposal get appended to a per-dataset
  `AnalysisLog` (new lightweight dataclass, persisted as part of the project file via `ProjectService`)
  so a full run can be replayed. This is additive to `ProjectService`'s existing save/load, not a rewrite.

## Milestone 10 — Foundational UI overhaul

**Why here:** by this point there's something worth building a UI around (rotation-safe AI, expertise
levels, a real orchestrator) — building the UI earlier would mean re-doing panels once those land.

- **Design-token QSS system**: replace the two hand-duplicated `resources/styles/{dark,light}.qss` files
  with a single token source (colors, spacing, radii, typography) generated into both themes — the
  `dark.qss` docstring already flags this as deferred-but-intended work; this milestone is where it
  happens. `ThemeManager` (`src/ui/theme_manager.py`) keeps its current app-level `setStyleSheet` role.
- **Icon set**: add a real icon resource (SVG icon set, e.g. bundled Feather/Lucide-style icons under a
  new `assets/icons/`) and wire `QIcon`s into menu actions, toolbar buttons, and dock title bars — today
  everything is text-only.
- **AI chat panel** (the single biggest gap found during exploration — a fully built `AssistantService`
  with zero UI surface): new dock via `DockManager`, chat-style message list + input box, streams
  `AssistantTurnResult` replies, shows which tool calls ran (transparency, ties into "Explain Everything"),
  shows active AI provider (ties into Milestone 7 rotation), respects `objectName`/`toggleViewAction()`
  conventions the other docks already follow.
- **Real tree-based explorers**: replace the flat `QListWidget` Project Explorer and Dataset Explorer with
  `QTreeView`/`QTreeWidget` (project → datasets → derived datasets via `parent_dataset_id` lineage;
  dataset → visualizations → dashboards), with context menus (rename, close, "show lineage") and
  drag-drop where sensible (e.g. drag a dataset onto a chart-builder dock).
- **Console dock**: replace the "will appear in a later milestone" placeholder with real output — natural
  home for the orchestrator's stage-by-stage log and worker progress/errors from Milestone 6.
- **Multi-chart / dashboard interactivity**: replace the single-chart-overwrites-previous `ChartView` dock
  with a tabbed chart area (each `Visualization` gets a tab) and make dashboards genuinely interactive
  Qt-side rather than one flattened pre-rendered Plotly figure — needed for "Adaptive Dashboards" and
  drill-down-style exploration to feel real rather than static.
- **Onboarding/empty states**: expand `welcome_widget.py` beyond two buttons — recent projects with
  metadata, a "what does this data tell me?" quick-start entry point that jumps straight into the
  Milestone 9 orchestrator for zero-expertise users.
- **Progressive-expertise-aware rendering**: result panels (profile summaries, chart annotations, AI
  explanations) read `ai.expertise_level` and adjust density/vocabulary — reuses the `Explanation`
  dataclass from Milestone 8 rather than the UI inventing its own text.

## Milestone 11 — Statistics & forecasting expansion

**Why after UI:** these are mostly additive `Base*` implementations; sequencing them after the
orchestrator and UI exist means each new method is immediately usable end-to-end instead of sitting
unwired (the fate of the *existing* forecasting module before this plan).

- `src/analysis/`: add ANOVA, regression (linear/multiple), chi-square, t-tests, PCA, clustering,
  association rules, normality tests — as new modules alongside the existing
  `correlation.py`/`crosstab.py`/`aggregation.py`, same plain-function-returning-JSON-friendly-dict shape
  so they slot into `tool_registry.py` the same way the current four do.
- `src/forecasting/`: add Linear/Polynomial Regression, ARIMA/SARIMA, Random Forest, XGBoost (optional
  LSTM) alongside existing Exponential Smoothing/Prophet, all returning the existing `ForecastResult`
  shape so `model_comparison.py` (Milestone 9) works unmodified across the expanded set.
- `src/visualization/`: fill in the chart types SPECIFICATION.md lists but the codebase doesn't have yet
  (Treemap, Sunburst, Bubble, Heatmap/Correlation Matrix, Violin, Radar, Parallel Coordinates, Waterfall,
  Funnel, Candlestick, Geographic Maps, 3D Scatter/Surface) as new `BaseChart` subclasses in new or
  existing chart-category modules — each wired into `create_visualization_dialog.py`'s chart registry and
  into the AI charting tool from Milestone 9.
- **Smart Visualization Selection**: small new function (e.g. `src/visualization/chart_recommender.py`)
  that inspects column types/cardinality from `column_profile.py` and ranks candidate chart types with a
  stated reason — feeds both the orchestrator's VISUALIZE stage and a "suggest a chart" button in the
  chart-builder dialog.

## Milestone 12 — Plugin system (`src/plugins/`)

**Why last among backend work:** a plugin loader is much easier to design correctly once there are 4+
real `Base*` extension points with settled shapes (readers/cleaning/charts/forecast models/AI providers)
to discover and validate against — designing it first would mean guessing at the contract.

- `src/plugins/`: `PluginManifest` (name, version, provided extension points), `PluginLoader` that scans
  `config.plugin_search_paths` (already reserved in config) for Python packages exposing a known entry
  point, validates each provided class against the relevant `Base*` ABC before registration, and reports
  load failures without crashing startup (bad plugin = skipped + logged, not a `BootstrapError`).
- Registers discovered readers/cleaning-ops/charts/forecast-models/AI-providers into the *existing*
  registries (`reader_registry.py` gains a `register_reader()` used by both built-ins and plugins; give
  cleaning and charts an equivalent lightweight registry at this point, since dynamic discovery is what
  finally requires one — resolves the gap the architecture exploration flagged).
- `PluginManager` registers in `bootstrap.py` as a singleton, resolved by `main_window.py` to build a
  "Plugins" settings panel (list installed, enable/disable, show errors).
- Report-format plugin category from the feature list slots in here once Milestone 13 defines the base
  report exporter shape.

## Milestone 13 — Reporting (`src/reports/`)

- `BaseReportExporter(ABC)` in `src/reports/base_exporter.py`, same stateless-classmethod shape as the
  other `Base*` types: `export(report_content, output_path, **kwargs) -> Path`.
- Concrete exporters: PDF, HTML (interactive, embeds live Plotly figures), Word, Excel — each assembled
  from a shared `ReportContent` dataclass (dataset summary, stats, charts, forecasts, AI explanations,
  metadata) built by a new `ReportService` in `src/services/` that pulls from the `AnalysisLog`
  (Milestone 9) so a report is literally "replay the log and render it," keeping Reproducible Analysis and
  Reporting the same underlying data rather than parallel systems.
- UI: "Generate Report" action (menu + orchestrator's REPORT stage) opens a small wizard (format, sections
  to include, expertise level for the narrative text) and runs export via the Milestone 6 worker
  infrastructure (report generation is exactly the kind of operation that must not block the UI thread).

## Milestone 14 — Additional readers/database connectivity (`src/database/`)

- Round out `src/readers/` with the remaining SPECIFICATION.md formats not yet covered (ODS, YAML,
  Parquet, Feather, PowerPoint, HTML tables, ZIP/GZIP) as further `BaseReader` subclasses — mechanical,
  same registration pattern as the existing 9.
- `src/database/`: `DatabaseConnection` abstraction + connectors for MySQL/PostgreSQL/SQL Server/
  Oracle/DuckDB, and a `DatabaseReader(BaseReader)` that treats a live query result as a table source —
  distinct from `SqliteReader` (file-based) which stays as-is. UI: a "Connect to Database" dialog
  (connection profile, saved via `SettingsService` with credentials kept out of the plain config file —
  flag this specifically for the `security-reviewer` agent when implemented, since it's credential
  handling).

---

## Verification approach (per milestone, not just at the end)

- Each milestone ends runnable: `python main.py` launches, the new capability is reachable from the UI
  (not just unit-testable), and existing flows (open dataset, create visualization, AI chat) still work —
  matches the `milestone-verification` skill's existing checklist for this repo.
- `tests/` is currently empty despite `pytest` being a dependency — every new `Base*` implementation,
  service, and orchestrator stage gets a real test alongside it as it's built (via the `test-engineer`
  agent), rather than deferring test-writing to a cleanup pass at the end.
- Config-schema changes verified by round-tripping `AppConfig.load()`/`save()` against the new
  `_default_config_dict` shape (existing self-healing behavior must keep working for users upgrading from
  the current config file).
- UI changes spot-checked with the `run` skill (launch + screenshot) rather than assumed from code alone,
  especially for the new AI chat panel, tree explorers, and multi-chart tabs.
- Delegate architecture-boundary questions that come up mid-implementation (e.g. "does the plugin
  registry belong in each package or centralized") to the `architect` agent before writing code, per this
  repo's own agent-routing convention — this plan sets direction, not every low-level decision.

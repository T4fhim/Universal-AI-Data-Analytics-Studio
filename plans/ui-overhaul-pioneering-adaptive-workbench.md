# Universal AI Data Analytics Studio — UI Overhaul (Milestones 15–27)

## Context

Milestones 1a–14 built a large, disciplined backend: 16 readers, 5 cleaning operations, 12 analysis
functions, 7 forecasting methods, 12 chart types, a guided-pipeline orchestrator, a 24-tool AI
layer, a plugin system, 4 report exporters, and 5 database connectors — roughly 10,300 lines.

An audit of `src/ui/` (3,257 lines) against that backend found the UI exposes **11 menu actions**,
and that roughly **70% of the application's capability has no UI path at all**:

- **There is no dataframe viewer anywhere.** `QTableView`/`QTableWidget`/`QAbstractTableModel`
  appear zero times in the repo. A user can never see a single cell value — datasets render only
  as `"name (1,204 rows × 8 cols)"` text in a tree.
- `setCentralWidget` is called exactly once, with `WelcomeWidget`, and never again. The welcome
  screen is the permanent central widget.
- **The entire `AnalysisOrchestratorService` is orphaned** except `get_log()`. `propose_next_stage`,
  `run_stage`, `reproduce`, and `load_log` are never called. The flagship "Guided Universal Data
  Scientist" has no UI, despite that service's own docstring saying its checkpoint UI "is a UI
  concern completed in milestone 10."
- `src/analysis/`, `src/forecasting/`, and `src/cleaning/` are **100% orphaned** — no `src/ui/` file
  imports any of them. They are reachable only by typing English at the AI chat, which requires a
  configured API key.
- `Explanation` (the "Explain Everything" feature) is never rendered; it only gets flattened into
  report text. `chart_recommender` ("Smart Visualization Selection") is never called.
- `Edit > Undo`/`Redo` are `QAction`s connected to nothing. The recent-projects submenu is built but
  its actions are never connected — clicking does nothing.
- Accessibility across the whole repo is **13 API calls total**, 9 of which are menu shortcuts.
  Zero occurrences of `setAccessibleName`, `setAccessibleDescription`, `setWhatsThis`,
  `setStatusTip`, `setTabOrder`, `QAccessible`, or `setFocusPolicy`.
- Onboarding is one title label, one subtitle label, and two buttons. Help contains only "About".
- `ChartView` inlines the full ~3 MB Plotly bundle into a `delete=False` temp file **per chart tab**
  and never cleans them up.

So this is not a reskin. **This is the UI that was supposed to exist.** The overhaul is the delivery
vehicle for the majority of the product, and that framing drives every decision below.

Four decisions were confirmed with the user before planning:

1. **Guided stage rail is the primary navigation spine** — `PipelineStage` becomes the app's
   structure, with a Ctrl+K command palette and a free-roam escape hatch so experts are never
   forced through stages.
2. **Expressive + adaptive visual identity** — a token-driven design system with a vivid accent
   ramp, semantic color, per-stage identity hues, Lucide icons, illustrated empty states, and
   density that **adapts to `ExpertiseLevel`** (which already exists with six values and currently
   only tunes AI prose).
3. **Sequenced milestones**, matching repo convention — each independently shippable and demoable.
4. **The in-app manual ships with full written content**, not stubs.

---

## Language decision (settled — do not revisit)

The user asked for a concrete decision on whether other languages belong here.

**Python remains the only authored application language. No C++, no Rust, no Java, no C#.**

Rationale, in order of weight:

1. **It would destroy the no-build-step property.** CLAUDE.md states "There is no build step (pure
   Python)." A native extension means MSVC on Windows, a C toolchain elsewhere, and per-platform
   wheel builds for every contributor and every CI run. That cost is permanent and recurring.
2. **The compute is already native.** pandas/numpy/scipy/scikit-learn/statsmodels/pmdarima are
   C/C++/Fortran under thin Python wrappers. DuckDB — a C++ analytical engine — has been a
   dependency since milestone 14. Qt itself is C++; PySide6 is a binding. The app already spends
   most of its cycles in compiled code. Hand-writing more adds nothing.
3. **The bottlenecks are not arithmetic.** They are file I/O, Qt widget layout and repolish,
   Chromium rendering in `QWebEngineView`, and network latency to LLM providers. No language change
   touches any of those.
4. **If dataframe throughput ever becomes the bottleneck, the answer is Polars or DuckDB** —
   prebuilt wheels, `pip install`, zero local toolchain — not authored native code.

**Languages that genuinely are in scope**, all interpreted at runtime with no build step, and all
either already present or trivially added:

| Language | Where it is used | Status |
|---|---|---|
| **JavaScript** | `resources/web/chart_bridge.js` — Plotly event handling, `Plotly.react` updates, selection/brush/click forwarded to Python over `QWebChannel` | Already running today (Plotly.js); expanded in M16 |
| **HTML** | `resources/web/chart_host.html` (chart shell), plus the manual's compiled output for `QTextBrowser` | Generated today; becomes authored assets |
| **CSS** | Inline CSS in the manual's HTML (`QTextBrowser` ignores application QSS) | New, small |
| **QSS** | `resources/styles/base.qss.template` — Qt's CSS dialect, compiled from tokens | Already used; gains a token layer |
| **Markdown** | `docs/manual/*.md` — the manual's authored source | New |
| **SQL** | Already present via SQLAlchemy in `src/database/` | Unchanged |
| **JSON / YAML** | Config, plugin manifests, project files, Plotly figure JSON | Unchanged |

**New pip dependencies: zero.** `QWebChannel` and `QtSvg` ship inside PySide6. `markdown-it-py`
4.2.0 is already importable in the venv — but only transitively, via `rich` (requirements.txt:50),
which is fragile. So **add `markdown-it-py` as an explicit line in `requirements.txt`**: a
declaration, not an installation. Lucide icons are ISC-licensed SVG assets, not a package.

---

## Cross-cutting rules (apply to every milestone below)

1. **Config keys**: `_default_config_dict`, `_TOP_LEVEL_SCHEMA`/`_NESTED_SCHEMA`, and
   `AppConfig.from_dict` change together, plus a `_migrate_legacy_*` backfill for any key added to
   an existing section. Per CLAUDE.md — all of them, every time.
2. **New services** (`GuidanceService`) register in `src/core/bootstrap.py` and resolve from the
   `DependencyContainer`. Never constructed ad hoc in UI code.
3. **New registries mirror `src/visualization/chart_registry.py` exactly**: a frozen dataclass
   registration, a module-level `_REGISTRY` dict, `register_x` raising `ServiceError` on duplicates,
   plus `get_x`, `list_x`, `unregister_x`.
4. **Module conventions**: `# File: <path>` first line, then a docstring explaining *why* the module
   exists and how it relates to neighbours; `from __future__ import annotations`; type hints
   throughout; Sphinx `:class:`/`:meth:` cross-references; comments that explain why a simpler
   alternative was rejected.
5. **Never mutate a `Dataset` in place.** Undo (M22) is built *on* that contract, not around it.
6. **`src/core/app.py` keeps `AA_UseSoftwareOpenGL` + `AA_ShareOpenGLContexts` before
   `QApplication`.** This fixes a confirmed blank-`QWebEngineView` bug on Windows. Do not touch.
7. **Accessibility is a constraint from M15 onward, not an M26 retrofit.** Every milestone's
   acceptance criteria include "the a11y audit returns zero ERROR findings for widgets added here."
   M26 is enforcement hardening and legacy cleanup, not first contact.
8. **`ui/` imports downward only.** Nothing outside `src/ui/` may import `src.ui` — enforced by test.

---

## Architecture

### A1. Design tokens and the QSS pipeline — `src/ui/theme/`

QSS has **no variable support** (verified). So tokens live in Python and are substituted into a
single template at theme-apply time.

- `tokens.py` — `ThemeTokens` frozen dataclass with *semantic* fields, not literal colors:
  `surface_0/1/2`, `text_primary/secondary/disabled`, `accent`, `accent_hover`, `accent_pressed`,
  `border`, `border_focus`, `success`, `warning`, `danger`, `info`, `stage_hues: tuple[str, ...]`,
  `chart_categorical: tuple[str, ...]` (Okabe–Ito, colorblind-safe), `focus_ring_width`,
  `radius_sm/md`, `space_1..5`, `font_family`, `font_size_sm/md/lg`, `density: Density`.
  Exports `DARK_TOKENS`, `LIGHT_TOKENS`, `HIGH_CONTRAST_TOKENS`, `TOKENS_BY_NAME`.
- `qss_compiler.py` — `compile_qss(tokens) -> str` via `string.Template.substitute`.
  **Use `substitute`, not `safe_substitute`** — a missing token must raise at compile time, not
  silently emit a literal `${surface_9}` into the stylesheet.
- `icon_provider.py` — `IconProvider(QObject)`. Loads Lucide SVGs, recolors by replacing Lucide's
  `currentColor` stroke convention with `tokens.text_primary`, renders via `QSvgRenderer` onto a
  `QPixmap`, caches on `(icon_name, theme_name)`.
- `plotly_theme.py` — `plotly_template(tokens) -> dict`, so charts match the app theme.
- `contrast.py` — `relative_luminance`, `contrast_ratio`, `CONTRAST_REQUIREMENTS`.

**Delete `resources/styles/dark.qss` and `light.qss`.** Keeping generated copies on disk guarantees
drift. `resources/styles/base.qss.template` plus the token sets is the single source. (`dark.qss`'s
own header comment already anticipates this: *"If a design-token system becomes worth the
complexity, both this file and light.qss should be regenerated from it together."*)

**`ThemeManager` becomes a `QObject`** with `theme_changed = Signal(str)` — it is a plain class
today and cannot notify anything. On theme change: `IconProvider` clears its cache and re-renders,
`ActionBinder` re-`setIcon`s every bound `QAction`, and open `ChartView`s re-theme via
`Plotly.relayout` over the bridge (no page reload).

Cost note: substitution is sub-millisecond. The real cost is `QApplication.setStyleSheet`
re-polishing the whole widget tree — 20–80 ms, unavoidable, and acceptable for a user-initiated
toggle.

### A2. ActionRegistry — `src/ui/actions/`

The single source of truth from which the menu bar, toolbar, command palette, context menus, and
the guidance engine all derive. Mirrors `chart_registry`'s shape.

**Correction to the original thesis: the handler and the `QIcon` do not go in the registration.**
`chart_registry` works because registrations are pure data resolvable at import time with no
`QApplication`. Handlers are bound methods of a `MainWindow` that does not exist at import time, and
constructing a `QIcon` before `QApplication` is undefined behavior. Putting either in the
registration forces per-window mutable state and makes the registry untestable without Qt. So it
splits three ways:

- `action_registry.py` — **Qt-free, import-time populated.** `ActionSpec` frozen dataclass:
  `action_id` (e.g. `"dataset.open"`), `label`, `category` (enum), `icon_name: str | None`,
  `shortcut: str | None`, `status_tip`, `help_anchor`, `requires: frozenset[Requirement]`,
  `predicate: Callable[[ActionContext], bool] | None`, `checkable`, `palette_visible`,
  `stage: PipelineStage | None`.
- `action_context.py` — `ActionContext`, an immutable snapshot predicates read: `has_project`,
  `has_active_dataset`, `numeric_column_count`, `datetime_column_count`, `completed_stages`,
  `ai_configured`, `is_busy`, `can_undo`, and so on. `capture()` is **O(columns), never O(rows)**.
- `action_binder.py` — the per-window Qt side. `bind(action_id, handler) -> QAction`,
  `build_menu(menu, ids)`, `refresh_enablement(context)`, and **`assert_all_bound()`**, which raises
  if any registered spec has no handler. That last one turns the Undo/Redo/recent-projects
  dead-action class of bug into a test failure instead of a code-review hope.

**Enablement without polling**, three layers: `src/ui/ui_state_bus.py` (a `QObject` emitting
`state_changed` plus narrower signals at exact mutation points); a lazy safety net on
`QMenu.aboutToShow` and palette-open; and coalescing via a one-shot `QTimer.singleShot(0, ...)` so a
burst of ten mutations produces one recompute.

### A3. Stage workbench — `src/ui/workbench/`

Central widget becomes `Workbench(QWidget)`: an `HBoxLayout` of `StageRail` (~180 px) and a
`QStackedWidget` with one page per `PipelineStage` plus a welcome page.

**`StageRail` is a `QListWidget`, not custom-painted.** Qt 6 on Windows uses the UI Automation
accessibility backend; standard widgets are accessible for free, while custom-painted ones need a
`QAccessibleInterface` plugin. A `QListWidget` gives item-level accessibility, keyboard navigation,
and focus rings at no cost.

`StagePage(QWidget)` declares `stage: ClassVar[PipelineStage]` and `help_anchor: ClassVar[str]`, and
provides a **standard three-zone layout** — guidance card / parameter form / result area. Pages
supply only the middle zone. If a page wants a fourth zone, that is a signal the abstraction is
wrong, not a reason to special-case.

**Dock disposition** (the only user-visible removals in the whole plan):

| Dock | Verdict |
|---|---|
| Dataset Explorer | Keep and **promote** — absorb the project explorer as a top-level "Project" node |
| Project Explorer | **Delete.** It has never worked; it always reads `"(No project open)"` |
| Console + Log | Keep, tabified, default-hidden after first run |
| Charts | **Demote** — charts become `visualize_page` content; dock survives for pinned comparisons |
| AI Assistant | Keep, right side, default-visible — genuinely cross-cutting |

The workbench owns stage-sequential flow; docks own cross-cutting surfaces.

### A4. DataTableView — `src/ui/widgets/data_table/`

The missing dataframe viewer. `QTableView` + `PandasTableModel(QAbstractTableModel)`.

**`QTableView` is already virtualized** — it calls `data()` only for visible cells. The failure mode
is never the view; it is a model doing anything O(n) per call. So the model holds the frame by
reference (never a copy), keeps a `_visible: np.ndarray` index permutation, and reads via
`frame.iat[...]` positionally.

**Reject `QSortFilterProxyModel`.** Its `filterAcceptsRow` is a Python callback invoked once per
source row on every filter change, and it builds a full source↔proxy mapping. On 1M rows that is
~1M Python calls per keystroke. Sorting instead uses `np.argsort(kind="stable")` on one Series;
filtering uses a vectorised boolean mask into `np.flatnonzero`. Three to four orders of magnitude
faster, and it is the entire reason the compute layer is already native. Document this rejected
alternative in the module docstring per CLAUDE.md.

Guards: fixed row height via `QHeaderView.Fixed` (otherwise Qt measures every row);
`resizeColumnsToContents()` sampled over the first 200 rows only; a column chooser for frames wider
than ~1000 columns; `NaN`/`NaT` render as an em-dash with `Qt.AccessibleTextRole` returning
`"missing"` — not color-only. Filters above ~200k rows route through `WorkerRunner`.

### A5. Result rendering — `src/ui/results/`

Two layers, and the second is what avoids a giant `if/elif` on result type.

**Layer 1 — dispatch registry.** `result_renderer_registry.py`: a `dict[type, type[BaseResultRenderer]]`
resolved by exact type, then MRO walk, then a generic fallback.

**Layer 2 — renderers return data, not widgets.** `BaseResultRenderer` is stateless and
classmethod-only, matching every other `Base*` extension point:

```
title(result) -> str
headline(result, level: ExpertiseLevel) -> str
sections(result, level: ExpertiseLevel) -> list[ResultSection]
help_anchor() -> str
```

`ResultSection` is a small frozen-dataclass vocabulary: `KeyValueSection`, `TableSection`,
`FigureSection`, `ProseSection`, `MetricSection`, `AssumptionsSection`. A single
`ResultCard(QWidget)` converts sections into widgets, so all Qt, theming, and accessibility code
lives in exactly one place instead of once per result type. Renderers become pure functions
testable with zero Qt — `TTestResultRenderer.sections(result, ExpertiseLevel.BEGINNER)` returns
comparable dataclasses. Adding a new statistical method later is a ~40-line renderer with no Qt.

`ExplanationPanel(QWidget)` renders the seven `Explanation` fields with per-`ExpertiseLevel` default
expansion — BEGINNER opens *what* + *why_it_matters*, RESEARCHER opens *assumptions* +
*limitations*, ENGINEER opens *how_calculated*. It is a **sibling** of `ResultCard`, not embedded.
That separation is the key to the API-key problem: **results render deterministically with no LLM;
explanations are an optional overlay.**

### A6. GuidanceService — `src/services/guidance_service.py`

Registered in `bootstrap()` after `AnalysisOrchestratorService`. Answers "what should I do next?"

`Suggestion` carries `action_id` **as a string only** — the service never imports `src.ui`. It merges
four deterministic sources, then sorts by confidence:

1. `orchestrator.propose_next_stage()` → one PIPELINE suggestion.
2. `chart_recommender.recommend_charts()` → CHART suggestions. **Fixes a real bug**: the recommender
   emits display names (`"Box Plot"`) that do not match registry keys (`"box_plot"`). Normalize in
   `chart_recommender.py` itself, with a test asserting every output resolves via
   `chart_registry.get_chart`.
3. A data-quality scan (null fraction, duplicate rows, mixed-type columns) mapped onto
   `operation_registry` names.
4. `ExpertiseLevel` **re-ranking, never filtering** — BEGINNER biases toward UNDERSTAND/VISUALIZE
   and de-prioritises PREDICT; RESEARCHER/ENGINEER surface ANALYZE/PREDICT earlier. Nothing ever
   becomes unreachable.

AI suggestions are additive and optional. Guidance must be fully useful with no API key.

Contract test: `test_every_suggestion_action_id_is_registered` — that is how the string-id
decoupling stays honest.

### A7. Accessibility — `src/ui/a11y/`

Target: **WCAG 2.2 Level AA**, the standard EN 301 549 references for software.

**Free functions, not a mixin.** A mixin must enter the MRO of every Qt base you use, and PySide6
multiple inheritance with Qt C++ bases is fragile — one Qt base only, metaclass conflicts,
`super().__init__` ordering bugs. It buys nothing a function doesn't.

```
describe(widget, *, name, description=None, status_tip=None, help_anchor=None, focusable=True)
label_for(widget, label)          # QLabel.setBuddy + accessible-name mirror
set_tab_order(*widgets)
announce(widget, message)         # QAccessible.updateAccessibility — live-region equivalent
```

`describe()` sets accessible name, accessible description, status tip, tooltip, the `helpAnchor`
dynamic property (which F1 routing reads), and focus policy in one call.

`audit.py` walks a widget tree and returns `A11yFinding`s. Default rules: every interactive widget
has a non-empty accessible name; no `Qt.NoFocus` on an interactive widget; every `QLineEdit`/
`QComboBox` has a buddy or accessible name; no duplicate shortcuts; every dock has a window title;
tab order is non-degenerate.

Coverage across the WCAG 2.2 AA surface: contrast 4.5:1 body and 3:1 non-text/focus indicators
(1.4.3, 1.4.11); focus visible and focus appearance (2.4.7, 2.4.11); full keyboard operation with no
traps (2.1.1, 2.1.2); 24×24 minimum target size (2.5.8); text resize to 200% (1.4.4); text spacing
(1.4.12); never color alone (1.4.1); error identification with suggestions (3.3.1, 3.3.3);
consistent navigation (3.2.3). Plus a high-contrast token set, a reduced-motion toggle, an
adjustable base font size, and `tr()`-wrapped strings for future localization.

Two named defects get fixed: `chat_panel`'s `setSelectionMode(NoSelection)` (messages currently
cannot be focused, read by a screen reader, or copied) and its gray/red color-only status signaling.

### A8. Manual and onboarding — `src/ui/help/`

Source is `docs/manual/*.md` — authored Markdown: versioned, greppable, diffable. Compiled lazily
in memory with `markdown_it` into the HTML subset `QTextBrowser` supports.

**`QTextBrowser`, not `QWebEngineView`.** Qt Assistant itself uses `QTextBrowser` for documentation.
It is a native, fully accessible widget with internal anchors, back/forward history, and
`QTextDocument.find()` search — no Chromium process, no accessibility gap, no startup cost.

`resolve_help_anchor(widget)` walks `QApplication.focusWidget()` up the parent chain reading the
`helpAnchor` dynamic property that `describe()` set, falling back to the active `StagePage`'s
anchor, then to `"index"`. F1 is an application-level `QShortcut(QKeySequence.HelpContents)`.

**Anti-rot mechanism:** a test asserts every `ActionSpec.help_anchor` and every
`StagePage.help_anchor` resolves in `ManualIndex`. F1 can never land on a missing page.

---

## Milestones

Each is independently shippable: `pytest` green, app launches, one demoable behavior.

### M15 — Design tokens, QSS pipeline, icons, and the UI test harness

**Why first:** nothing visual can be built consistently until tokens exist — and **no UI test
infrastructure exists at all** (`tests/` has no `ui/` directory; no existing test imports `src.ui`).
Building the harness first makes every later milestone verifiable. The 265-green constraint is
nearly free precisely because nothing currently touches the UI.

`src/ui/theme/{tokens,qss_compiler,icon_provider,plotly_theme,contrast}.py` ·
`resources/styles/base.qss.template` (covers the 39 existing rule blocks **plus** the currently
unstyled `QGroupBox`, `QProgressBar`, `QToolTip`, `QHeaderView`, `QSplitter`, `QTableView`,
`QDialogButtonBox`, and universal `:focus`) · delete `dark.qss`/`light.qss` · `theme_manager.py` →
`QObject` with `theme_changed` · `resources/icons/` (~40 Lucide SVGs + `LICENSE`) ·
`src/ui/a11y/accessible.py` · **`tests/ui/conftest.py`** (session `qapp`, autouse `block_modals`) ·
`requirements.txt` gains an explicit `markdown-it-py`.

**Demo:** toggle theme; the app is fully styled including previously unstyled widgets; focus rings
are visible everywhere.

### M16 — ChartView hardening: web assets, temp-file lifecycle, QWebChannel, Plotly theme sync

**Why now:** the smallest fix for the highest-severity live defect. Depends only on M15 tokens.

`resources/web/{chart_host.html,chart_bridge.js}` plus a vendored `plotly.min.js` ·
`src/ui/web/{web_assets,chart_bridge}.py` · `chart_view.py` rewritten: one process-lifetime
`QTemporaryDir` (module-level singleton with `atexit` cleanup — it must outlive every `ChartView`),
figure JSON pushed over `QWebChannel` so re-renders are `Plotly.react` with no new file and no page
reload, explicit `page().deleteLater()` in `closeEvent`.

**Demo:** open 10 charts — disk usage flat, load instant; toggle theme and charts recolor without
flicker.

### M17 — ActionRegistry, ActionBinder, command palette, dead-action eradication

`src/ui/actions/*` · `src/ui/ui_state_bus.py` · `src/ui/command_palette.py` · `menu_bar.py` and
`toolbar.py` rewritten as declarative id lists with icons · **wire the recent-projects submenu** ·
**remove Undo/Redo here** and reintroduce them in M22 where cleaning ops make undo meaningful ·
`status_bar.py` gains determinate progress, finally consuming `BaseWorker.started`/`progress`.

**Demo:** Ctrl+K opens a searchable palette of every action; the toolbar has icons; recent projects
actually open.

### M18 — DataTableView: the missing dataframe viewer

`src/ui/widgets/data_table/*` · dataset double-click opens a data view · a new "Data" dock tab ·
a perf test on a 1M×10 synthetic frame (model construction < 500 ms, `data()` < 50 µs, no copy).

**Demo:** open a CSV and see, sort, and filter the actual cells. For the first time.

### M19 — MainWindow decomposition + WorkerRunner

**Why before the workbench:** otherwise 942 lines becomes 2,500. Pure refactor, no user-visible
change — which is exactly what makes it safe.

`src/ui/controllers/{project,dataset,visualization,report,assistant,database}_controller.py` ·
`src/ui/worker_runner.py` · `main_window.py` shrinks to ~200 lines · surface `record_datasets`'
skipped-dataset names (currently silently discarded) · call
`DatabaseConnectionService.close_all_connections()` in `closeEvent`.

**Demo:** identical behavior, plus determinate progress and a "3 datasets skipped" warning that used
to vanish silently.

### M20 — Workbench shell, StageRail, orchestrator wiring

The flagship. `src/ui/workbench/*` · `pages/{welcome,understand,report,reproduce}_page.py` ·
`src/ui/controllers/pipeline_controller.py` calling `propose_next_stage`/`run_stage`/`reproduce` ·
`ProjectService.record_analysis_log`/`get_recorded_analysis_logs` wired so **analysis logs finally
survive save/reload** · merge the project explorer into the dataset explorer, delete the dead dock,
demote the chart dock.

**Demo:** open a dataset → the rail shows UPLOAD complete and UNDERSTAND proposed → click Run →
`profile_dataset` executes, a log entry appears, and save/reopen preserves it.

### M21 — Result renderers, ResultCard, ExplanationPanel — unlocking `src/analysis/`

Turns ~2,000 orphaned backend lines into product. `src/ui/results/*` ·
`renderers/{profiling,statistical_tests,regression,multivariate,correlation,generic}.py` ·
`pages/{explore,analyze,explain}_page.py` · `analysis_parameter_dialog.py` — one generic parameter
form driven by `tool_registry.TOOLS` metadata, replacing N bespoke dialogs.

**Demo:** run a t-test from the Analyze page and see a formatted card with an assumptions section —
**with no API key configured.**

### M22 — Clean stage, lineage, workspace lifecycle, real Undo

`pages/clean_page.py` with a before/after `DataTableView` split · `widgets/lineage_view.py` over
`get_lineage`/`get_children` · `src/ui/command_stack.py` — undo exploits the never-mutate-in-place
contract (undo = re-point the active dataset at its parent) · close/remove actions for datasets,
visualizations, dashboards, and DB profiles, fixing the **data-accumulates-until-exit leak**.

### M23 — Visualize stage: multi-select picker, recommendations, all 12 charts

`widgets/column_multi_select.py` unlocks `treemap` and `radar` (flip `dialog_compatible=True`) ·
`pages/visualize_page.py` · the `chart_recommender` key-normalization fix plus its test · chart
interactivity via the M16 bridge: click a point to filter the data table.

### M24 — Predict stage: forecasting + Automatic Model Competition

`pages/predict_page.py` · `renderers/forecasting.py` — `compare_forecast_models` renders as a ranked
table plus an overlay chart with the winner highlighted · `validate_time_series` as pre-flight
warnings · add `progress_callback` to `compare_forecast_models`, the first real consumer of
`report_progress=True`.

### M25 — GuidanceService + progressive expertise

`src/services/guidance_service.py` registered in `bootstrap.py` · `widgets/guidance_panel.py` on
every stage page · **density adapts to `ExpertiseLevel`** · `AssistantService.set_expertise_level`
wired live (it currently needs a restart) · `reset_conversation` → a Clear Chat button ·
`EXPERTISE_LEVEL_GUIDANCE` rendered in the settings picker.

### M26 — Accessibility enforcement

`src/ui/a11y/{audit,contrast_manifest,rules}.py` · retrofit tab order and accessible names across
every legacy dialog · fix `chat_panel` selection mode and color-only status · high-contrast theme ·
reduced-motion and font-scale settings · a hidden `debug.a11y_audit` action dumping findings to the
console dock.

### M27 — Manual, F1, onboarding, and config debt

`docs/manual/*.md` — **full content**: all 16 readers, 12 charts, 12 statistical methods, 5
forecasters, 5 cleaning ops, the pipeline, the AI layer, plugins, and a plain-language statistics
glossary · `src/ui/help/*` · first-run tour · new `ui.*` config keys · **implement the autosave timer
that `autosave.enabled`/`interval_minutes` have described since milestone 1a but which has never
existed** · wire or delete the other dead keys (`ai.enabled`, `ai.active_provider_index`,
`forecasting.default_horizon_periods`, `reports.default_export_format`, `window.width`/`height`).

---

## Risks

**R1 — `main_window.py` unmaintainability.** Highest structural risk. M19 decomposes it *before* M20
adds the workbench, as a behavior-preserving refactor with a smoke test written first. Enforced by
`tests/ui/test_module_size.py` asserting no `src/ui/**.py` exceeds 400 non-docstring lines.

**R2 — QWebEngineView temp-file leak.** Live today. M16 fixes it. **Trap:** the `QTemporaryDir` must
outlive every `ChartView` — module-level singleton with `atexit`, not per-view. **Second trap:**
`QWebEngineView` destruction ordering on Windows can crash at shutdown if the profile outlives the
view; explicit `page().deleteLater()` in `closeEvent`, and leave `AA_ShareOpenGLContexts` alone.

**R3 — QSS token substitution.** The perf risk is a red herring (sub-millisecond); the real risk is
correctness. A literal `$` in QSS must be escaped as `$$`. Using `substitute` over `safe_substitute`
makes a typo raise at compile time, and a test compiles both token sets asserting no `$` survives.

**R4 — Keeping 265 tests green.** Low: no existing test imports `src.ui` (verified). Real exposure
is `src/core/constants.py` (QSS paths change in M15) and `src/core/config.py` (new keys in M27),
both already covered. `chart_recommender`'s normalization (M23) intentionally changes existing
assertions.

**R5 — Circular imports as `ui/` grows.** The pattern that will bite: `main_window` → `controllers`
→ `workbench` → `results` → `actions` → `main_window`. Rules, enforced by an `ast`-based
`tests/ui/test_import_layering.py`: `action_registry` and `ui_state_bus` import nothing from
`src.ui`; controllers import widgets but **widgets never import controllers** (they signal upward);
`results/renderers/` imports only `src.analysis`/`src.forecasting`/`result_view` and never Qt; and
repo-wide, nothing outside `src/ui` imports `src.ui`.

**R6 — Offscreen QWebEngineView.** Chromium can hang or fail to initialize under the offscreen
platform. `ChartView` tests must not instantiate `QWebEngineView` — test HTML/JSON generation and
temp-file lifecycle as pure functions, and mark the one real-widget smoke test
`@pytest.mark.webengine` with a skip guard.

**R7 — 1M-row UI freeze.** Even virtualized, filtering 1M rows blocks for 100–300 ms. Route filters
above ~200k rows through `WorkerRunner`, computing the mask off-thread and calling
`beginResetModel` on the main thread with the result.

**R8 — Stage-page proliferation.** Ten pages × bespoke design = 3,000 lines of near-duplicate code.
The three-zone `StagePage` layout is the mitigation, and a page wanting a fourth zone is a signal to
revisit the abstraction rather than special-case it.

**R9 — The two user-visible removals** (deleting the project-explorer dock, demoting the chart dock)
land in M20. A permanently-inert widget that always reads `"(No project open)"` is worse than its
absence, so I recommend against gating them behind a legacy flag.

---

## Testing

**The harness is an M15 deliverable** — `tests/ui/conftest.py`:

- `QT_QPA_PLATFORM=offscreen` set **before any PySide6 import**.
- A session-scoped `qapp` fixture setting `AA_UseSoftwareOpenGL` + `AA_ShareOpenGLContexts`. Never
  call `app.quit()` — teardown ordering crashes on Windows.
- An autouse `block_modals` fixture monkeypatching `QMessageBox.{information,warning,critical,question}`
  and the `QFileDialog` statics. **It returns the recorded calls**, so tests assert *what was shown*
  — which is exactly how the silently-discarded-`record_datasets`-output class of bug gets caught.
- `tests/ui/qt_helpers.py`: `process_events`, `wait_for_signal`, `click`, `widget_tree`. No
  `pytest-qt` (not installed, and `qtbot`'s value here is mostly `waitSignal`). Drive handlers
  directly and use `.click()`/`.setCurrentIndex()` — offscreen synthetic mouse input is unreliable.

**Tiers.** *Pure, no Qt*: tokens, contrast math, QSS compile, result renderers, `ManualIndex`,
`ActionContext.capture`, `GuidanceService`, the action registry. *Model*: `PandasTableModel`
correctness and perf. *Widget*: each page constructed and driven. *Window*: `MainWindow` smoke.
*Contract*: `assert_all_bound`, help anchors resolve, guidance action ids exist, import layering,
module size.

**Automated accessibility assertions** are the mechanism that makes a11y systematic rather than
aspirational:

- `test_fully_populated_main_window_has_no_a11y_errors` — opens every dock, visits every stage, runs
  `audit_widget_tree`, asserts zero ERROR findings.
- `ALL_DIALOG_CLASSES` is **discovered** by importing `src.ui.dialogs` and collecting `QDialog`
  subclasses, so a newly added dialog is automatically covered and automatically fails until it
  calls `describe()`.
- Contrast is parametrized over both token sets × every pair in `CONTRAST_REQUIREMENTS`, asserting
  the WCAG 2.2 AA threshold (4.5:1 body, 3:1 non-text and focus indicators).

**Per-milestone manual verification** (the `milestone-verification` skill): the app launches from
`main.py`; the new surface is reachable **by keyboard alone**; theme toggles both ways; and `logs/`
shows no new WARNING or ERROR.

---

## Documentation deliverables

- `docs/decisions/0003-no-additional-compiled-languages.md` — the language decision above, in the
  existing ADR format.
- `docs/decisions/0004-design-tokens-over-static-qss.md` — why tokens plus one template replaced two
  hand-maintained QSS files, and why `substitute` over `safe_substitute`.
- `docs/ARCHITECTURE.md` — the `src/ui/` section is currently one line; it needs the full subsystem
  map once M20 lands.
- `docs/ROADMAP.md` — milestones 15–27 appended as they complete.

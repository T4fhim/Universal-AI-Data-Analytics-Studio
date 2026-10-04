# UI behaviour rules recovered from the Qt shell

Mined in Phase 2.4b from `src/ui/` and `src/workers/` **before sub-step 2.5 deleted them**. The
structured data (layout, constants, copy, mapping tables, file filters) is in the sibling `.json`
files; this document holds what data files cannot: the product rules and the reasoning behind
them, especially **why a simpler alternative was rejected**. A Phase 4 React rewrite will reach
for the simple alternative by default, and every rule below marks a place where it is wrong.

File paths and line numbers point into the deleted tree and are kept as an audit trail only. The
sources no longer exist, so this file is the surviving copy — edit it deliberately.

Contents: [1 Data table](#1-data-table) · [2 Async and orchestration](#2-async-and-orchestration)
· [3 Navigation and stage pages](#3-navigation-and-stage-pages) · [4 Dialogs and forms](#4-dialogs-and-forms)
· [5 Product rules](#5-product-rules) · [6 Chart bridge](#6-chart-bridge)
· [7 Where else the rest lives](#7-where-else-the-rest-lives)

---

## 1. Data table

Source: `src/ui/widgets/data_table/{pandas_table_model,data_table_view,filter_bar}.py`. Numeric
thresholds are in `ui-constants.json`; presentation of missing values (`—`, accessible text
`missing`, six-significant-figure floats, `3.0` shown as `3`) already lives in
`uadas_core/data_table/column_formatters.py`. These are the *behavioural* rules, which did not move.

1. **Missing values always sort last, in both directions.** Not "NaN is greater than everything".
   Reversing the whole array for a descending sort would move missing values to the *front*, so
   "missing" would mean something different depending on sort direction. A spreadsheet never does
   that.
2. **The sort is stable** (`kind="stable"`), so sorting by a second column preserves the previous
   column's order among ties — what users expect from spreadsheet software. A naive JS
   `Array.sort` comparator gets multi-column behaviour wrong by default.
3. **The row header shows the 1-based *source* row number, not the position in the view.** A
   sorted or filtered view still tells the user which original row a line came from, instead of
   relabelling rows 1..N on every sort or filter change.
4. **Numeric cells are right-aligned; booleans are not** (`bool` is an `int` subclass, so the
   check must exclude it explicitly).
5. **Filtering re-applies the active sort** to the new row set; it does not drop it.
6. **There is deliberately no row cap and no paging.** The model is index-array based over a
   frame held *by reference* (never `.copy()`), so a million-row frame is virtualised. The
   answer to "why was that cap chosen" is that there is none.
7. **A per-row filter predicate was rejected.** `QSortFilterProxyModel.filterAcceptsRow` costs
   about a million Python calls per keystroke — three to four orders of magnitude slower than one
   vectorised numpy/pandas operation. A rewrite that filters row-by-row in JavaScript on a large
   table repeats exactly this mistake.
8. **The filter is whole-row, substring, case-insensitive and non-regex**, over every column
   coerced to `str`. It is explicitly *not* a per-column query language: "a small text box next
   to a table, not a query builder". The same filter is reused for chart-click drill-down rather
   than building column-aware exact matching — a deliberate rejection.
9. **Known gap — keep it from being silently reinvented.** There is **no debounce** (the filter
   bar fires on every keystroke; "debouncing belongs to the consumer" and the consumer does
   none), and **no cancellation or stale-result guard**: for frames above the off-thread
   threshold, an older keystroke's result can land *after* a newer one. A React version should
   close this with abort / last-write-wins.
10. **Column auto-size** is `max(header width, widest of the first 200 rows) + 24`, clamped to
    400px (see `ui-constants.json`). The filter runs off the UI thread only above 200,000 rows;
    columns are offered through a chooser only above 1,000.

## 2. Async and orchestration

Source: `src/ui/controllers/*`, `src/ui/worker_runner.py`, `src/workers/base_worker.py`. The Qt
threading mechanism is not data and is not recorded. The *contracts* are.

1. **Which operations are asynchronous (run off the UI thread, progress to the status bar, busy
   state cleared in a separate `on_finished`):** dataset file read, project dataset reload,
   workspace save and load, `profile_dataset` (the Understand stage), dashboard render, report
   generation, an assistant turn. State is mutated on the UI thread only.
2. **Which are deliberately synchronous, and why:**
   - *Database connect* — "a deliberate exception to this application's usual 'slow work runs off
     the UI thread' rule".
   - *`reproduce_active_dataset`* — its docstring justifies being synchronous because, "as of
     milestone 20", the only stage that could appear in an analysis log was Understand, and says
     to revisit once later stages whose replay could be slow (Clean / Analyze / Predict) exist.
     Those stages now exist and the method is still synchronous with that comment unchanged — so
     the justification is **stale**. Replay is expected to become slow; do not assume it stays
     fast.
   - *Undo / redo* — moving a pointer is O(1); nothing to offload.
3. **A run disables the same button that started it, for exactly its duration.**
4. **Never open a modal from an asynchronous completion callback.** This is a reproduced defect.
   Read warnings used to be a blocking message box raised from a worker's result callback; because
   the callback that hides the busy indicator is a *separate* queued callback that cannot run until
   the first returns, the application appeared hung indefinitely. The chosen rule: **non-fatal
   post-load notices go to the persistent Console, never a modal** — "don't lose it, but don't
   block on it". A `<Modal>` opened inside a promise `.then()` reintroduces this exact bug.
5. **A background-task callback failure must never be silent.** The full traceback is logged *and*
   the user is blocked with a dialog titled `Unexpected Error`, whose body names which handler
   failed ("result handler", "error handler", "finished handler", "progress handler") and ends
   "See the log for full details." Exact text is in `ui-copy.json`.
6. **The chat input is enabled from construction and is never gated on provider configuration.**
   The earlier design started the input disabled and re-enabled it only after a *successful* turn,
   which made it permanently unusable with no provider configured — the "no provider" explanation
   was reachable only by reading a static label. Leaving it enabled means *attempting to send*
   produces the explanatory dialog: a silent dead control became a real, user-triggered
   explanation. Related ordering: "no provider configured" takes precedence over "assistant
   disabled", because "you haven't set anything up yet" is more actionable than "you switched it
   off".
7. **Worker lifecycle contract** (`src/workers/base_worker.py`) is already restated in
   `uadas_core/jobs/job_runner.py`: exactly one of result/error fires per job, then finished
   fires once on both paths; error carries the exception plus a *pre-formatted traceback string*
   (not safe across a thread boundary); there is deliberately no cancel / result / wait surface.
   One detail `job_runner` does not spell out: progress is an **`int` 0–100 plus a short status
   string**, and progress reporting is off by default because most call sites wrap one opaque
   operation with no natural sub-steps.
8. **Autosave never interrupts the user.** It silently does nothing when it is disabled, when no
   project is open, or when the project **has never been saved** (`path is None`) — it never
   prompts for a filename the way a first manual save would, and only writes to a path that
   already exists. Settings are **re-read on every tick** rather than eagerly reconfigured; the
   accepted cost is that a mid-interval change takes effect at most one interval late. (Defaults:
   enabled, 5 minutes — in `uadas_core/core/config.py`.)
9. **Status bar** has two regions: a transient message area (5s dwell) and an always-visible
   permanent project label (`No project open` rather than blank). Busy state: an indeterminate
   marquee, with **text shown only for a genuine determinate percentage** (clamped to 0–100).
   Under reduced motion the marquee becomes a **static, fully-filled bar, not removal** —
   "something is happening" must still be visible; only the continuous motion goes away. Reduced
   motion applies live mid-operation but deliberately leaves a determinate report alone.

## 3. Navigation and stage pages

Source: `src/ui/workbench/*`. The stage list, order and per-stage rationale are **not** lost —
`PipelineStage` and `_STAGE_RATIONALE` live in
`uadas_core/services/analysis_orchestrator_service.py`, restated in `docs/manual/pipeline/*.md`.

1. **Auto-navigation hijack rule.** The workbench jumps to the *proposed* next stage **only while
   the user is on the welcome page.** Once they have navigated the stage rail themselves, later
   refreshes must **not** yank them to a newly proposed stage — that would contradict the plan's
   "free-roam escape hatch so experts are never forced through stages". A naive `useEffect` on
   "proposal changed" gets this wrong.
2. **Clicking the Upload stage on the rail is a silent no-op, not an error.** Upload has no page
   by design; the welcome page stands in for it.
3. **Every stage page has exactly three zones, in a fixed order:** guidance card + suggestion
   panel; parameter form; result area + error state. A subclass supplies *only* the middle zone.
   The load-bearing rejection: "If a page wants a fourth zone, that is a signal the abstraction is
   wrong, not a reason to special-case."
4. **The Predict page shows pre-flight validation failures inline *and* in the result area**, not
   only as a modal — so "why did nothing happen" stays visible instead of disappearing the moment
   a message box is dismissed. The inline label is prefixed `⚠ ` and the result area reads
   "Pre-flight validation failed -- see the warning above."
5. **The Visualize page gates recommendations on ≥2 checked columns** (message title `Select
   Columns`). Clicking a chart point filters the paired table **keyed on the clicked point's `x`
   only**, because `x` is the one field present on every chart type (`y`, `curveNumber` and
   `pointIndex` are not).
6. **Section groups on the Visualize page** are headed `Pick Columns` and `Configure Chart`,
   added because the page otherwise read as "one undifferentiated column of seven widgets".

## 4. Dialogs and forms

Source: `src/ui/dialogs/*`. Exact labels, titles and bodies are in `ui-copy.json`; ranges in
`ui-constants.json`.

1. **Generic parameter form conventions** (apply to every analysis, forecasting and cleaning tool
   form — ~22 of them; the parameter *catalogue* is in `uadas_core/ai/tool_registry.py`):
   - a required field's label gets a `" *"` suffix; an optional field's gets `" (optional)"`;
   - an optional combo/enum gets a literal `(none)` sentinel item, read back as `None`;
   - a column field is detected **by name**: ends with `_column`, equals `columns`, or ends with
     `_columns` — but only non-array fields get a picker; **array-typed column fields fall back to
     comma-separated free text** (`col_a, col_b`), because the toolkit had no multi-select combo;
   - validation failure: title `Missing Required Fields`, body `Please fill in: ` + humanised
     field names joined by `, `.
2. **Report export: changing the format clears any chosen output path** and forces a re-browse,
   and browsing force-corrects the suffix to the chosen format. Stated reason: so the dialog
   never quietly writes a `.pdf` under a `.html` name. A rewrite that keeps the path on format
   change ships a data-corruption-shaped bug.
3. **Settings → "Show tour again next time" is a *button*, not a checkbox.** `first_run_completed`
   is always `true` whenever that dialog is open, so a checkbox would permanently read "off" and
   be useless.
4. **The provider list is ordered and reorderable because order *is* the failover order.** With
   key rotation enabled, a rate-limited provider fails over to the next profile in the list
   (e.g. several Groq keys). That coupling is implicit in the UI and easy to lose. Provider types
   (`groq`, `anthropic`, `gemini`, `ollama`) are in `uadas_core/ai/llm_provider.py`.
5. **Database connect:** the "save profile" checkbox label *is* the security contract —
   `Save this profile (name/host/port/database/username only — never the password)`. The password
   widget is cleared immediately after it is read, win or lose (flagged by a security review).
   For DuckDB, host/port/username/password are disabled and the port auto-fills from
   `DEFAULT_PORTS` (in `uadas_core/database/connection_profile.py`).
6. **Closing a dataset is a per-item context menu (`Close Dataset`) on the Dataset Explorer tree**,
   not a registered action. Before it existed nothing in the UI ever called `close_dataset`, so
   data accumulated until exit.

## 5. Product rules

1. **Absence over an inert placeholder.** Applied three times: the **Edit menu was removed**, not
   emptied, in milestone 17 (Undo/Redo were clickable actions connected to nothing — the "dead
   action" defect the audit flagged) and returned in milestone 23 with real undo; the **Project
   Explorer dock was deleted**, not hidden; "Open Recent" is bespoke rather than faked through the
   registry. A rewrite that ships greyed-out stubs violates a standing product rule.
2. **Undo is a pointer move, not a replay.** See `uadas_core/command_stack.py` (lifted in 2.4b;
   its module docstring is the full account). A rewrite handed "add undo/redo" will build a
   snapshot or inverse-operation stack — the expensive wrong answer.
3. **The command palette shows disabled actions** so it answers "what can this application do",
   not only "what can I do right now"; selecting one is a safe no-op. Action *ids* are searchable
   as well as labels. Full contract in `workspace-layout.json`.
4. **Illustrations get a real accessible description** rather than being hidden as decorative — a
   deliberate departure from the usual empty-`alt` guidance. Danger icons use the `danger` token so
   colour is never the sole signal (WCAG 1.4.1); status rows in the chat panel dropped colour
   entirely for the same reason, since the glyph and accessible name already carry the distinction.
5. **Multi-select uses a checkbox per row, not ctrl/shift-click.** Rejected because ctrl/shift
   selection is neither keyboard-discoverable nor screen-reader-legible (a highlighted row
   announces as "selected", indistinguishable from "focused"). The selection is returned in
   **dataset column order, not check order**, matching the order the chart builders expect.
6. **The explanation panel's seven fields are collapsible sections whose title stays visible and
   announced while collapsed.** The empty-value placeholder is `(not provided)`.
7. **Dashboard auto-layout** uses *all* visualizations with no picker, two columns wide, row-major,
   and refuses to build with fewer than two.
8. **Each guidance suggestion** renders as `title` over `rationale`; the rationale is also the
   tooltip *and* the accessible text (`"{title}. {rationale}"`); the placeholder row is
   non-selectable and carries no action id. The lineage view shows only **one level** of
   descendants, deliberately, with the active node suffixed `  [active]`.
9. **Recompute action enablement on menu-open and palette-open** as a lazy safety net (see
   `workspace-layout.json` `menu_notes`).

## 6. Chart bridge

`resources/web/chart_host.html` and `chart_bridge.js` **survive** (they are not in the deleted
tree) and hold the page half. The Python half, which is deleted, defined this contract:

- an object named **`chartBridge`** registered on the page's web channel;
- JS calls `chartBridge.notify_point_clicked(json)` with `{"curveNumber":0,"pointIndex":3,"x":1.5,"y":22.0}`
  and `chartBridge.notify_selection_changed(json)` with an array of point indexes such as `[3,4,5]`;
- **malformed payloads are logged and dropped, never raised**;
- the intent: a chart click, or a box / lasso selection, **cross-filters the paired data table**.

The page is loaded **once** and every later figure or theme update is pushed into it with
`Plotly.newPlot` / `react` / `relayout` — never `setHtml()` per chart (a fully inlined Plotly bundle
is large enough that it silently fails to load). Plotly's `relayout` wants dot-path keys while
`newPlot` / `react` want nested objects; nested layout dicts must be flattened for `relayout`.

## 7. Where else the rest lives

Nothing below was lost; it is recorded here so nobody re-extracts it.

| What | Where it lives now |
|---|---|
| Stage list, ids, order, per-stage rationale | `uadas_core/services/analysis_orchestrator_service.py`, `docs/manual/pipeline/*.md` |
| Action catalogue (ids, labels, shortcuts, icons, requirements) | `uadas_core/actions/builtin_actions.py` |
| Design tokens (98 colours, density, contrast) | `uadas_core/theme/tokens.py`, `contrast.py` |
| Manual pages and anchors; F1 fallback (focused widget → active stage page → `index`) | `docs/manual/`, `uadas_core/help/` |
| Chart / cleaning / analysis / forecasting tool catalogues | `uadas_core/{visualization,cleaning,ai}/…registry.py` |
| Setting defaults (autosave 5 min, font 13, theme `dark`, reduced motion off) | `uadas_core/core/config.py` |
| Open-recent cap (10) | `uadas_core/services/project_service.py` |
| Worker/job lifecycle | `uadas_core/jobs/job_runner.py` |
| a11y rules, descriptors and the three interaction patterns | `a11y-*.json` in this directory |
| Per-ExpertiseLevel default-open sets for the explanation panel | `plans/ui-overhaul-pioneering-adaptive-workbench.md` (≈ lines 836–840) |

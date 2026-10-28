# Phase 4 — Chart intelligence: automatic, per-dataset visualization selection

**Status: DRAFT, all four §6 decisions answered (2026-10-28); awaiting your go to start CI.0. Revised the same day: renderer order is ECharts (core), Plotly (second),
D3 (third), as the user decided.** Nothing in this plan is built. It extends Phase 4 step 7 (the Tier-1
chart catalogue, complete) and is referenced from `plans/web-transition-glass-box-studio.md` as Phase 4.9.
Branch of record: `phase-4/instrument-design-system`.

## 0. Intent, constraints, non-goals

**Intent.** When a dataset is ready, the system works out *by itself* what is in it, what questions it can answer,
which chart answers each question best, and *how to draw that chart for this much data*, then offers the result.
The decision is reasoned per dataset, repeatable, explainable, and never silently applied.

**Constraints (each one is already a rule in this repo; this plan must not weaken them):**

1. **The UI stays the same.** Instrument design system, C6 workbench, the 34 golden screenshots, which stay the parity oracle now that ECharts renders them. The only new surface
   is one "Suggested" shelf inside the existing Visualize area, built from existing components (§5, CI.6).
2. **Python owns the analysis.** The frontend and the LLM never compute a number a user will read. The core stays
   Qt-free and Django-free (`.importlinter`).
3. **AI proposes, never mutates** (Phase 5 F6; CLAUDE.md "Streaming"). A recommendation is a proposal; accepting it
   creates a `ChartSpec` through the normal validated path.
4. **Deterministic first.** The chart choice must work with no LLM, no network, and give the same answer twice.
5. **Tenant data never leaks to a log, a prompt, or another tenant.** Fingerprints hold aggregates and column names,
   not rows; the existing "never log `%r` of a dataset value" rule applies.
6. **One registry, no parallel hardcoded lists** (CLAUDE.md "multi-file touchpoints"): a chart's selection metadata
   lives *with* its registration, and a test fails when they disagree.

**Non-goals.** No new visual language. No chart-type rewrite. No second web framework or dataframe library. No
model training (the recommender is rules + scoring, as `chart_recommender.py` already argues, for the same
"Explain Everything" reason). No auto-creating charts the user did not accept.

## 1. Verdict on the externally proposed stack

| Proposed | Verdict | Reason |
|---|---|---|
| React + TypeScript | **Already done** | `apps/web`: React 19, Vite 8, TS 6, TanStack Query, generated OpenAPI client. |
| FastAPI | **No — keep Django 6 + Ninja** | Phase 3 is built and tested (auth, tenancy, jobs, storage, SSE, ~2,100 API tests). Ninja is already Pydantic + OpenAPI 3.1, FastAPI's actual benefit. The master plan's "Why Django, specifically" already rejected bare FastAPI. A swap is a rewrite for no new capability. |
| Pandas · NumPy · SciPy · scikit-learn | **Already installed** (+ statsmodels) | Used by `uadas_core/analysis/`. |
| Polars | **No (for now)** | `duckdb` and `pyarrow` are already dependencies and do the heavy reductions on Parquet; Polars would be a third DataFrame API. Revisit only if CI.0's profiling shows the pandas fingerprint missing its budget. |
| ECharts as the main renderer | **Yes — core renderer (your decision)** | ECharts 6 covers most of the catalogue natively and adds chord, beeswarm, scatter jitter, broken axis, violin/contour custom charts and large-data modes: the Tier-3 charts of design decision 6 and the large-n cases. The cost is real: the 14 registered types and their variants were built and golden-tested in Plotly (step 7), so each is ported to an ECharts option and held to its golden (§3.7, CI.8). |
| Plotly.js "when required" | **Second renderer** | Draws what ECharts cannot at golden parity (the CI.0 audit lists them), stays live for every chart not yet ported, and is the fallback when an ECharts render fails. |
| D3 | **Third renderer (your decision)** | Only for charts neither library draws (Tier 3: skew-T/hodograph, Hilbert map, pictograms); a slot in the renderer registry, built when the first such chart is scheduled (CI.10). ECharts 6's native chord chart takes that one off D3's list. |
| "Validated chart specifications" | **Adopt, extend** | `_check_spec` (`apps/api/uadas_api/web/charts.py:86`) validates field names and shapes only; §3.8 adds dataset-aware validation. |
| Adapter architecture | **Adopt** | A closed registry of renderers, chosen per chart by §3.6; never a free-form string from the client. |
| AI recommends from types, stats, goal | **Adopt, bounded** | A deterministic scorer decides; the LLM only parses a goal, re-ranks the scorer's own candidates, and words facts the scorer computed (§3.9). |

## 2. What the code actually has (verified this session)

1. **A recommender exists, and is thin.** `uadas_core/visualization/chart_recommender.py:76` `recommend_charts` is
   seven hardcoded rules over the *first* column of each type, a single cardinality cutoff (`:40`, 15), no statistics,
   no goal. Its only caller is `uadas_core/services/guidance_service.py:301`. **No API route exposes it and nothing
   runs it automatically.** Its tests (`tests/visualization/test_chart_recommender.py`, including "every
   recommendation resolves in the chart registry") must stay green.
2. **Nothing auto-profiles.** `profile_dataset` runs only when a user runs the UNDERSTAND stage
   (`apps/api/uadas_api/stages/execute.py:76`, `stages/catalog.py:48`).
3. **Interactive render shows only the head of a large file.** `charts_render` (`web/charts.py:262`) calls
   `frames.read_sample` (`stages/frames.py:131`), documented as "the *first* `max_rows` rows" (5,000 by default,
   `web/config.py:51`), then builds the unchanged chart class over them. A bar/pie/treemap/KPI **total** on a larger
   dataset is therefore a total of the first 5,000 rows, and a line shows only the earliest period. The response
   carries `sampled: true`, so it is disclosed, but the number is still wrong. This is the single most important
   correctness gap the plan fixes (§3.6 "reduce, do not sample").
4. **Registry holds field names only.** `ChartRegistration` (`chart_registry.py`) has `required_fields`,
   `optional_fields`, `literal_fields`, `list_fields`, no data-shape or use-case metadata, so the recommender
   hardcodes the chart list separately, the "registry plus a separately hardcoded consumer" gap CLAUDE.md warns about.
5. **Free ingredients exist.** `frames.column_summaries` (`frames.py:156`) returns per-column type, null count, min,
   max **from the Parquet footer with no data read**; `column_profile`, `dataset_profile`, `type_inference`,
   `analysis/{correlation,normality,…}`, `plotly_resampler` (`continuous_charts.py:34`, threshold 5,000),
   `ExpertiseLevel` + `GuidanceService`, the SSE job-event stream, the job fence, and `ChartSpec`
   (`workspaces/models.py:134`).

## 3. Design

```
upload ─▶ ingest (sandbox) ─▶ Parquet frame                                   (exists)
                                  │ on ingest-complete, automatic
                                  ▼
 [1 Fingerprint] ─▶ [2 Intent] ─▶ [3 Candidates] ─▶ [4 Score + diversify] ─▶ [5 RenderPlan]
   per column/pair   what can      registry × slot    named terms, MMR          renderer + data
   shape, time,      be asked      bindings, hard     reasons built from        strategy per chart
   roles, stats                    constraints        terms                     (thresholds in config)
                                  │
                                  ▼  cached RecommendationSet ─▶ SSE event ─▶ "Suggested" shelf
                                                                     │ user accepts
                                                                     ▼
                              validated ChartSpec ─▶ render (plan applied) ─▶ renderer adapter
 [6 AI layer — optional, bounded] goal text → intent · re-rank candidate ids · narrate computed facts
```

Stages 1–5 are pure functions of their input; the same fingerprint and goal always give the same set.

### 3.1 Fingerprint (`uadas_core/analysis/`)

A versioned, JSON-serialisable `DataFingerprint`, built once per dataset from Parquet footer stats plus one bounded,
**uniformly random** sample (never the head), approximate distinct counts via DuckDB. It holds, per column:

- **Semantic role:** `measure | dimension | time | identifier | binary | ordinal | text | geo`, with a confidence.
  Extends `type_inference`; an ambiguous column stays ambiguous and is never charted silently.
- **Cardinality class** (constant, low ≤ 15, medium ≤ 50, high, unique-key).
- **Distribution shape** for measures: skew, kurtosis, IQR-outlier share, zero/negative share, modality hint.
- **Time structure:** granularity, regularity, gaps, span, trend strength (Kendall τ), seasonality hint (ACF).
- **Missingness** and its pattern.

and per pair (bounded to the top-K most promising, never all N²): |Pearson|/|Spearman|, cardinality ratio
(functional dependency / hierarchy), key uniqueness. Dataset level: rows, columns, wide-vs-long, grain, duplicate share.
It records `sampled_rows` and a `confidence`, and degrades to "partial fingerprint, lower confidence" on timeout
rather than failing.

### 3.2 Intent

A closed enum, `ChartIntent`: `TREND, COMPARISON, COMPOSITION, DISTRIBUTION, RELATIONSHIP, DEVIATION, FLOW, PROFILE,
SUMMARY, PATTERN` (`GEO`, `FORECAST` are reserved, not built). Not one label per dataset: stage 2 emits every intent the
fingerprint *supports*, each with a strength, so a dataset with a date, a category and two measures yields trend,
comparison, composition and relationship candidates ranked together. A user goal (typed, or "suggest for this column
selection") narrows or boosts them. Default is "auto".

### 3.3 Chart capability declarations (`ChartFit`, in the registry)

Each `ChartRegistration` gains a declarative `ChartFit` so adding a chart means adding its fit in the same place:

- `intents`: which questions it answers; `slots`: the role-typed columns it binds (e.g. bar: one `dimension`, one
  `measure`, optional second `dimension` for grouping); `cardinality` bounds per slot; `min_rows`/`max_rows`;
  `needs`: `non_negative`, `additive`, `ordered`, `signed`;
- `variants`: the existing literal/column options (`variant="stacked"|"grouped"|"paired"|"donut"`, `y2_column`,
  `series_column`, `panel_column`, `frontier`, …) each with its own trigger, so 7.2–7.12's variants are *recommendable*;
- `renderers`: an ordered preference list of the renderers that can draw it, e.g. `("echarts", "plotly")` (§3.7).

A test pins this in both directions (every registered chart has a `ChartFit`; every `ChartFit` names a registered
chart), the same pattern as `stages/catalog.py`'s `test_web_stages.py`. A plugin chart without a `ChartFit` is simply
never recommended (still manually buildable).

### 3.4 Candidates and scoring

For each chart × variant, enumerate slot bindings from the fingerprint, drop any that break a **hard constraint**, then
score the rest. Hard constraints (score 0, never shown): a required role is missing; negative values for pie, donut,
treemap, funnel; pie/donut over more than 6 slices (offer bar instead); radar outside 3–8 axes; rows below `min_rows`;
an ambiguous-type column bound to a measure slot; a candidate whose `ChartFit.renderers` is empty under §3.6.

Score = Σ weight × term, every term in [0, 1], **returned with the suggestion** so the reason string is generated *from*
the terms, never written separately:

| Term | Meaning |
|---|---|
| `fit` | roles satisfied, cardinality inside the sweet spot (not just the bound) |
| `effectiveness` | perceptual rank of the encoding for these data types (position on a common scale > length > angle > area > hue), the Cleveland–McGill / Mackinlay ordering |
| `intent_match` | overlap of the chart's declared intents with stage 2's strengths |
| `signal` | how much there is to see: |r|, trend strength, outlier share, skew, seasonality, group separation |
| `readability` | penalties: overplotting, too many series/labels, tiny n, long labels |
| `diversity` | maximal-marginal-relevance against charts already chosen, so the top five are not five scatters |

Weights live in versioned config and are **tuned against the gold set (§4), not by feel**. `ChartSuggestion` keeps its
current shape (`chart_type`, `columns`, `reason`, `score`) and gains `variant`, `terms`, `intent`, so `GuidanceService`
and its tests are untouched.

### 3.5 Use-case map: what each chart is for, and what it needs

This is the "probe the charts" result: the data-shape trigger for every registered chart, the variants step 7 added,
and what is missing. Thresholds are starting values for CI.0 to tune, not facts.

| Intent / question | Trigger (fingerprint) | Registered today | Not registered (add only when a gold-set dataset needs it; `lean-build`) | Cautions that become constraints |
|---|---|---|---|---|
| **Trend** — how does it change over time? | `time` + ≥1 measure | `line`; `line(area)`; `line(y2)` dual axis; `candlestick` (open/high/low/close bound) | step line, calendar heatmap (T2), indicator panes (T2) | >5,000 points → reduce (§3.6); irregular gaps shown as gaps; exponential growth → suggest log axis |
| **Comparison / ranking** | 1 dimension (≤15 levels, else top-N + "Other") + measure | `bar`; `bar(grouped)`, `bar(paired)`, `RankedList` component | lollipop, dumbbell (T2) | bars start at zero; sorted by value; grouping dimension ≤5 levels |
| **Composition** — what share? | dimension + non-negative additive measure; time × dimension for evolution | `pie`; `pie(donut)`, `pie(panel_column)`; `bar(stacked)` incl. 100 %; `treemap` (≥2 nested dimensions) | marimekko (T2) | no pie for negatives or >6 slices |
| **Distribution** — shape, spread, outliers | 1 measure with n ≥ 30, optionally a group ≤12 | `histogram`; `box_plot` | violin, ECDF, QQ (the diagnostics Phase 5 F5 "Assumption Sentinel" wants; ECharts 6 ships violin) | bin width by Freedman–Diaconis; strong skew → suggest log |
| **Relationship** — do A and B move together? | 2 measures; 3rd as size, a dimension as colour | `scatter` (+ `frontier`, `label_column`); `bubble`; `heatmap` (correlation) | hexbin / 2-D density (>50k points), beeswarm/jitter (ECharts 6) | overplotting; a group-level reversal (Simpson) is flagged when colour changes the sign of r |
| **Deviation** — start → end, actual vs plan | ordered dimension + signed increments; or actual & baseline measures | `waterfall`; `bar(paired)`; `kpi` (delta) | — | `waterfall` only for additive, ordered steps |
| **Flow / conversion** | ordered stage dimension, monotone non-increasing measure | `funnel` | sankey (T3, ECharts-native) | order must be meaningful |
| **Profile** — many attributes of few entities | 3–8 comparable-scale measures, ≤5 entities | `radar` | parallel coordinates (high-dim) | comparable scales or normalise |
| **Summary** | any dataset, headline measures | `kpi` (mini bars/dashes/lollipop); `RankedList` | — | the default first card for any dataset |
| **Pattern** — a matrix of two dimensions | dimension × dimension × measure | `heatmap` (pivot, numbers when ≤12×12, grid) | calendar / contribution heatmap (T2), missingness matrix (T2) | cap cells (§3.6) |
| **Geo** (reserved) | a `geo` role detected | none | choropleth, scatter-geo (T3) | not built; the role is detected so the UI can say "map not available yet" |

Also missing and worth recording: small-multiples as a generic facet (only `pie` has `panel_column`), and a
`FORECAST` intent that should fire after the PREDICT stage (`forecast_charts.py` exists but is outside the
recommender).

### 3.6 RenderPlan: choosing the stack and the data strategy for *this* dataset

A pure function `render_plan(chart, spec, fingerprint, row_count, interactive) → RenderPlan{renderer, strategy,
reason}`, computed at render time (so it adapts when the data changes) and returned in the render response; never stored
on the chart. The rule that matters: **reduce, do not sample.** Aggregating charts get an exact reduction pushed down to
DuckDB over the Parquet frame; row-level charts get an honest uniform sample or a density reduction.

| Chart family | ≤ 5k rows | 5k – 200k | > 200k |
|---|---|---|---|
| `bar`, `pie`, `treemap`, `kpi`, `funnel`, `waterfall`, pivot `heatmap` | draw as is | **exact group-by in DuckDB** (rows → one per category; top-N + Other beyond 15; pivot cells capped) | same: the reduced frame is the same size at any n |
| `histogram`, `box_plot` | as is | **exact** binning / quantiles in DuckDB | same |
| `line`, `candlestick` | as is | server-side LTTB/M4 reduction to ≤5k points (extends today's `plotly_resampler`) | same |
| `scatter`, `bubble` | ECharts canvas | ECharts canvas, `large` mode | 2-D density bins + outlier points (thresholds tuned in CI.0) |

Mechanics (**rewritten by the review, §9.3; the sentences below describe the superseded Plotly-only version**): a per-chart **reducer** turns `(chart_type, spec, parquet)` into a smaller frame the *unchanged*
`BaseChart.build` turns into the same figure. This is checked by an **equivalence test**: for bar/pie/histogram/box/
treemap/heatmap, `build(full_frame)` and `build(reduce(full_frame))` give identical figure JSON on datasets up to 200k
rows. Non-decomposable aggregates (median, quantiles) use DuckDB's exact `median`/`quantile_cont`, not an average of
partial results. Where only a sample is possible (a scatter), the response says so (`sampled`, `rows_used`,
`rows_total` already exist) and the UI keeps showing it. `render_max_rows` (5,000) and `render_max_figure_bytes`
(2 MiB) stay as the outer bounds. The thresholds are config keys (the three-place rule in CLAUDE.md).

### 3.7 Renderers and adapters

A closed registry on the client, in preference order: `renderers = { echarts, plotly, d3, component }` (`component` = the HTML pieces such as
`RankedList`, KPI, log pane). A chart's `ChartFit.renderers` lists what can draw it; `render_plan` picks one; the
client follows the plan and **never** picks a renderer from user input.

- **ECharts is the core renderer**, the default for every chart it can draw at golden parity. It is ported chart by chart (CI.8 waves); until a chart's wave passes its golden, that chart keeps rendering in Plotly.
- **How ECharts gets its data:** a lazy-loaded chunk, so the initial bundle does not grow. Python keeps
  owning data shaping: every `BaseChart` subclass gains `build_option(df, **spec) -> dict` returning a plain
  ECharts option as JSON (`build` and its Plotly `Figure` stay as the second renderer's builder; both call one shared shaping step so they cannot disagree on a number; no new import enters
  the core). The ECharts theme is **generated from the same design tokens** (`scripts/build_design_tokens.py` already
  emits `plotly-template.json`) so a chart looks the same in either. The 34 goldens are the parity oracle. CLAUDE.md's `BaseChart` line ("charts return Plotly `Figure` objects directly") and the `add-extension` / `dataviz-development` skills change in the same step (CI.8a).
- **Plotly is the second renderer:** it draws what ECharts cannot at parity (the CI.0 audit lists them), stays live for every chart not yet ported, and is the failure ladder: an ECharts load or render error falls back to the Plotly rendering of the same reduced data.
- **D3 is the third:** only for charts neither library draws (Tier 3: skew-T/hodograph, Hilbert map, pictograms). Its slot in the registry is added when the first such chart is scheduled (CI.10); nothing is built for it before.

### 3.8 The validated spec: three gates

1. **Schema** (Ninja/Pydantic): shape, enums, size caps. Exists.
2. **Registry** (`_check_spec`): chart type, allowed/required fields, list-vs-scalar shape. Exists.
3. **Dataset** (new): every referenced column exists in this dataset; its role is compatible with the slot; cardinality
   and `min_rows` hold; the `variant` literal is in the allowed set. Fails with a closed, specific code, not the
   generic "could not be built".

A `ChartSpec` accepted from a recommendation is created through the same three gates. The recommendation's provenance
(fingerprint hash, recommender version, terms) is stored on the recommendation set, not in `ChartSpec.spec`, which stays
exactly the builder's parameters (backward compatible; no change to the existing field-set check).

### 3.9 The AI layer (bounded, optional, off by default until it earns its place)

| Job | Input (never rows) | Output | Why it cannot hallucinate |
|---|---|---|---|
| Goal → intent | goal text; column names + roles + cardinality classes | `{intent, focus_columns[]}` | JSON against a closed schema; every column must exist in the fingerprint; invalid → ignored, deterministic path used |
| Re-rank | the top-8 candidates with their terms; the goal | an ordering of those candidate ids + one sentence each | any id outside the candidate set is discarded |
| Narrate | a list of computed facts `{id, value, template}` | prose that cites fact ids | every number must string-match its fact, else fall back to the template text |

Constraints: a provider call goes through `BaseLLMProvider` and the existing assistant plumbing; the assistant only
*proposes* (SSE, no `AssistantService` import in the route); an org-level switch disables it; column names are the only
tenant text sent and the redaction policy for them is a decision (§6). **It ships only if the gold-set evaluation shows
top-3 hit rate above the deterministic baseline with zero invalid suggestions**; otherwise it stays off.

### 3.10 Automatic trigger, caching, invalidation

- On ingest-complete the system enqueues one job through `jobs.queue.enqueue` (never Celery directly): fingerprint,
  then stages 2–5, result stored as a `RecommendationSet` keyed
  `(dataset_id, fingerprint_version, recommender_version, goal_key)`. Worker writes are fenced by attempt number
  (`services._running`), the task message carries only a job id, and the worker re-checks ownership (CLAUDE.md).
- Completion fires the existing SSE job-event stream; the shelf updates without polling. SSE frames use `web/sse.py`
  closed fields only.
- **Invalidation is free once a hook exists (§9.5: cleaning has none today):** datasets are immutable (the non-mutating `Dataset` rule), so a cleaning step yields a new
  dataset and a new fingerprint. A cached set goes stale only when `recommender_version` changes.
- A change of goal or column selection is a cheap synchronous call over the cached fingerprint (target ≤200 ms), not a
  new job.
- **Superseded by §9.5 (a dedicated job handler, not a core tool).** Original proposal: expose the recommender as a core tool in `uadas_core/ai/tool_registry.py` under the
  VISUALIZE stage and add its `stages/catalog.py` entry, so the job runner, the stage UI and the assistant all reach it
  by the one existing route. *To confirm with `architect` at CI.5.*

## 4. Ruggedness

**Gold set (built in CI.0, the thing everything is measured against).** ≥25 *synthetic, seeded, committed* datasets
(no third-party licensing, no tenant data) covering: regular and irregular time series, OHLC prices, seasonal sales
(date × region × product), survey Likert scales, high-cardinality IDs, wide numeric, hierarchical categories, signed
increments, funnel stages, a Simpson's-paradox pair, near-empty, one row, zero rows, 1M rows. Each carries an
*acceptable set* of charts (not a single answer) for the top-3, and a forbidden set.

| Failure | Behaviour | Proof |
|---|---|---|
| LLM down / slow / invalid output | deterministic result, flag `ai: unavailable` | provider-fault test |
| Fingerprint timeout / sample too small | partial fingerprint, lower confidence, fewer suggestions, never an error | fuzz + timeout test |
| Adversarial data: NaN, ±inf, all-null, mixed types, constant, 10k columns, absurd names | no crash, no invalid suggestion | Hypothesis property tests (add the dependency if absent) |
| A candidate that cannot be built | cannot appear: hard constraints + dataset gate | invariant: every suggestion passes gate 3 on its own dataset |
| Reducer disagrees with the full build | blocked in CI | equivalence test (§3.6) |
| Renderer fails in the browser | Plotly fallback on the same data | Playwright fault injection |
| Tenant data in a log, prompt, or another tenant's cache | impossible by construction | redaction test over logs and captured prompts; IDOR walk (`tests/test_web_idor.py`) covers the new routes |
| Non-determinism | none | same input twice → byte-identical set |

**Budgets, enforced in CI** (starting values for CI.0 to confirm): fingerprint ≤2 s for 1M rows (Parquet footer +
bounded sample); recommend from a cached fingerprint ≤200 ms; reduced render ≤1 s at 1M rows; initial JS bundle growth
0 KB (ECharts lazy).

**Quality bar.** Top-3 contains an acceptable chart on ≥90 % of gold-set datasets; **0** invalid suggestions; ≥3
distinct chart types in the top 5 whenever ≥3 valid exist.

## 5. Build sequence

Each step is one milestone: complete and integrated, with its own verification, not a stub. The per-commit gate
(`pytest` + `bandit`) and the single per-commit `code-reviewer` of RESOURCE_ORCHESTRATION §1.5 apply to every step.
Ordering: CI.0 → (CI.1 ∥ CI.2 ∥ CI.8a) → (CI.3 ∥ CI.4) → CI.5 → CI.6; CI.8's port waves follow CI.8a and run alongside CI.3–CI.6, each gated by golden parity; CI.7 starts after CI.3; CI.9 last; CI.10 post-launch.

| Step | Output | Verification gate | Resources |
|---|---|---|---|
| **CI.0 Ground truth and spike** (throwaway, no product code) | gold set + expected charts; the current recommender scored on it (baseline); benchmark Plotly SVG / `scattergl` / ECharts large-mode at 10k, 100k, 1M points and a 50k-node treemap, plus DuckDB reduce vs pandas sample; fingerprint cost on 1M rows; `plans/phase-4-ci0-findings.md`. **Output of the audit: for each of the 14 types, their variants and the Tier-1 charts, whether ECharts draws it at golden parity (hatched bars, end-dot area, candlestick + volume, dual axis, waterfall, KPI minis, treemap, radar, funnel); what it cannot stays Plotly. Also decided here: the DuckDB security posture (§9.2). Polars stays out unless the pandas fingerprint misses budget.** | numbers in the findings doc, reproducible by one script | `superpowers:brainstorming` outcome, `performance-analyzer`, `ecc:architect` (opus, one pass), context7 for ECharts/DuckDB facts |
| **CI.1 Fingerprint** | `DataFingerprint` + builder in `uadas_core/analysis/`; DuckDB-backed footer/approx stats in the API layer; version field | property + fuzz tests; fingerprint within budget; `lint-imports` (check `.importlinter` layering before placing); add the package to the mypy list | `lean-build`, `ecc:python-reviewer`, `performance-analyzer` |
| **CI.2 `ChartFit` on the registry** | declarations for all 14 types and their variants; both-direction consistency test | the test; manual's chart counts and AI tool schema unchanged | `add-extension`, `project-architecture`, `architect` |
| **CI.3 Recommender v2** | candidates + hard constraints + scoring terms + diversity + reasons; `recommend_charts` keeps its signature; weights tuned on the gold set | gold-set quality bar (§4); determinism; `test_chart_recommender.py` and `GuidanceService` tests unchanged | `tdd-guide`, `python-reviewer` |
| **CI.4 RenderPlan and reducers** | `render_plan`, DuckDB reducers per chart family, LTTB/M4, config keys (3-place rule), `charts_render` applies the plan and returns it | **equivalence test**; budgets; existing 2,125 API tests stay green | `performance-analyzer`, `security-reviewer` (does DuckDB over our own Parquet cross the sandbox boundary? answer before coding) |
| **CI.5 API + automatic trigger** | `RecommendationSet` model + migration `0005` (add it to the pinned list in `apps/api/tests/test_migrations.py`); routes (`member()` first, `project_of`/`in_project`, `operation_id`, `responses`); ingest-complete enqueue; SSE event; gate 3; regenerate `openapi.json` | IDOR walk; OpenAPI drift check; fenced-write test; a real-ASGI streaming test (`test_web_streaming` style) | `contract-first`, `migration`, `django-reviewer`, `database-reviewer`, `security-reviewer` |
| **CI.6 "Suggested" shelf** (the only UI change) | shelf in the Visualize area from existing card/list components, reason + score terms behind the existing expertise-level disclosure, "suggest for this selection"; accept → `ChartSpec` | Playwright E2E: upload → suggestions appear → accept → chart renders; golden for the shelf; a11y checked (axe was **not** run for 7.10–7.14, so this step runs it or says it did not) | `react-reviewer`, `typescript-reviewer`, `a11y-architect`, `e2e-runner`, `impeccable` only as reviewer |
| **CI.7 AI layer** | the three bounded jobs of §3.9, org switch, provider-fault handling, eval harness | gold-set top-3 beats baseline with 0 invalid, else left off | `security-reviewer`, `mle-reviewer`, `mlflow:agent-evaluation` |
| **CI.8 ECharts core renderer** — 8a foundation, 8b–8e port waves | **8a:** renderer registry (`echarts`, `plotly`, `component`; `d3` reserved), lazy ECharts chunk, ECharts theme generated from the design tokens, the option-builder contract (§9.4), CLAUDE.md and skill updates, Plotly fallback ladder. **Waves:** 8b line/area/dual-axis/candlestick; 8c bar variants, pie/donut/pie grid; 8d scatter/bubble/heatmap/histogram/box; 8e treemap/radar/funnel/waterfall/KPI. A chart switches to ECharts only when its wave passes | each ported chart matches its golden (or a difference you signed off); bundle budget; fault-injection fallback; the 34 goldens stay green for charts still on Plotly | `typescript-reviewer`, `react-reviewer`, `e2e-runner`, `architect` (changes the `Base*` pattern), `a11y-architect` (canvas charts need text alternatives) |
| **CI.9 Hardening and docs** | load test on render/recommend, chaos on LLM and renderer, flag, manual page `docs/manual/visualize/auto-suggest.md` (anti-rot test applies), ROADMAP and this plan synced | all §4 rows green; `milestone-doc-sync` | `milestone-verification`, `milestone-doc-sync`, `doc-updater` |
| **CI.10 D3 renderer slot** (post-launch, only when a Tier-3 chart is scheduled) | `d3` entry in the registry, one custom chart (e.g. skew-T), its golden | a golden; D3 in its own lazy chunk | `typescript-reviewer`, `e2e-runner` |

**Fit with launch (agreed 2026-10-28).** ECharts is the core renderer, so CI.8's port waves are launch scope with CI.0–CI.6, the deterministic path that makes a coherent launch
feature; CI.7 (AI) and CI.10 (D3) come after. This reverses design decision 9 (Plotly template) and the ship plan's D9 ("Plotly-only path"), which I did not edit. I did not re-read
`plans/two-week-ship-plan.md` for this; check its D9 before committing.

## 6. Decisions (all four answered 2026-10-28)

1. **Port sign-off: answered.** ECharts is the core renderer. A ported chart's golden may differ only where you sign off that specific difference; until then it keeps rendering in Plotly.
2. **Scope for launch: answered.** CI.0–CI.6 plus the ECharts port waves (CI.8); the AI layer (CI.7) and D3 (CI.10) come after.
3. **AI and tenant text: answered.** Off by default per organisation; only column names are ever sent, never cell values.
4. **The shelf: answered.** One "Suggested" shelf inside Visualize, built from existing components.

No decision is pending; what remains open is listed in §8 and §9 and is settled by the step that depends on it.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Rules look smart but pick badly on real data | the gold set, a hard quality bar, weights tuned on data, reasons shown so a user can see why |
| Reducers drift from the chart classes | equivalence test in CI on every reducible chart |
| Porting 14 types and their variants to ECharts regresses a look or a feature | one wave at a time, golden parity per chart, Plotly stays live for any chart not yet ported, one shared Python shaping step under both builders |
| DuckDB inside the API crosses the sandbox rule | CI.4 asks `security-reviewer` first; frames are our own Parquet, not untrusted formats, but the rule is stated about parsers |
| Scope creep into new chart types | a chart is added only when a gold-set dataset needs it (`lean-build`) |

## 8. Not verified (assumptions to check at the step that depends on them)

- Where an ingest completes and where a profile result is persisted (I read the dispatch table in `stages/execute.py`,
  not the ingest path): CI.5.
- `.importlinter` layering: whether `analysis/` may import `visualization/` or the reverse: CI.1/CI.2.
- ECharts `large`/`sampling` and Plotly `scattergl` behaviour at 1M points: measured in CI.0, not assumed. The ECharts 6
  chord/beeswarm/jitter/broken-axis/violin/contour features and the `large` bar mode were confirmed from the
  ECharts handbook (context7), not run.
- Whether `hypothesis` is in `requirements-dev.txt`: CI.1.
- Whether ECharts reproduces hatched bars, the end-dot gradient area, candlestick + volume and waterfall at golden parity: the CI.0 audit, not assumed.
- Nothing here was benchmarked or built; every budget is a starting value.

## 9. Architect review (2026-10-28): corrections that supersede earlier sections

One read-only `ecc:architect` pass. Each item is the reviewer's reading of the cited file (I have not re-read them);
the step that depends on it re-verifies before coding.

1. **Layering.** `.importlinter:79-80` puts `visualization` above `analysis`, so the fingerprint cannot import
   visualization: `ChartIntent` and stage 2 live in `visualization/`; the fingerprint stays intent-free. The fingerprint
   may import `readers.type_inference` (allowlisted, `test_sandbox_boundary.py:132`); API code may not
   (`.importlinter:144`), so the API calls the core builder and never `readers.*`.
2. **DuckDB is a second parser of untrusted bytes.** A compromised ingest child writes the Parquet
   (`ingest/service.py:265`, `stages/frames.py:46`); nothing under `apps/api` imports `duckdb` today, and
   `api-avoids-raw-sql-connectors` blocks reusing `DuckDbConnection`. Rules: raw `duckdb` behind one module with reviewer
   sign-off; query pyarrow tables, never file paths; external access and extension autoload off; quote every identifier
   (column names are tenant text and bandit skips B608); add `duckdb` to the sandbox-boundary probe. Decided in CI.0/CI.1,
   because the fingerprint already needs it.
3. **Reduction depends on the chart class (replaces §3.6's equivalence claim).** Histogram and box send raw rows to
   Plotly.js (`distribution_charts.py:44-48, 92-99`); count-mode bar/pie use `value_counts`
   (`categorical_charts.py:39, 348-349`); the top-14 + "Other" tie order is unstable (`:340, 113`,
   `advanced_charts.py:73`); NaN vs NULL labels, float sum order and BIGINT→HUGEINT differ; treemap's negative check
   (`advanced_charts.py:362`); correlation-mode heatmap is not group-by reducible (`:223`); KPI, funnel and waterfall
   depend on row order (`:472-476, 513-516, 675-681`). So: the new ECharts option builders take reduced input natively
   (pre-binned histogram, precomputed quartiles, fences and outliers, an ordered/tail strategy for KPI/funnel/waterfall);
   one deterministic tie-break (value desc, label asc) on both sides; nulls and dtypes normalised; the equivalence test
   compares with tolerance and is scoped to bar, pie, treemap and pivot-mode heatmap; correlation is computed in DuckDB or
   on a disclosed sample. Plotly's `build` keeps its current behaviour.
4. **Option-builder shape.** Two output contracts on `BaseChart` with no drift test, inherited by plugins
   (`base_chart.py:58-79`): use a sibling stateless `BaseOptionBuilder` keyed by chart name in `ChartFit`, with an
   equivalence test against `build`. `ChartRegistration.fit` is `ChartFit | None = None` (plugins register at runtime,
   `chart_registry.py:43-85, 102`); the both-ways test covers built-ins only. `RankedList` and the log pane are
   components, not registry charts: kept out of the recommender, or a separate closed set.
5. **Automatic trigger (replaces §3.10's registration path).** Hook `create_job(...)` inside ingest's `commit()`
   (`jobs/execution.py:164-177`, `ingest/service.py:280-314`) with idempotency key `recommend:<dataset_id>`; catch a
   capability or JOB_SECONDS-quota failure (`jobs/services.py:178, 192`) and skip rather than fail the ingest; decide
   whether the auto job bills the user; return the follow-up job id in the ingest result so the SSE client finds it. A new
   JobKind needs jobs migration `0004` and a registry parity entry (`jobs/choices.py:29`, `jobs/models.py:183`,
   `jobs/registry.py:102`) as well as workspaces `0005`, all in `test_migrations.py`. A VISUALIZE-stage tool is forced to
   `OperationKind.FIGURE` (`stages/catalog.py:68, 84`) and a tool handler loads a whole `Dataset` (`stages/run.py:230`,
   2M-row refusal `config.py:54`): so a **dedicated job handler, not a core tool**, and the "AI tool schema unchanged"
   gate in CI.2 is moot. Cleaning creates derived records with no hook (`stages/run.py:305`): hook the stage commit too.
6. **Render is a 5k synchronous call by design** (`web/charts.py:9-14`, `stages/frames.py:5-6`): each call spools the
   whole object, so an exact group-by at 1M rows in a request reverses that ruling and the ≤1 s budget includes a full
   download. The reduction runs in a job and its reduced frame is cached per (dataset, spec); the sync render serves the
   cache. Render thresholds are `ApiConfig` keys (`web/config.py:38`), not the core's three-place config rule. CI.4
   changes `ChartRenderOut` (`charts.py:79`), so the OpenAPI regeneration and drift gate belong in CI.4; the §3.4 "no
   renderer" constraint is stated statically per `ChartFit`, so CI.3 does not depend on CI.4.
7. **Determinism and fixtures.** The uniform sample takes a fixed seed (DuckDB `REPEATABLE` is repeatable only
   single-threaded). The gold set is seeded generators, not committed 1M-row files (large-file pre-commit check).
   `hypothesis` is only transitive via schemathesis (`apps/api/pyproject.toml`): add it to `requirements-dev.txt`.

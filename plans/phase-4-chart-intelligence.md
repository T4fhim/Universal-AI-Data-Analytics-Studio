# Phase 4 — Chart intelligence: automatic, per-dataset visualization selection

**Status: DRAFT, all four §6 decisions answered (2026-10-28); CI.0 done (`plans/phase-4-ci0-findings.md`, §6 has the measurements); CI.1 (fingerprint) and CI.2 (`ChartFit`) are built (§3.1 and §3.3, "As built"); CI.8a is next, and CI.3/CI.4 are unblocked. Revised the same day: renderer order is ECharts (core), Plotly (second),
D3 (third), as the user decided.** Nothing in this plan is built. It extends Phase 4 step 7 (the Tier-1
chart catalogue, complete) and is referenced from `plans/web-transition-glass-box-studio.md` as Phase 4.9.
It is step 8 of `plans/phase-4-design-reference.md` §7; the design-language skill moved to step 9.
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

**As built (CI.1, 2026-11-01).** `uadas_core/analysis/fingerprint.py` (builder over a pandas frame, `build_fingerprint`) and
`apps/api/uadas_api/stages/fingerprint.py` (`fingerprint_frame`: one streamed pass over a Parquet object into a seeded uniform
100k sample plus whole-file null and approximate-distinct counts from a locked-down DuckDB, the only module allowed to import
it: `.importlinter` contract `duckdb-only-in-the-fingerprint-module`). Where it differs from the text above:

- Roles gained `unknown` (all-null, unsupported or not-analysed columns); a column also carries closed `issues`
  (`all_null | constant | ambiguous_type | unsupported_type | not_analysed | non_finite`) and two derived flags: `usable`
  (understood and sound) and `chartable` (usable and a role a chart can draw; an identifier is usable, not chartable).
- Time structure reports `granularity`, `regularity` and `coverage` (distinct values over a gap-free grid), not a count of
  gaps, because a count does not survive sampling. Seasonality is computed only for an unsampled, regular series with unique
  timestamps; trend (Kendall tau) uses up to 5,000 points. The "modality hint" is a histogram valley test: Sarle's
  coefficient was tried and rejected (it flags every skewed or uniform measure).
- Pairs are bounded: the top 20 |r| among at most 40 measures on 20k rows, and parent/child dimensions among at most 12.
  `grain` is a key column, else time (+ one dimension).
- "Never raises on data" is structural, not only tested: every stage runs under a guard that records `stage_failed:<name>`
  (and the exception class, never its text) and degrades; each defect the independent review found is also fixed at its
  source and has a regression test (a span of centuries overflowing int64 nanoseconds, opposite float extremes in the
  histogram, `numpy.str_` cells, pandas-3 surrogates). The column `dtype` is a closed vocabulary (`integer`, `float`, `text`,
  `datetime`, `categorical`, ...), because pandas' own name embeds a cell value for a Sparse column and changes between
  pandas versions, which would change the hash. A timezone-aware column is read as local wall-clock time (a daily series in
  New York stays daily across the 23-hour DST day); coded categoricals are dimensions; seasonality needs three cycles and an
  autocorrelation above 2/sqrt(n) (white noise of 24 points was called seasonal 21 % of the time, now 3 %). A date outside the
  nanosecond range (a year-9999 "no end date") is `unsupported_type` on pandas 2 and a real time column on pandas 3 (a known
  version difference). Pair key-uniqueness is `grain`, not a field of `DimensionPair`.
- **Not built (nothing consumes them yet):** a missingness *pattern* (only the share), `DataFingerprint.from_dict`, geo beyond
  a latitude/longitude pair detected by name and range, and a whole-number year column as a time axis (it is an ordinal or a
  measure). Add each with its first consumer.
- DuckDB parses no bytes (pyarrow still decodes the Parquet), so it is **not** in the sandbox-boundary probe (§9.2 asked for
  that on the premise that DuckDB would read files; the lockdown, with one refusal test per statement, is the control).
  The stream is bounded by `max_object_bytes` and the job's time limit, not by the fingerprint's `time_budget` (which cuts the
  CPU stages after it). A worker running it at 1M rows needs at least 1 GB.
- Measured (this machine, 1M rows x 20 columns, written the way ingest writes it): 1.3-1.9 s end to end over repeated
  runs (stream and DuckDB 0.4-0.6 s, to_pandas 0.06 s, the core builder 1.0-1.3 s), against the 2 s budget; the CI test
  allows 4 s. The core's time is per-column pandas work and the machine is noisy, so the budget has little slack: halving the
  sample saved only 0.2 s.
- Bounds in the API module (from the security review): at most 1,000 columns (`columns_truncated` note, only those decoded),
  the sample can never exceed `sample_rows` whatever the footer declares, no DuckDB spill, no `duckdb` pin (the per-statement
  refusal tests run on whatever version CI resolves). Left to the caller: the decoded size of a small file and the stream's
  duration (worker memory limit, job time limit), and never logging `str(exc)` of a pyarrow error.

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

**As built (CI.2, 2026-11-01).** `uadas_core/visualization/chart_fit.py` (`ChartFit`, `Slot`, `Bounds`, `Variant`,
`ChartIntent`, `Renderer`, `Need`; validated at construction) and `ChartRegistration.fit`, with `fit_for(name)` and
`list_fits()` in the registry. All 14 built-ins declare one, **inline in their own `register_chart` call**; a chart with
`fit=None` (a plugin) is never recommended but stays buildable. Where it differs from the text above:

- `needs` is **per slot**, not per chart (a pie's value is non-negative and additive, its category is neither), and gained
  `non_increasing` for a funnel's measure so the scorer need not hardcode "funnel". Needs are **hard or soft**:
  `HARD_NEEDS` (`non_negative`, `non_increasing`) are decidable from a fingerprint (`negative_share`, and the new
  `ColumnFingerprint.row_order`, which is recorded only for an exact fingerprint because a sample has lost the order of
  the file) and make a candidate invalid; `SOFT_NEEDS` (`additive`, `ordered`, `signed`) are judgements no fingerprint can
  settle, so the scorer treats them as evidence. On a sampled fingerprint a negative row can be missed: the dataset gate at
  accept time is the backstop.
- A variant's slots are added to the chart's, or replace the one with the same field (`stacked` tightens `value_column`; a
  series bar lets its category be a time axis). `ChartFit.slots_for`, `intents_for` and `rows_for` are the one place that
  merge rule lives. A candidate is exactly one variant, and no column fills two slots of one candidate.
- A slot may carry `name_hints` (`hint_required` for a candlestick's open/high/low/close), matched as whole tokens of the
  column name (`name_tokens`, now public): four measures are not an OHLC series and a fingerprint cannot say which is which.
- `Slot.unique` (one distinct value per non-null row) is declared where a chart draws one mark per row with no aggregation:
  line x, radar entity, waterfall step, funnel stage, candlestick x. `Slot.nested` (each bound column determines the next)
  is a treemap's path, now exactly two nested levels with at most 200 leaves.
- **Declared stricter than the builder, deliberately:** a line needs an x axis (a line over the row index is not a trend), and
  the plain bar's category is not a time axis (it sorts by value and folds past 15; the series bars sort by label and may
  take one). Distinct counts follow the builder, which draws a `(missing)` bucket for nulls, so a consumer compares
  `distinct + 1` when `missing_share > 0`.
- **The correlation heatmap is not declared:** the builder correlates every numeric column (identifiers and ordinals
  included) and takes no column parameter, so a spec cannot bind or avoid a column and the API reads no columns for it. The
  heatmap fit is the pivot mode (`numbers` and `grid` are its variants). It becomes recommendable when `HeatmapChart.build`
  takes a `columns` list, a deliberate change to the AI tool schema.
- An independent architect review of this design found the gaps above; each is fixed or recorded as deliberate. The
  fingerprint version is 2 for `row_order`.
- `Variant.explicit` marks looks only offered on request (the four scatter frontier corners, three KPI looks): nothing in
  the data says which is "best". `bar(stacked)` is a variant with no literal (a series column makes it stacked); there is
  no 100 % stacked bar in the builder, so none is declared.
- **`renderers` is `(plotly,)` for all 14 today**, not `(echarts, plotly)`: declaring a renderer that cannot draw the chart
  yet would make the render plan pick one that does not exist. A CI.8 wave puts `echarts` first for its charts when their
  goldens pass.
- Every number (cardinality sweet spots, `min_rows`, `max_rows`) is a starting value for CI.3 to tune. Four are pinned to the
  builders' own constants by `tests/visualization/test_chart_fit.py` (a bar's fold limit, a pie's panel cap, a heatmap's
  matrix cap, a radar's 3 axes) and the allowed `variant` literals are checked both ways against the builders, so adding a
  variant to a builder fails the test until it is declared.
- `chart_fit.py` and `chart_registry.py` are in the CI mypy list (`.github/workflows/ci.yml`; clean over the whole list with
  the pinned mypy), with a matching note in `docs/MYPY_DEBT.md`. That edit landed one commit after CI.2 because the push
  token lacked the `workflow` scope until it was refreshed. The AI tool schema and the manual's chart counts are unchanged
  (no field was added or renamed).

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
current shape (`chart_type`, `columns`, `reason`, `score`) and gains `params` (field → column: a bare `columns` list cannot name a builder parameter, CI.0 finding 1), `variant`, `terms`, `intent`, so `GuidanceService`
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
| `scatter`, `bubble` | ECharts canvas | ECharts canvas, `large` mode | 2-D density bins + outlier points (CI.0 §6.1: ECharts needs `large: true` always; above 200k the payload, 39 MB at 1M, is the limit, not drawing) |

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
- `.importlinter` layering: whether `analysis/` may import `visualization/` or the reverse: **answered in CI.1**: `visualization`
  sits above `analysis`, so `analysis` may not import it and `ChartFit` / `ChartIntent` live in `visualization/`; `analysis` may
  import `readers.type_inference` (the fingerprint did not need to).
- ECharts `large`/`sampling` and Plotly `scattergl` behaviour at 1M points: **measured in CI.0 §6.1.** The ECharts 6
  chord/beeswarm/jitter/broken-axis/violin/contour features and the `large` bar mode were confirmed from the
  ECharts handbook (context7), not run.
- Whether `hypothesis` is in `requirements-dev.txt`: it was not (only transitive via schemathesis); **added, pinned, in CI.1.**
- Whether ECharts reproduces hatched bars, the end-dot gradient area, candlestick + volume and waterfall at golden parity: the CI.0
  audit found no CANNOT; CI.0 §6.4 ran candlestick + volume, the waterfall (with a zero crossing), a log bar and decals; the end-dot
  area and golden-level pixel parity are still checked per wave in CI.8.
- Budgets are starting values; CI.0 §6 measured the fingerprint (1.5 s at 1M rows, streamed), the reductions (<0.1 s) and the
  ECharts chunk (295 KB gzip) on one machine, and nothing else here is built.

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

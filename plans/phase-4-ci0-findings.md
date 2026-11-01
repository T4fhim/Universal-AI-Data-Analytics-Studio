# Phase 4 step 8 — CI.0 findings (2026-10-28; part 2 added 2026-11-01)

Part of `plans/phase-4-chart-intelligence.md`. **CI.0 is done.** Part 1 (§1–§5, 2026-10-28): gold set, baseline,
DuckDB posture, ECharts parity audit from the docs. Part 2 (§6, 2026-11-01): the browser benchmarks, the fingerprint
and reduction costs on 1M rows, the four recipe spikes and the bundle weight, all measured by the committed scripts in
`scripts/ci0_bench/`. §1–§5 are labelled where a statement came from the docs rather than a run; §6 numbers are all
from one machine (stated there).

## 1. The gold set (`tests/visualization/gold_set.py`, `test_gold_set.py`)

29 seeded generator cases (regular/irregular time series, OHLC, seasonal sales, low and high cardinality, a numeric-id
trap, correlated and independent pairs, 12 and 200 wide columns, survey, hierarchy, signed increments, funnel, skewed
single measure, categorical-only, a Simpson's pair, tiny, one-row and zero-row frames, all-null, constant and
mixed-type columns, bubble, budget-vs-actual, composition over time, a 1M-row-capable time series). Each carries an
acceptable set (one must be in the top three), a forbidden set (must not appear in the top five), columns that must
never be bound, and whether the right answer is "nothing". `evaluate()` and `summarise()` are the instrument CI.3 and
CI.7 call. **63 tests pass** (determinism, stated size, coherent expectations, every named chart registered,
`evaluate` records a crash and carries on).

## 2. Baseline: today's `recommend_charts` on the gold set (measured)

| Metric | Value |
|---|---|
| cases / scored (zero_rows expects no suggestion) | 29 / 28 |
| top-3 contains an acceptable chart | **27 of 28 = 96.4 %** (miss: `one_row`) |
| crashes | 0 |
| suggestions that cannot be built | 0 |
| forbidden chart shown in the top five | **4** (`tiny_five_rows`: histogram; `one_row`: heatmap, histogram, scatter) |
| avoided column bound to a suggestion | **3** (`order_id`, an all-null column, a constant column) |
| cases with at least 3 distinct chart types | 22 of 29 |

Findings the numbers force:

1. **`ChartSuggestion.columns` cannot become a chart spec.** It is a bare ordered list; the registry cannot name the
   parameter for each position (`line` has `y_column` required and `x_column` optional; `heatmap` has no required
   field and takes no columns). My first scoring run reported 7 "unbuildable" suggestions, all `line`, because of exactly
   this. The gold set now carries the legacy mapping explicitly (`_LEGACY_COLUMN_FIELDS`) and prefers a `params` dict
   when a suggestion has one. **CI.3's `ChartSuggestion` must carry `params` (field → column)** (plan §3.4 updated).
2. **A sequential id, an all-null column and a constant column are all treated as measures.** The fingerprint's
   semantic roles (CI.1) are what fix this; the gold set pins it (`avoid_columns`).
3. **No minimum-rows rule.** A histogram of five rows and a scatter of one row are suggested (plan §3.4's `min_rows`).
4. **The hit rate is not discriminating.** 96.4 % already clears the plan's 90 % bar because the acceptable sets are
   deliberately generous. The bar that matters is the zero-violation ones above, plus: **today's recommender can only
   ever suggest 7 of the 14 chart types** (line, scatter, heatmap, bar, pie, histogram, box_plot; asserted by
   `tests/visualization/test_chart_recommender.py::test_every_recommend_charts_branch_is_covered_by_the_candidate_frames`).
   Candlestick, treemap, waterfall, funnel, radar, bubble and KPI are never suggested, and `ohlc_prices`,
   `hierarchy_sales`, `signed_increments`, `funnel_stages`, `bubble_gapminder_like` and `one_row` pass only because a
   generic chart is also acceptable. **CI.3's first task: add a `preferred` chart per specialist case and gate on it.**

## 3. DuckDB security posture (proved on duckdb 1.5.4, installed here)

Connection: `duckdb.connect(":memory:", config={"enable_external_access": False, "autoinstall_known_extensions":
False, "autoload_known_extensions": False})` then `SET lock_configuration=true`; query only `con.register(name,
pyarrow_table)`. Result of the probe script (`scratchpad/duck_posture.py`):

- **Works:** group-by with `sum`, exact `median`, `approx_count_distinct`, NULL as its own group (comes back as `None`,
  not `"nan"`: the reviewer's label-mismatch warning is real).
- **Refused (`PermissionException` / `InvalidInputException`):** `read_parquet`, `read_csv`, `glob`, `COPY ... TO`,
  `INSTALL`, `LOAD`, `ATTACH`, and `SET enable_external_access=true` after the lock.

Consequence: DuckDB sees only Arrow tables the code hands it, so it adds **no new file parser** to the web/worker
processes; Parquet is still parsed by pyarrow, which `stages/frames.py` already uses. **Still open (CI.1):** memory for
a 1M-row frame as an Arrow table, and whether DuckDB can scan an Arrow dataset or iterator with projection and pushdown
instead of a fully loaded table. Identifiers still need quoting (column names are tenant text; bandit skips B608).

## 4. ECharts 6 parity audit (from the ECharts docs through context7; nothing here was run)

No chart the product draws today is a **CANNOT**. Verdicts:

| Chart / feature | Verdict | How, and the parity risk |
|---|---|---|
| bar: stacked, 100 %, grouped hatched vs solid, paired horizontal, log axis | native | `bar` + `stack`, `itemStyle.decal` (works only with `aria.enabled` and `aria.decal.show`); **no native percent stack, so Python normalises to 100**; bar on a log axis unconfirmed |
| pie: donut with centre total, pie grid | native | `radius:[inner,outer]`, centre text via label or `graphic`; several `pie` series for the grid; pin `itemStyle.color` per item so colours do not drift |
| line: area gradient + end dot, dual axis, step | native | `areaStyle.color` as a JSON linear gradient; end dot via `markPoint` or a 1-point scatter; `yAxis:[…]` + `yAxisIndex` |
| scatter: hover label, Pareto frontier, pinned point, bubble | native | frontier as an extra `line` series from Python; `large:true` drops per-item styling, so the pin is a separate series; `symbolSize` is per item (no function) |
| histogram | native, **Python bins** | no native histogram series; bars on pre-binned data, `barCategoryGap:'0%'`, per-bar `itemStyle.color` |
| box plot | native | `boxplot` `[min,Q1,median,Q3,max]`, outliers as a `scatter` series, all computed in Python |
| heatmap: matrix, numbers in cells, gapped grid | native | `heatmap` + `visualMap`, `label` template `{@[2]}`, `itemStyle.borderWidth`; square cells need pixel-sized `grid` |
| treemap, radar, funnel | native | `levels[].color`/`visualMap`; `radar.splitLine.lineStyle.type:'dotted'` (dotted rings unverified); `funnel` |
| waterfall | native via a trick | stacked `bar` with a transparent base series; Python computes base/up/down; stacks crossing zero need splitting |
| candlestick + volume | native, **unverified end to end** | `candlestick` data order is `[open,close,low,high]`; volume as `bar` on a second `grid` with `axisPointer.link` |
| KPI mini charts (~60 px) | **use a plain SVG component** | one chart instance per tile is wasteful; the plan's `component` renderer |
| crosshair + one-line readout | native + client glue | `axisPointer`, `tooltip.position` pinned under the plot; custom text needs the formatter registry |
| theme from tokens, runtime switch | native (v6) | `registerTheme(json)`, `setTheme()`; explicit option styles override a theme |
| accessibility | **partial** | `aria.enabled`, `aria.label`, decals; canvas gives only a container `aria-label`, nothing per element, so **React renders a hidden/toggleable data table from the same payload** |
| large data | native, per series | `large`/`largeThreshold` (scatter, lines, bar), `sampling` (`lttb`, `minmax`, … on line and bar only), `progressive` (heatmap, scatter); `lttb` can hide a spike |
| bundle | modular | `echarts/core` + `use([…])`; the docs give **no size figures**, so measure |

**The JSON-only rule is the main engineering consequence.** A Python-built `option` cannot carry JS functions.
Everything above that needs one has a workaround: string templates (`{b}: {c}`, `{@[2]}`) where they exist; otherwise
the backend sends `{"$fmt":"pct1"}` and the SPA swaps in a function from a **named formatter registry** before
`setOption`; per-item `symbolSize`/colour instead of callbacks; `visualMap` pieces are pure JSON; a custom series is
shippable only as a name the SPA registered once with `registerCustomSeries`. Plan §3.7's option builder therefore
needs a `$fmt` convention and a test that no emitted option contains a function.

**Also true:** Plotly SVG and ECharts canvas will never be pixel-equal, so golden comparison needs a tolerance or a
re-baseline per chart. That is the sign-off decision you already answered: a difference is accepted only when you
approve it.

**Not confirmed from the docs:** `registerCustomSeries` fields; any bundle size; decal `symbol`/`rotation`; bar on a log
axis; `large` defaults for bar/candlestick; the `updateAxisPointer` payload; boxplot whisker caps and horizontal layout;
multi-grid candlestick + volume and the waterfall recipe (the examples index returned nothing); whether default decals
also hit series with none set; `{@[n]}` inside tooltip formatter strings; whether SVGRenderer helps accessibility;
keyboard navigation.

## 5. What this changes in the plan

- §3.4: `ChartSuggestion` gains `params` (done).
- §3.7 / CI.8a: a `$fmt` formatter-registry convention and a no-functions test; KPI minis are `component`, not ECharts.
- CI.3: first task is a `preferred` chart per specialist case; the metric is zero violations plus `preferred` in the top
  three, not the raw hit rate.
- CI.8 spike (before wave 8b): candlestick + volume on two grids, waterfall, bar on a log axis, decal parity.

## 6. CI.0 part 2 (done 2026-11-01): measurements

One machine (Windows 11, Intel Iris Xe), ECharts 6.1.0, Plotly 3.6.0, Chromium via Playwright, 900×500 canvas, median of
3 runs (1 where a single run took over 20 s). Every number below is from the committed scripts in
`scripts/ci0_bench/` (`npm install` there once; the commands are in §6.5). Raw output goes to `scripts/ci0_bench/out/`
(git-ignored). The GPU run uses real Direct3D11; the headless-shell run uses software GL and agrees within noise except
Plotly's `scattergl`, which collapses without a GPU (line, 1M points: 13.6 s software, 1.2 s GPU).

### 6.1 Browser render (GPU run; render ms / zoom ms)

| Points | Plotly SVG | Plotly `scattergl` | ECharts | ECharts `large` (scatter) or `sampling` (line) |
|---|---|---|---|---|
| scatter 10k | 415 / 283 | 234 / 34 | 514 / 433 | **97 / 48** |
| scatter 100k | 3,470 / 3,896 | 270 / 33 | **29,479** (1 run) / 7,984 | 397 / 267 |
| scatter 1M | 42,914 (1 run) / 37,152 | 689 / 60 | **no result in 90 s** | 3,789 / 2,484 (303 MB heap) |
| line 10k | 112 / 34 | 234 / 32 | 98 / 33 | 81 (lttb) / 32 |
| line 100k | 206 / 74 | 477 / 53 | 241 / 66 | 209 (lttb) / 44 |
| line 1M | 615 / 205 | 1,224 / 34 | 1,193 / 252 | 1,200 (lttb) / 150; 1,116 (minmax) / 165 |
| treemap 50k nodes | 16,265 | n/a | **1,980** | n/a |

- **An ECharts scatter must always set `large: true`** (`largeThreshold` 2,000 was used): plain ECharts is already 5×
  slower at 10k and unusable from 100k. This is a constraint on the option builder, not a tuning choice.
- **Above 200k points the payload, not the drawing, is the limit:** 1M points is 26–28 MB of JSON for a line and 39–41 MB
  for a scatter, with 300 MB of browser heap in ECharts. The plan's server-side reduction (≤5k line points, density bins for
  scatter above 200k) stands; neither library's `sampling` helps at 1M (draw time is unchanged, zoom is 40 % faster).
  If density bins are rejected, Plotly `scattergl` (0.7 s at 1M, GPU only) is the only renderer that draws it directly.
- **ECharts treemap is 8× faster than Plotly at 50k nodes** (2.0 s vs 16.3 s; 1.9 s vs 13.0 s in the software run): a point
  in favour of the port, though both exceed the 1 s budget, so the node cap in the render plan stays.

### 6.2 Fingerprint cost on 1M rows (a 20-column Parquet frame; 8 float, 4 int, 3 string categories, an id, 2 timestamps, a bool and a 90 %-null column)

| Method | Total | Peak working set | Arrow peak |
|---|---|---|---|
| Parquet footer only | 0.04 s | 95 MB | 0 |
| pandas, full read | 3.69 s | 687 MB | 341 MB |
| DuckDB over a loaded Arrow table | 1.82 s | 660 MB | 284 MB |
| **DuckDB over streamed record batches** | **1.54 s** | 627 MB | 198 MB |
| **Streamed uniform 100k sample, pandas stats** | **0.45 s** | 284 MB | 74 MB |

The ≤2 s budget at 1M rows is met by the streamed paths and missed by a full pandas read, so **Polars stays out**. It
answers the open question of §3: a `RecordBatchReader` can be registered with the locked-down DuckDB connection, so the
table is never held whole (Arrow peak 284 → 198 MB); the process still peaks near 0.63 GB, so a worker running a
fingerprint needs a memory limit of at least 1 GB at this size. Reading two columns of the frame costs 0.16–0.19 s and
160 MB through DuckDB.

### 6.3 Reductions at 1M rows (median of 3, ms)

| Reduction | pandas / numpy | DuckDB |
|---|---|---|
| group-by 50 categories, sum | 48 | **13** |
| group-by 50 categories, median (exact) | 68 | **33** |
| 50-bin histogram | **14** | 60 |
| M4 reduction, 1,250 buckets | **35** | 49 |

The group-by sums agree to 1.4e-15 relative (float summation order only). Every reduction is under 0.1 s, so the plan's
≤1 s reduced-render budget holds with a wide margin and speed does not choose the engine: use DuckDB for group-bys and exact
medians/quantiles (it streams, so no whole-frame load) and one engine for the rest unless a reducer proves slow.

### 6.4 The four recipe spikes (ECharts 6.1.0, canvas, pixel-checked; screenshots in `out/`)

| Recipe | Result |
|---|---|
| **Candlestick + volume on two grids** | Works. Data order `[open, close, low, high]`; the two grids do not overlap and share the x position of every date; candle and volume-bar colours come out as sent (per-item colour for volume); **one axis tooltip lists Price and Volume together and the crosshair is linked across both grids** (`axisPointer.link`, seen in `spike_candlestick.png`). |
| **Waterfall** | Works, **including a step that crosses zero**, with 7 series: one transparent base plus increase, decrease and total, each as a positive and a negative piece (ECharts stacks the two signs separately, so a crossing bar is two visible pieces and only a bar wholly on one side gets a base). Six checks per step (inside the span, just outside it) all hold. Still to do in CI.8e: hide the base and the negative-piece series from the legend and tooltip. |
| **Bar on a log axis** | Draws, from the **plot floor** (the axis minimum, 1 here) up to the value; **zero and negative values draw nothing and raise no warning**; `min: 1` changes nothing. A log bar's length is not proportional to its value, so the existing "bars start at zero" rule means a log axis on bars stays an explicit choice with a caution, and the dataset gate must refuse it for non-positive data rather than let ECharts drop them silently. |
| **Decal parity** | **Corrects the docs.** An explicit `itemStyle.decal` (rotated `rect` = hatch, small `circle` = stipple) draws with no `aria` at all, and `aria.decal.show: true` additionally gives **every series that has no decal a default one** (a plain series came out 43 % hatched) unless it sets `decal: {symbol: "none"}`. So the builder sends explicit decals and never enables `aria.decal.show`. The decal colour is an overlay colour (ink at 0.7 alpha was used) and needs a design token. |

One harness trap worth keeping: `echarts.init` on an element that already holds an instance returns that instance and
**merges** the new option into it (the first run of the decal spike inherited the previous scenario's aria and series).
The React wrapper in CI.8a must dispose on unmount.

### 6.5 Bundle weight (Vite 8 lib build of the tree-shaken import set; not the product build)

| | Raw | gzip | brotli |
|---|---|---|---|
| ECharts modular, the 10 chart types + 13 components + canvas renderer the catalogue needs | 1,068 KB | **295 KB** | 238 KB |
| ECharts modular, line + bar only | 728 KB | 203 KB | 167 KB |
| `echarts.min.js` (one file) | 1,096 KB | 360 KB | 292 KB |
| `plotly.min.js` (what `apps/web` ships) | 4,731 KB | 1,439 KB | 1,070 KB |

Tree-shaking saves little (core plus the canvas renderer is already 203 KB gzip), so the lazy ECharts chunk is about
**295 KB gzip, a fifth of Plotly's**. CI.8a budget: the ECharts chunk ≤ 300 KB gzip, **initial bundle growth 0**.

Reproduce (from `scripts/ci0_bench/`, after `npm install`; set `CI0_CHROMIUM` / `CI0_CHROMIUM_SHELL` to a browser binary
when the one Playwright expects is not installed): `node run_render.mjs chromium` (GPU) or `shell` (software GL);
`python bench_python.py make` then `python bench_python.py run`; `node run_spikes.mjs`; `node bundle_size.mjs`;
`python duck_posture.py` (the §3 posture).

### 6.6 What this changes in the plan

- §3.6 render plan: scatter always `large: true`; above 200k rows density bins are chosen for payload reasons, not draw time;
  the fingerprint uses a streamed `RecordBatchReader` into the locked-down DuckDB connection.
- CI.8a: ECharts chunk budget 295 KB gzip measured; explicit decals only; a dispose-on-unmount rule; a waterfall option
  builder with the 7-series split; the dataset gate refuses a log axis on bars with non-positive data.
- Still not confirmed (CI.8): `registerCustomSeries` fields, boxplot whisker caps and horizontal layout, `{@[n]}` inside
  a tooltip formatter string, whether `SVGRenderer` helps accessibility, keyboard navigation.

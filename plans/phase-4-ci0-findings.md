# Phase 4 step 8 — CI.0 findings (2026-10-28)

Part of `plans/phase-4-chart-intelligence.md`. **CI.0 part 1 is done** (gold set, baseline, DuckDB posture, ECharts
parity audit). **Part 2 is not done:** the browser benchmarks (ECharts `large` vs Plotly at 10k / 100k / 1M points, a
50k-node treemap), the fingerprint cost on 1M rows, and a spike of the four unverified ECharts recipes (§4). Nothing
below is a benchmark; every number is from a run on this machine today and is labelled.

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

## 6. CI.0 part 2 (not done)

Browser benchmarks to set the render-plan thresholds (they no longer decide ECharts, which is core); the fingerprint
cost on 1M rows; the DuckDB-versus-pandas reduction timing and the Arrow memory question in §3; the four ECharts recipe
spikes. These are measurements, so they need a browser harness and a 1M-row frame, not more reading.

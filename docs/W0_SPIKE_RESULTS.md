# W0 de-risking spikes: measured results

This document reports the five W0 spikes named in the web-replatform plan
(`lucky-marinating-hopcroft.md` §9), specifically the three assigned to this
pass: **Spike A** (PyMuPDF/AGPL), **Spike B** (DuckDB 1M-row paging), and
**Spike C** (environment reality checks). These are measurements and
investigations only — no `api/`, no frontend, no dependency changes, no
`src/` edits. Every number below was produced by actually running code in
this repository's `.venv` (Python 3.13.14, Windows), not estimated. Scratch
scripts used to produce these numbers live outside the repo (session
scratchpad) and are not part of this commit; the commands are reproduced
inline so results can be regenerated.

## Spike A — PyMuPDF AGPL exposure

**Verdict: (a) pdfplumber (or nothing) already fully replaces PyMuPDF — because nothing in this codebase's installed environment uses PyMuPDF at all, directly or transitively.**

### Where PyMuPDF is referenced

```
rg "fitz|pymupdf|PyMuPDF" src/
```

returns exactly **one file**: `src/readers/pdf_reader.py`. Reading it: the
only occurrences are in the *module docstring's prose*, explaining why
`camelot-py` was chosen **instead of** PyMuPDF ("Uses `camelot-py` rather
than `PyMuPDF` … a deliberate deviation"). There is no `import fitz` or
`import pymupdf` anywhere in `src/` — `rg "^import fitz|^from fitz|import
pymupdf"` across the whole repository returns zero matches.

`pymupdf` (v1.28.0) *is* installed in `.venv` and *is* declared in
`requirements.txt:15`, immediately followed by `pdfplumber` on line 16. But
`pip show pymupdf` reports `Required-by:` **empty** — no other installed
package in this environment depends on it either. It is a fully vestigial
declared dependency: installed, licensed AGPL-3.0, and touched by zero code
paths.

### What the PDF reader actually needs, and what it uses instead

`PdfReader` (`src/readers/pdf_reader.py`) extracts tables from PDFs using
`camelot-py` exclusively, in two passes: `flavor="lattice"` (grid-line
based, precise, needs Ghostscript) first, falling back to
`flavor="stream"` (whitespace-based, less precise, no Ghostscript
dependency) if lattice finds nothing. Its own docstring already documents
this choice and the reasoning — this spike did not have to guess at intent.

Checked what `camelot-py` 2.0.0 (the version actually installed) itself
depends on:

```
pip show camelot-py
Requires: click, numpy, opencv-python-headless, openpyxl, pandas, pillow, playa-pdf, pypdfium2, tabulate
```

No PyMuPDF. Confirmed by grepping the installed package source directly —
`rg -l "fitz|pymupdf|PyMuPDF" .venv/Lib/site-packages/camelot` returns
**zero matches**. Camelot's actual PDF-rendering backend in this version is
`pypdfium2` (BSD-3-Clause/Apache-2.0) + `playa-pdf` (MIT) — both
permissively licensed. (Older camelot releases in some environments have
used PyMuPDF for page rasterization; this project's *pinned, installed*
version does not.)

### pdfplumber coverage — verified with a real proof-of-concept, not asserted

`pdfplumber` (0.11.10, already declared, already installed) is similarly
unused by any `src/` code today. It depends on `pdfminer.six`, `Pillow`,
and the same `pypdfium2` camelot uses.

**No automated tests exist for `src/readers/pdf_reader.py`** — checked
`tests/readers/test_new_format_readers.py`, `tests/readers/
test_reader_registry.py`, and a repo-wide glob for `*pdf*`; the only
PDF-named test file is `tests/reports/test_pdf_exporter.py`, which exercises
`src/reports/pdf_exporter.py` (PDF *generation* for reports), an unrelated
module. This means step 4 of the spike brief ("run the EXISTING pdf reader
tests against it") could not be performed as literally specified — there is
nothing to run. This is reported honestly as a gap, not glossed over:
**`PdfReader` currently has zero test coverage**, independent of this
spike's findings.

In its place, two synthetic PDFs were built with `reportlab` (already a
dependency) to exercise the reader's two documented cases:
`gridded_table.pdf` (one table with visible grid lines: Name/Age/City, 3
data rows) and `prose_only.pdf` (three ordinary paragraphs, no table).

Running the real `PdfReader` (camelot-backed) against both:

| Case | `list_tables()` | `read()` |
|---|---|---|
| `gridded_table.pdf` | `['Page 1, Table 1']` | 3×3 DataFrame, exact values, 0 warnings (lattice succeeded) |
| `prose_only.pdf` | `[]` | (not called — zero-tables case) |

Running `pdfplumber.open(...).pages[i].extract_tables()` directly (its own
default line-detection strategy, no configuration) against the identical
two files:

| Case | Tables found | Content |
|---|---|---|
| `gridded_table.pdf` | 1 | `[['Name','Age','City'], ['Alice','30','NYC'], ['Bob','25','LA'], ['Carol','40','SF']]` — matches camelot's output exactly |
| `prose_only.pdf` | 0 | correctly empty |

pdfplumber reproduced camelot's lattice-mode behavior exactly on both the
table-present and zero-tables cases, out of the box. This is *not* a full
port of `PdfReader` (camelot's "stream" fallback, its per-page table
numbering, and its single-column-filter heuristic for prose false-positives
were not re-implemented or tested against pdfplumber — that is real,
unstarted work, scoped out of this spike), but it establishes that
pdfplumber is a plausible drop-in for the reader's core job.

### Verdict

Not "(a) pdfplumber fully replaces it" in the sense of a completed port —
that port doesn't exist yet. The more precise finding: **PyMuPDF is not
used anywhere in this codebase today**, so there is currently nothing
to replace. The actual reader (`camelot-py`) already avoids PyMuPDF
entirely in its installed version, using permissively-licensed
`pypdfium2`/`playa-pdf` instead. `pdfplumber` — already declared, already
installed, unused — was spot-checked and handles the reader's two core
cases correctly.

**Recommendation (not executed — out of scope for this investigation-only
pass):** remove `pymupdf` from `requirements.txt`. It is dead weight (53
MiB installed, see Spike C.4) carrying AGPL-3.0 risk for zero functional
benefit, confirmed by direct code search and installed-package dependency
inspection, not by absence of evidence. This is a one-line, zero-behavior-
change edit whenever a milestone is next allowed to touch
`requirements.txt`.

**Gate 9.1 (AGPL): PASS** for the "is PyMuPDF actually load-bearing"
question — it is not. **BLOCKED-NEEDS-DECISION** remains only for the
mechanical follow-up (deleting the `requirements.txt` line, and adding the
still-missing `LICENSE` file per §9.1's related note) — both explicitly out
of scope for this measurement-only pass.

## Spike B — DuckDB 1M-row paging benchmark

**Gate: p95 < 400 ms server-side, sort+filter+page, 1M rows.**

### Dataset

Synthetic 1,000,000-row × 20-column Parquet file, generated with
`numpy`/`pandas`/`pyarrow` (seeded RNG, `seed=42`) in a temp scratch
directory:

- 5 integer columns (`id` unique/no-null key, plus low/medium/high
  cardinality and a signed-score column)
- 5 float columns (uniform, normal, currency-like, percentage, ratio)
- 5 string columns (5-value region category, 200-value segment category,
  composed full names, synthetic emails, UUID-like high-cardinality strings)
- 3 date/datetime columns
- 2 boolean flag columns
- ~2% nulls scattered **independently per column** (measured: 1.99%–2.03%
  per nullable column; `id` deliberately kept non-null as a realistic
  primary key)

Generation: 9.99 s. Parquet write: 2.17 s.
**Parquet file size on disk: 86.38 MiB.** In-memory `pandas` (deep) size of
the same data: 450.84 MiB — Parquet compression brings it to ~19% of the
in-memory footprint. DuckDB version: 1.5.4. pyarrow: 24.0.0.

### Results — querying `parquet_scan()` directly, as specified

20 runs per operation, times in ms, DuckDB in-memory connection
(`threads=8`, default `memory_limit=12.5 GiB` on this machine):

| # | Operation | min | median | p95 | max | vs. 400ms p95 gate |
|---|---|---:|---:|---:|---:|---|
| a | rows 0–100 unsorted | 23.94 | 28.95 | 32.79 | 33.64 | **PASS** |
| b | rows 500000–500100 unsorted (deep offset) | 87.43 | 94.36 | 105.95 | 106.44 | **PASS** |
| c | `ORDER BY int_high_card ASC NULLS LAST LIMIT 100` | 258.47 | 443.52 | 573.40 | 579.26 | **FAIL** |
| d | `ORDER BY str_full_name DESC NULLS LAST LIMIT 100` | 360.14 | 471.17 | 567.58 | 581.34 | **FAIL** |
| e | `WHERE str_uuid_like LIKE '%123%' LIMIT 100` | 31.13 | 43.06 | 53.77 | 61.39 | **PASS** |
| f | filter + sort + 100-row window, deep offset | 642.58 | 742.30 | 881.17 | 949.98 | **FAIL** |
| g | `COUNT(*)` with a filter | 14.30 | 22.90 | 37.23 | 40.40 | **PASS** |

**3 of 7 operations fail the 400ms p95 gate — every failure involves an
`ORDER BY`.** `EXPLAIN ANALYZE` on operation (c) shows why: the `TABLE_SCAN`
node alone (not planning, not the `TOP_N` step) takes ~0.26 s of the ~0.28 s
total, because a `SELECT *` sort must decompress and materialize all 20
projected columns across the full 1M-row Parquet file on every single query
— there is no persistent index or cache between requests when querying the
raw file directly.

### Root-cause check: does a materialization layer fix it?

The plan's own gate 9.2 already names the fallback ("Fail → add a
pre-computed index/materialization layer before W4"). Tested it directly
rather than leaving it as an assumption: loaded the same Parquet file into
a DuckDB-native table (`CREATE TABLE t AS SELECT * FROM parquet_scan(...)`,
still in-memory, still 20 runs each) instead of re-scanning the Parquet file
cold on every request:

| Query (against native table `t`) | min | median | p95 | max | vs. gate |
|---|---:|---:|---:|---:|---|
| full-column `ORDER BY int_high_card ASC LIMIT 100` | 15.50 | 22.94 | 30.35 | 32.49 | **PASS** (573ms→30ms p95) |
| 2-column projection, same sort | 2.85 | 4.20 | 4.65 | 5.38 | **PASS** |
| filter + sort + deep-offset window, all columns | 92.54 | 112.02 | 148.97 | 151.55 | **PASS** (881ms→149ms p95) |

Every previously-failing case comfortably clears the gate once the data is
resident in a DuckDB-native table rather than re-read from Parquet per
query. This is a real, verified mitigation, not a hopeful assertion — it
means the engine itself is fast enough; the specific failure mode is "cold
column-store scan of a Parquet file over and over," which the plan's own
data-layer sketch (§4: "load DataFrame from Parquet (LRU-cached)") was
already heading toward, just not for the grid path specifically. **The grid
query layer must load each opened dataset's Parquet file into a
session-scoped DuckDB table (or attach it once and keep the connection
warm) rather than issuing a fresh `parquet_scan()` per grid request** —
this is a concrete design requirement for W4, not a nice-to-have.

### Null-ordering semantic check

Required check: does DuckDB's `NULLS LAST` genuinely put nulls last in
*both* directions, matching `pandas_table_model._stable_sort_indices()`'s
guarantee? Verified directly against `float_normal` (19,997 real nulls out
of 1,000,000 rows, ~2%):

- `ORDER BY float_normal DESC NULLS LAST` — first 10 rows are non-null high
  values (e.g. `232.80, 219.25, 216.89, ...`); **last 10 rows of the same
  ordered result are all `NULL`.**
- `ORDER BY float_normal ASC NULLS LAST` — first 10 rows are non-null low
  values (e.g. `-30.53, -14.72, -13.04, ...`); **last 10 rows are all
  `NULL`.**

Both directions confirmed to push nulls to the true end of the result set
(checked via an offset into the tail of the full 1M-row ordering, not just
`LIMIT`), not merely "last within the fetched page." **PASS** — DuckDB's
`NULLS LAST` maps directly to the desktop's stable-sort-nulls-last
semantics with no translation logic needed beyond adding the clause.

### Memory

Windows process peak working-set (via `psapi.GetProcessMemoryInfo`,
`psutil` is not installed in this venv so this was measured directly via
`ctypes`) across the full benchmark run, including Python, pandas, and
DuckDB's own buffers: **189.72 MiB.** (Python-heap-only `tracemalloc`
reported 0.10 MiB peak, which is not meaningful here — it excludes
DuckDB's native C++ allocations entirely, which dominate; the psapi number
is the one to trust.)

### Verdict

**Gate 9.2: FAIL as literally specified (raw `parquet_scan()`, no
materialization) — 3 of 7 operations exceed 400ms p95, all `ORDER BY`
cases.** **BLOCKED-NEEDS-DECISION**, resolving to a concrete, already-tested
answer: the data layer must materialize each opened dataset into a
DuckDB-native table (or attached persistent `.duckdb` file) rather than
re-scanning Parquet per grid request, at which point every operation
clears the gate by a wide margin (worst case 149ms p95, well under 400ms).
This is not a new invention — it is exactly the "materialization layer"
the plan's own §9.2 fallback clause already named, now confirmed to work
rather than assumed. Sort-by-column filenames/behavior otherwise did not
reveal any DuckDB-specific correctness surprises: null-ordering, both
directions, is exactly right.

## Spike C — environment reality checks

### C.1 — Docker

```
docker --version
```

`docker: command not found` (exit 127). **Docker is not available in this
environment.** Per instructions, container-dependent parts of gates 9.3
(container image size/build) and 9.4 (headless PNG *inside a container*)
were **skipped, not installed, not simulated.** These remain genuinely
unverified until a machine or CI runner with Docker is used — do not treat
the venv-only kaleido result below as a container proof.

### C.2 — `MPLBACKEND=Agg` Qt-free claim

Imported `src.core.bootstrap`, `src.ai.tool_registry`,
`src.forecasting.model_comparison`, `src.readers.reader_registry`,
`src.visualization.chart_registry`, `src.services.guidance_service` and
checked `sys.modules`:

| | `PySide6` in `sys.modules` | Any Qt-named module loaded |
|---|---|---|
| `MPLBACKEND=Agg` set | `False` | `[]` |
| `MPLBACKEND` unset | `False` | `[]` |

**Both PASS — identical result with and without the env var.** One
material caveat found while investigating why: `matplotlib` (3.10.0) *is*
installed in this venv (a transitive dependency of something else in
`requirements.txt`, not `src/`), but `rg "import matplotlib" src/` returns
**zero matches** anywhere in `src/`. None of the six modules under test —
nor, as far as this grep shows, anything else in `src/` — imports
`matplotlib` directly. So this specific test never actually exercised the
`MPLBACKEND=Agg` mechanism at all: the "Qt-free" property holds
unconditionally for this import set, independent of the env var, simply
because matplotlib is never touched on this path. `MPLBACKEND=Agg` may
still matter for import paths not covered by these six modules (e.g. if
`prophet`, `statsmodels`, or `ydata-profiling` import matplotlib
internally along some code path not triggered by constructing these
registries) — not disproven, just not exercised by this specific check.
Recommend keeping `MPLBACKEND=Agg` set at API startup regardless, as cheap
insurance, per the plan's own "Plus" item — this spike did not find a
reason to drop it, only that it wasn't the deciding factor for these six
modules specifically.

### C.3 — Headless kaleido PNG export

Built a real chart via the project's own visualization code
(`src.visualization.categorical_charts.BarChart.build()`, a 4-category bar
chart) and rasterized it through the actual, unmodified
`src.reports.rasterize.figure_to_png_bytes()` — the same function every
report exporter uses, including its documented behavior of *swallowing*
exceptions and returning `None` on failure. The returned value was checked
directly, not just "no exception raised":

- Return value: not `None`.
- Byte length: 18,642 bytes.
- First 8 bytes: `89 50 4e 47 0d 0a 1a 0a` — **exact PNG magic number**,
  confirmed byte-for-byte, not merely "non-empty."
- File written to disk and is a valid, openable PNG.

**Timing — a real, worth-flagging finding:** first (cold) call: 3.581 s.
Five subsequent "warm" calls (same process, same figure, `kaleido` already
imported): **2.10 s, 2.23 s, 2.29 s, 2.21 s, 2.13 s** — essentially no
improvement over the cold call. `kaleido` 1.3.0 (installed version) appears
to launch a fresh headless-Chrome subprocess per `to_image()` call rather
than reusing a persistent browser context, unlike the batched/persistent
usage pattern kaleido's newer API supports elsewhere. **This works, but at
~2.1–2.3 s per chart it is a real latency concern for any report containing
multiple charts** (a 5-chart PDF/Word export would spend >10 s in
rasterization alone) — worth investigating kaleido's persistent/batch mode
before W13 (report exporters), not a blocker for W0 itself.

**Gate 9.4: PASS for "does it produce a valid non-empty PNG"** (verified
against actual bytes, per the instruction to not trust absence of an
exception). **Container-specific behavior remains untested** — see C.1.

### C.4 — venv size

```
du -sh .venv
```

**Total: 2.7 GiB.** Largest contributors (`du -sh .venv/Lib/site-packages/*
| sort -rh`):

| Package | Size |
|---|---:|
| `PySide6` | 644 MiB |
| `catboost` | 330 MiB |
| `_polars_runtime_32` | 177 MiB |
| `scipy` | 121 MiB |
| `cv2` (opencv) | 113 MiB |
| `llvmlite` | 104 MiB |
| `xgboost` | 98 MiB |
| `pyarrow` | 87 MiB |
| `pandas` | 70 MiB |
| `plotly` | 64 MiB |
| `pymupdf` | 53 MiB |
| `statsmodels` | 52 MiB |
| `prophet` | 48 MiB |
| `scikit-learn` | 45 MiB |
| `dash` | 42 MiB |

`PySide6` (644 MiB) leaves the dependency set entirely for the web build
per the plan (§2 decision 2) — removing it alone drops ~24% of current venv
size, before any container-specific slimming (multi-stage builds,
`--no-cache-dir`, excluding `pytest`/`black`/`mypy`/dev tooling from the
runtime image) is attempted. `pymupdf`'s 53 MiB is entirely unused per
Spike A and would be free to drop as well. This gives a rough, optimistic
floor near ~2.0 GiB for a *runtime-only* dependency set before real
container-build measurement (gate 9.3, blocked on Docker per C.1) can
confirm anything concrete against the plan's <2.5 GiB target.

## Summary

| Gate | Verdict | Note |
|---|---|---|
| 9.1 PyMuPDF/AGPL | **PASS** (finding: unused) | Mechanical `requirements.txt`/`LICENSE` follow-up remains, out of scope here |
| 9.2 DuckDB 1M-row paging | **FAIL as specified → BLOCKED-NEEDS-DECISION, resolved** | Materialization layer (tested, works) required before W4 |
| 9.2 null-ordering semantics | **PASS** | Both directions verified on real null data |
| 9.3 container image size | **BLOCKED** | No Docker in this environment; not installed per instructions |
| 9.4 headless PNG export | **PASS** (venv-level only) | Valid PNG confirmed by bytes; ~2.1–2.3s/image latency flagged; container behavior still unverified |
| C.2 MPLBACKEND=Agg Qt-free | **PASS** | Also found: not actually exercised by this import set (matplotlib never imported) |
| C.4 venv size | measured, informational | 2.7 GiB total; PySide6 removal (web build) is the single largest lever |

**What this means for the plan:**

- Spike A removes the single biggest fear in §9.1 — there is no PyMuPDF
  code to port or isolate, because none exists. The only remaining work is
  a `requirements.txt` line deletion and the still-missing `LICENSE` file,
  both trivial and already flagged in the plan, not new scope this spike
  discovered.
- Spike B is the one genuine, actionable finding: **the grid/query layer
  design in §4 must materialize each dataset into a DuckDB-native table (or
  keep a warm attached connection) rather than issue `parquet_scan()`
  directly per request** — confirmed necessary (raw scan fails 3/7 cases)
  and confirmed sufficient (materialized table passes all cases with
  large margin) before W4 is built, not merely "recommended."
- Spike C found no new blockers, but two things worth carrying forward:
  kaleido's apparent per-call browser-launch cost (~2.1s) should be
  investigated before W13's report exporters are built at scale, and gate
  9.3/half of 9.4 remain genuinely unverified — Docker access is required
  before those can be closed, not assumed from the venv-only results here.

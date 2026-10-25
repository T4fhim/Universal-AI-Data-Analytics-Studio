# mypy debt: what CI does not check, and why

`.github/workflows/ci.yml`'s `mypy (clean packages)` step does not run `mypy` against all of
`uadas_core/`. It runs against an explicit list of packages/modules that are genuinely clean
under `mypy --ignore-missing-imports --follow-imports=silent` (the same flags CI uses). This
document is the other half of that scoping decision: exactly which packages are *not* in the
list, what is wrong in each, and how large the debt is, so the gap does not silently get
forgotten.

Since Phase 2.5 the Qt shell (`src/`) is gone, so `uadas_core/` is the only tree there is to
check. Everything the old version of this document said about `src/ui/` (the `main_window.py`
errors, the controllers/workbench/widgets scope) described code that no longer exists and has
been removed.

## How to reproduce these numbers

```powershell
python -m mypy uadas_core --ignore-missing-imports --follow-imports=silent --no-incremental
```

**Measured 2026-10-04 (Phase 2.7, branch `phase-2/retire-desktop-ui`): 42 errors in 17 files
(143 source files checked).**

The CI list (below) is clean on its own: running the CI command reports
`Success: no issues found in 80 source files`.

## What CI checks

`uadas_core/core`, `uadas_core/services`, `uadas_core/analysis`, `uadas_core/database`,
`uadas_core/results`, `uadas_core/persistence`, `uadas_core/jobs`, `uadas_core/provenance`,
`uadas_core/theme`, `uadas_core/a11y`, `uadas_core/help`, `uadas_core/data_table`,
`uadas_core/actions`, `uadas_core/models`, `uadas_core/bootstrap.py`,
`uadas_core/command_stack.py`.

When a module becomes clean, add it to the list in `ci.yml` rather than treating a bare
`mypy uadas_core` run as the target.

## What CI does not check: 7 packages, 42 errors

The debt is not zero. Every `uadas_core` package outside the CI list has at least one error:

| Package | Errors | Files |
|---|---|---|
| `uadas_core/visualization/` | 13 | `advanced_charts.py` 6, `categorical_charts.py` 2, `continuous_charts.py` 2, `distribution_charts.py` 2, `forecast_charts.py` 1 |
| `uadas_core/ai/` | 8 | `llm_provider.py` 8 |
| `uadas_core/reports/` | 7 | `word_exporter.py` 7 |
| `uadas_core/cleaning/` | 5 | `missing_values.py` 2, `duplicates.py` 1, `text_normalization.py` 1, `type_conversion.py` 1 |
| `uadas_core/readers/` | 4 | `csv_reader.py` 1, `powerpoint_reader.py` 1, `reader_registry.py` 1, `word_reader.py` 1 |
| `uadas_core/plugins/` | 3 | `plugin_loader.py` 3 |
| `uadas_core/forecasting/` | 2 | `exponential_smoothing.py` 2 |

### `uadas_core/visualization/` -- 13 errors, all `Signature of "build" incompatible with supertype "BaseChart"`

Every concrete chart builder's `build(dataframe, **kwargs)` signature takes its own named
required/optional keyword arguments rather than `**kwargs: Any`, which mypy's Liskov
substitution check rejects against `BaseChart.build(cls, dataframe, **kwargs)`. Fixing this for
real means either loosening `BaseChart.build` to accept anything (weakens the interface for
every future chart) or adding `# type: ignore[override]` to all thirteen with a comment pointing
at the same interface-design tradeoff. That is an architecture decision, not a bug, so it has not
been made unilaterally.

### `uadas_core/cleaning/` -- 5 errors, same pattern

`type_conversion.py`, `text_normalization.py`, `missing_values.py` (x2), `duplicates.py`:
`Signature of "apply" incompatible with supertype "BaseOperation"` -- the identical
per-operation-named-kwargs vs. `apply(dataset, **kwargs)` mismatch as the chart builders. Same
reasoning, same recommendation: an interface-design call for whichever milestone next touches
`BaseOperation`/`BaseChart`, not something to paper over with an ignore-comment sweep.

### `uadas_core/ai/` -- 8 errors (`llm_provider.py`)

All are third-party SDK typing mismatches: Anthropic's `Messages.create(tools=...)` overload set
(`:164`), `google-genai`'s `Content | None` union and its optional `call_id`/`name` fields
(`:250`, `:254`, `:255`), and the OpenAI-style chat `Completions.create(tools=...)` call plus the
`ChatCompletionMessageFunctionToolCall | ChatCompletionMessageCustomToolCall` union (`:343`,
`:357`, `:361`, `:365`). Each provider's docstring already explains why it translates its SDK's
wire format by hand, and the SDKs' generated stubs are stricter than the runtime behaviour (call
sites narrow the union before use, but mypy flags the access on the wider type). Fixing it means
per-call-site `cast()`/`isinstance` narrowing across three SDKs' type shapes, or
`# type: ignore[code]` with a call-site-specific rationale -- real work that should be verified
against each provider rather than rushed. (`tool_registry.py`, which used to carry one error,
is clean now.)

### `uadas_core/reports/word_exporter.py` -- 7 errors

`python-docx`'s `Document` resolves to effectively-`Any` (`Document?` in mypy's own output):
`Function "docx.api.Document" is not valid as a type` (`:61`) and then `add_heading`,
`add_paragraph` (x3), `styles` and `add_picture` reported as missing attributes (`:62`-`:73`).
This is a stub problem in the third-party package, not a bug in this module. Fixable with a
`# type: ignore[...]` per call site or by typing the document parameter as `Any`, but seven
call-site ignores in one file reads as "sweeping", so it was left.

### `uadas_core/readers/` -- 4 errors

Four independent, unrelated errors, left as debt rather than four one-line fixes rushed in
without reader-specific coverage: `word_reader.py:189` (a `Path` passed where `python-docx`'s
`Document()` stub declares `str | IO[bytes] | None`), `csv_reader.py:302` (a `max(..., key=...)`
call whose key function's inferred type does not match the overloaded `max` signature),
`powerpoint_reader.py:97` (`"object" has no attribute "table"` -- a shape looked up from a
`table_shapes` mapping whose value type is inferred as `object`), and `reader_registry.py:135` (`type[BaseReader]` accessed for a
`SUPPORTED_EXTENSIONS` class attribute that is not declared on the base class).

### `uadas_core/plugins/plugin_loader.py` -- 3 errors

`Argument 1 to "register_reader" has incompatible type "type[object]"; expected
"type[BaseReader]"` (`:152`), and the same for `register_operation` (`:154`) and
`ChartRegistration` (`:166`). The loader necessarily holds dynamically-imported, unverified
third-party classes before it has confirmed they subclass the right `Base*`, so `type[object]` is
the honest type at that point; narrowing needs a runtime `issubclass()` check mypy can follow
(the loader may already have one and just need reordering around it) or a `cast()`. Plugin
loading is security- and correctness-sensitive (arbitrary code from a plugin directory) and
deserves its own focused pass rather than a type-only patch.

### `uadas_core/forecasting/exponential_smoothing.py` -- 2 errors

`Unsupported operand types for * ("int" and "None")` at `:110` and `:112` -- a real, narrow
`Optional` handling gap (a value typed `int | None` reaches an arithmetic expression without a
`None` check). Small enough to fix in isolation, but whether the `None` case should default to a
specific value or be treated as a caller error is a forecasting-domain call, so it is flagged
here as a straightforward follow-up.

## History

Earlier revisions of this document tracked a rolling count across the two-tree
(`src/` + `uadas_core/`) era: 79 errors / 22 files at the milestone-19 remediation pass, 74 / 19
after the Phase 1 carve-out, and 44 / 18 after Phase 1.4's typed `DependencyContainer.resolve()`
overload cleared 29 `resolve() -> object` errors in the (since deleted) `src/ui/main_window.py`.
The deletion of `src/` in Phase 2.5, the extraction of `uadas_core/models/` and the lifting of
`theme`, `a11y`, `help`, `data_table` and `actions` into `uadas_core/` (all kept clean and folded
into the CI list) brought the remaining debt to the 42 errors above, all of it pre-existing in
packages that were never on the list.

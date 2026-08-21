# mypy debt: what CI does not check, and why

`.github/workflows/ci.yml`'s `mypy (clean packages)` step does not run
`mypy` against the full `src/` tree. It runs against an explicit, growing
list of packages/modules that are genuinely clean under
`mypy --ignore-missing-imports --follow-imports=silent` (the same flags CI
uses). This document is the other half of that scoping decision: exactly
which packages are *not* in the list, why, and how large the debt is, so
the gap doesn't silently get forgotten again the way it did between
milestone 16 (CI's mypy step first added, scope frozen at four packages)
and this remediation pass (milestone 19-27 added whole new `src/ui/`
packages -- controllers, workbench, widgets, results -- that were never
folded into CI's scope even though they were kept clean).

## How to reproduce these numbers

```powershell
python -m mypy src/ --ignore-missing-imports --follow-imports=silent
```

As of this document's commit: **72 errors in 19 files** (down from 79
before this remediation pass fixed 7 genuine, narrowly-scoped bugs in
`src/ui/controllers/pipeline_controller.py`,
`src/ui/widgets/data_table/pandas_table_model.py`, and
`src/ui/dialogs/create_visualization_dialog.py` -- see git history for the
commit that introduced this document for the exact diffs).

## Excluded packages, categorized

### `src/ui/main_window.py` -- 29 errors, all one root cause

Every error here is `"object" has no attribute "..."` or `Argument N ...
has incompatible type "object"; expected "<ServiceType>"`. This is
`DependencyContainer.resolve()` returning `object` (see
`docs/ARCHITECTURE.md`'s dependency-container section) -- every
`resolve(...)` call site in `main_window.py`'s `_build_controllers`/
`_build_services` wiring loses the concrete service type and mypy correctly
flags every attribute access and constructor argument built from that
result. This is an architecture-level typing gap, not a bug in
`main_window.py` itself, and fixing it means adding a typed
`resolve(self, key: type[T]) -> T` overload (or an equivalent generic
registration API) to `DependencyContainer` itself -- real, but
out-of-scope for a remediation pass whose brief was "narrowly-scoped
fixes, not sweeping changes." Flagged here as a recommendation for
whichever milestone next touches `DependencyContainer`.

### `src/ai/` -- 9 errors (`llm_provider.py`: 8, `tool_registry.py`: 1)

`llm_provider.py`'s errors are all third-party SDK typing mismatches
(Anthropic's `Messages.create(tools=...)` overload set, `google-genai`'s
`Content | None` union, OpenAI's `ChatCompletionMessageFunctionToolCall |
ChatCompletionMessageCustomToolCall` union) -- each provider's own
docstring already explains why it translates its SDK's wire format by
hand (see `BaseLLMProvider`'s docstring in `src/ai/llm_provider.py`), and
the SDKs' own generated stubs are stricter than the code's actual runtime
behavior (e.g. every call site already narrows the union before use, but
mypy still flags the access on the wider type). Narrowly fixing this
means either per-call-site `cast()`/`isinstance` narrowing across three
different SDKs' type shapes, or `# type: ignore[code]` with a
call-site-specific rationale comment -- real work, not attempted in this
pass to avoid rushing SDK-specific casts without testing each provider
live against a real API key. `tool_registry.py`'s one error (`"type" has
no attribute "build"`) is the same untyped-registry-dict pattern that was
fixed narrowly in `create_visualization_dialog.py` in this same pass (see
git history) -- worth the same treatment, left out only because fixing it
alone does not make the rest of the package clean enough to add to CI.

### `src/reports/word_exporter.py` -- 7 errors

`python-docx`'s `Document` class returns effectively-`Any` (`Document?` in
mypy's own output) from its constructor and every method
(`add_heading`/`add_paragraph`/`add_picture`/`styles`) -- this is a
missing/incomplete third-party stub problem (`python-docx` ships no
`py.typed` marker), not a bug in this module. Fixable with an
`# type: ignore[attr-defined]` per call site plus a short comment citing
this, but not attempted here since seven call-site ignores across one
file reads closer to "sweeping" than the "reasonable, narrowly-scoped
fixes" this pass was asked for.

### `src/visualization/*.py` -- 13 errors, all `Signature of "build"
incompatible with supertype "BaseChart"` (`distribution_charts.py`,
`continuous_charts.py`, `categorical_charts.py`, `forecast_charts.py`,
`advanced_charts.py`)

Every concrete chart builder's `build(dataframe, **kwargs)` signature
narrows or widens `BaseChart.build`'s declared parameters in a way mypy's
Liskov substitution check rejects (each chart takes its own named
required/optional keyword arguments rather than `**kwargs: Any`, which is
precisely what makes `create_visualization_dialog.py`'s "no shared
building-signature interface" docstring note true). Fixing this for real
means either loosening `BaseChart.build`'s own signature to
`**kwargs: Any` (weakens the interface for every future chart) or adding
an explicit `# type: ignore[override]` to all thirteen with a comment
pointing at the same interface-design tradeoff -- an architecture
decision, not a bug, and out of scope for this pass to make unilaterally.

### `src/cleaning/*.py` -- 5 errors, same pattern as visualization

`type_conversion.py`, `text_normalization.py`, `missing_values.py` (x2),
`duplicates.py`: `Signature of "apply" incompatible with supertype
"BaseOperation"` -- the identical per-operation-named-kwargs vs.
`apply(dataset, **kwargs)` shape mismatch as the chart builders above.
Same reasoning, same recommendation: an interface-design call for
whichever milestone next touches `BaseOperation`/`BaseChart`, not
something to paper over with an ignore-comment sweep here.

### `src/forecasting/exponential_smoothing.py` -- 2 errors

`Unsupported operand types for * ("int" and "None")` -- a real, narrow
`Optional` handling gap (a config value typed as `int | None` reaches an
arithmetic expression without a `None` check first). Small enough to fix
in isolation, but touching forecasting's numeric logic without a forecast
domain expert's review of whether the `None` case should default to a
specific value or actually be treated as a caller error was judged
outside a mypy-scoping remediation pass's remit -- flagged here as a
straightforward follow-up.

### `src/readers/*.py` -- 3 errors

`word_reader.py` (a `Path` passed where `python-docx`'s `Document()` stub
declares `str | IO[bytes] | None`), `csv_reader.py` (a `max(..., key=...)`
call whose key function's inferred type doesn't match the overloaded
`max` signature mypy selects), `reader_registry.py` (`type[BaseReader]`
accessed for a `SUPPORTED_EXTENSIONS` class attribute mypy doesn't see
declared on the base class). Each is independently fixable but unrelated
to the others -- left as one paragraph of debt rather than three
one-line fixes rushed in without reader-specific test coverage to back
them.

### `src/plugins/plugin_loader.py` -- 3 errors

`Argument 1 to "register_reader" has incompatible type "type[object]";
expected "type[BaseReader]"` (and the same for `register_operation`/
`ChartRegistration`) -- the plugin loader necessarily works with
dynamically-imported, unverified third-party classes before it has
confirmed they subclass the right `Base*`, so `type[object]` is the
honest type of what it holds at that point in the function; asserting
the narrower type requires either a runtime `issubclass()` check mypy can
narrow on (which the loader may already have and just needs reordering
around), or a `cast()`. Left out of this pass because plugin loading is
security/correctness-sensitive surface (arbitrary code execution from a
plugin directory) that deserves its own focused pass, not a type-only
patch bundled into a mypy-scoping remediation.

## What changed in this pass

Newly added to CI's mypy scope (all now genuinely clean):
`src/core`, `src/services`, `src/analysis`, `src/database`, `src/workers`,
and within `src/ui/`: `controllers`, `workbench`, `widgets`, `results`,
`dialogs`, and every standalone top-level `src/ui/*.py` module except
`main_window.py` (`command_stack.py`, `command_palette.py`,
`dataset_close_menu.py`, `dock_manager.py`, `menu_bar.py`, `status_bar.py`,
`theme_manager.py`, `toolbar.py`, `ui_state_bus.py`, `worker_runner.py`,
`__init__.py`).

Three genuine bugs were fixed to get there, not ignored or worked around:

- `src/ui/controllers/pipeline_controller.py`: `CommandStack`, `Dataset`,
  and `DatasetPointerCommand` were used as real type annotations
  (constructor parameter and method signature) with no import at all --
  silently safe at runtime only because `from __future__ import
  annotations` defers annotation evaluation, but a real gap mypy caught
  correctly. Fixed by adding the missing imports.
- `src/ui/widgets/data_table/pandas_table_model.py`: `rowCount`/
  `columnCount`/`data` declared their `parent`/`index` parameter as
  `QModelIndex` only, narrower than `QAbstractItemModel`'s own
  `QModelIndex | QPersistentModelIndex` -- a real Liskov violation (a
  caller holding a `QPersistentModelIndex` and calling through the base
  class reference would hit an argument-type mismatch these three methods
  didn't actually guard against, they just happened to only ever be
  called with `QModelIndex` so far). Fixed by widening the parameter
  types to match the base class exactly.
- `src/ui/dialogs/create_visualization_dialog.py`: `_CHART_REGISTRY` was
  typed as `dict[str, tuple[type, ...]]` (bare `type`, no chart-class
  bound), so `builder_class.build(...)` lost `BaseChart`'s declared
  `build` method entirely. Fixed by typing the registry's chart-class slot
  as `type[BaseChart]`.

Before/after full-repo count: **79 errors in 22 files -> 72 errors in 19
files.**

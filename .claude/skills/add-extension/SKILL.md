---
name: add-extension
description: Scaffold a new BaseReader, BaseOperation, BaseChart, or BaseLLMProvider implementation for Universal AI Data Analytics Studio, following the project's existing stateless-classmethod pattern and file conventions. Use when adding a new file format reader, cleaning operation, chart type, or LLM provider.
---

# Add Extension

Generates the boilerplate for a new concrete implementation of one of this project's four `Base*`
extension points, matching the shape every existing implementation already follows. This skill
only scaffolds the file; it does **not** replace `project-architecture`'s integration checklist —
run that skill immediately after, before declaring the new extension complete.

## Scope boundary

This skill does NOT provide the integration-point checklist (registry entry, UI filter update,
config sync) — that's `project-architecture`. It does NOT provide milestone completion sign-off —
that's `milestone-verification`. It only generates a correctly-shaped starting file.

## Which Base* type, and where it lives

| Extension point | Base class | Lives under | Registry it must be added to |
|---|---|---|---|
| File format reader | `BaseReader` (`src/readers/base_reader.py`) | `src/readers/` | `src/readers/reader_registry.py`'s `_REGISTERED_READERS` |
| Cleaning operation | `BaseOperation` (`src/cleaning/base_operation.py`) | `src/cleaning/` | `src/cleaning/operation_registry.py` |
| Chart type | `BaseChart` (`src/visualization/base_chart.py`) | `src/visualization/` | `src/visualization/chart_registry.py` |
| LLM provider | `BaseLLMProvider` (`src/ai/llm_provider.py`) | `src/ai/` | wired into `create_provider()` in `src/ai/llm_provider.py` |

(This project also has registries for other extension families — `src/database/connection_registry.py`,
`src/ai/tool_registry.py`, plus UI-side `action_registry.py`/`stage_registry.py`/
`result_renderer_registry.py` — those follow the same "register it or it doesn't exist to the rest
of the app" principle but are outside this skill's four `Base*` types.)

## Shape to follow (stateless, classmethod-only)

Three of the four types — `BaseReader`, `BaseOperation`, `BaseChart` — are **stateless and
classmethod-only**: never instantiated, held in a registry as classes, inputs validated before real
work happens. `BaseLLMProvider` is the documented exception (it holds a real SDK client and
conversation history) — see CLAUDE.md's `Base*` section before scaffolding a new provider.

### Reader skeleton

```python
# File: src/readers/<name>_reader.py
"""<Why this reader exists and what format it handles — not just what it does.>"""
from __future__ import annotations

from pathlib import Path

from src.readers.base_reader import BaseReader
from src.core.models import Dataset  # adjust to actual Dataset import path


class <Name>Reader(BaseReader):
    """:class:`BaseReader` implementation for <format>.

    See :class:`src.readers.base_reader.BaseReader` for the contract this fulfils.
    """

    @classmethod
    def can_read(cls, path: Path) -> bool:
        ...

    @classmethod
    def list_tables(cls, path: Path) -> list[str]:
        ...

    @classmethod
    def read(cls, path: Path, table_name: str | None = None) -> Dataset:
        ...
```

### Operation skeleton

```python
# File: src/cleaning/<name>_operation.py
"""<Why this operation exists.>"""
from __future__ import annotations

from src.cleaning.base_operation import BaseOperation
from src.core.models import Dataset


class <Name>Operation(BaseOperation):
    """:class:`BaseOperation` implementation for <what it cleans>.

    Never mutates the input :class:`Dataset` in place — returns a new one with
    ``parent_dataset_id`` and ``derivation_description`` set, per the project's lineage contract.
    """

    @classmethod
    def apply(cls, dataset: Dataset, **kwargs: object) -> Dataset:
        # Build the new DataFrame, then:
        # return Dataset(..., parent_dataset_id=dataset.dataset_id,
        #                 derivation_description="<what changed and why>")
        ...
```

### Chart skeleton

```python
# File: src/visualization/<name>_chart.py
"""<Why this chart exists.>"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.visualization.base_chart import BaseChart


class <Name>Chart(BaseChart):
    """:class:`BaseChart` implementation for <chart type>."""

    @classmethod
    def build(cls, dataframe: pd.DataFrame, **kwargs: object) -> go.Figure:
        ...
```

### LLM provider skeleton

Read `src/ai/llm_provider.py`'s existing providers (`AnthropicProvider`, `GeminiProvider`,
`GroqProvider`) first — a new provider implements `send()` / `append_user_message()` /
`append_assistant_turn()` / `append_tool_results()`, translating its SDK's own wire format to the
shared `LLMTurn`/`PendingToolCall` shape, and is wired into `create_provider()`. This is the one
extension point that is NOT stateless/classmethod-only; don't force it into that shape.

## After scaffolding

1. Run `project-architecture` for this extension type's exact registry/integration checklist —
   the table above names the registry, but that skill owns verifying it was actually done.
2. Add the corresponding test file under `tests/<matching package>/`.
3. Before declaring the new extension complete, run `milestone-verification`.

## Conventions this scaffold already follows (don't skip when hand-editing)

- `# File: <path>` as the first line, module docstring explaining *why*, not just what.
- `from __future__ import annotations` at the top.
- Type hints throughout; Sphinx-style `:class:`/`:meth:` cross-references in docstrings.
- `ruff format`/`ruff check --fix` run automatically on save (`.claude/hooks/quality-check.ps1`) —
  don't hand-format after using this skill, but `black`/`isort`/`mypy` are not part of that hook and
  still need to be run explicitly to match CI (see CLAUDE.md's Commands section).

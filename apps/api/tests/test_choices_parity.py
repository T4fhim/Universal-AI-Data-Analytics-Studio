# File: apps/api/tests/test_choices_parity.py
"""The API's value sets are pinned to the core, and the models never import the core.

Why: ``SourceFormat``, ``ChartType``, ``ReportFormat``, ``NodeKind`` and ``EdgeKind``
mirror things ``uadas_core`` owns. Models must not import the core at runtime, so the
values are copied -- which is exactly the "registry plus a separately hard-coded
consumer" gap CLAUDE.md warns about. This is the only place the API imports the core to
compare: if the core gains a reader, a chart, a report format or a graph element and this
side is not updated, a test here fails instead of a user hitting a rejected value.

Each derivation asserts it found *something* before comparing, so a refactor that makes
the core-side extraction silently return an empty set cannot turn into a vacuous pass.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import sys
from pathlib import Path

import pytest

import uadas_api
from uadas_api.exports.choices import ReportFormat
from uadas_api.pipeline.choices import EdgeKind, NodeKind
from uadas_api.workspaces.choices import ChartType, SourceFormat

# A built-in reader that deliberately sets no source_format of its own: it unpacks an
# archive and delegates to the reader for whatever is inside, which stamps the format.
READERS_WITHOUT_OWN_FORMAT = frozenset({"ArchiveReader"})


def _constant_strings(node: ast.expr) -> set[str] | None:
    """The string literals ``node`` can evaluate to, or ``None`` if it is not a literal choice."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        body, orelse = _constant_strings(node.body), _constant_strings(node.orelse)
        return None if body is None or orelse is None else body | orelse
    return None


def _source_formats_of(module_name: str) -> set[str]:
    """Every ``source_format=`` literal passed anywhere in a reader's module."""
    tree = ast.parse(inspect.getsource(sys.modules[module_name]))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "source_format":
            values = _constant_strings(node.value)
            assert values is not None, (
                f"{module_name}: source_format is not a string literal; teach "
                "test_choices_parity._constant_strings about the new shape"
            )
            found |= values
    return found


def test_source_formats_match_the_builtin_readers() -> None:
    from uadas_core.readers.reader_registry import _BUILTIN_READERS

    assert _BUILTIN_READERS, "no built-in readers found"
    per_reader = {
        r.__name__: _source_formats_of(r.__module__) for r in _BUILTIN_READERS
    }

    without = {name for name, formats in per_reader.items() if not formats}
    assert without == READERS_WITHOUT_OWN_FORMAT, (
        f"readers with no source_format literal: {sorted(without)}; expected exactly "
        f"{sorted(READERS_WITHOUT_OWN_FORMAT)}"
    )
    core_formats = set().union(*per_reader.values())
    assert core_formats, "extracted no source formats from the readers"
    assert core_formats == set(SourceFormat.values)


def test_chart_types_match_the_chart_registry() -> None:
    from uadas_core.visualization import chart_registry

    chart_registry._register_builtins()  # idempotent; the registry is empty until bootstrap
    core_charts = set(chart_registry.list_charts())
    assert core_charts, "the chart registry is empty"
    assert core_charts == set(ChartType.values)


def test_report_formats_match_the_report_service() -> None:
    from uadas_core.services.report_service import available_formats

    core_formats = set(available_formats())
    assert core_formats, "the report service offers no formats"
    assert core_formats == set(ReportFormat.values)


def _core_graph_element_names(suffix: str) -> set[str]:
    from uadas_core.provenance import dag

    classes = [
        cls
        for _, cls in inspect.getmembers(dag, inspect.isclass)
        if cls.__module__ == dag.__name__
        and dataclasses.is_dataclass(cls)
        and cls.__name__.endswith(suffix)
    ]
    return {cls.__name__.removesuffix(suffix).lower() for cls in classes}


def test_node_kinds_match_the_core_graph_node_classes() -> None:
    # The core has no kind enum: a node's kind is which dataclass it is
    # (DatasetNode, ArtifactNode, ...), so the kind names are derived from the classes.
    core_kinds = _core_graph_element_names("Node")
    assert core_kinds, "found no *Node dataclass in uadas_core.provenance.dag"
    assert core_kinds == set(NodeKind.values)


def test_edge_kinds_match_the_core_graph_edge_classes() -> None:
    core_kinds = _core_graph_element_names("Edge")
    assert core_kinds, "found no *Edge dataclass in uadas_core.provenance.dag"
    assert core_kinds == set(EdgeKind.values)


# ------------------------------------------------ models never import the core


def _files_that_must_not_import_the_core() -> list[Path]:
    root = Path(uadas_api.__file__).parent
    files = [root / "tenancy.py"]
    for app in ("accounts", "workspaces", "pipeline", "ai", "exports"):
        for name in ("models.py", "choices.py"):
            candidate = root / app / name
            if candidate.exists():
                files.append(candidate)
        files.extend((root / app / "migrations").glob("*.py"))
    return files


def test_there_are_files_to_check() -> None:
    names = {p.name for p in _files_that_must_not_import_the_core()}
    assert {"tenancy.py", "models.py", "choices.py", "0001_initial.py"} <= names


@pytest.mark.parametrize(
    "path",
    _files_that_must_not_import_the_core(),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_models_choices_tenancy_and_migrations_do_not_import_the_core(
    path: Path,
) -> None:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        assert not any(
            n == "uadas_core" or n.startswith("uadas_core.") for n in names
        ), f"{path.name} imports the core; only these parity tests may"

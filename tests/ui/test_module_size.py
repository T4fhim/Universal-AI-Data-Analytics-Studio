# File: tests/ui/test_module_size.py
"""Enforces the plan's R1 mitigation: no src/ui/ module may exceed 400 lines.

main_window.py reached 942 lines before this overhaul specifically because
nothing stopped it from growing. This test is blunt on purpose -- the plan's
own risk analysis calls it that -- but a hard ceiling is what actually
prevents "one more handler" additions from silently recreating the same
problem in a different file (workbench.py, a controller, a stage page).

400 lines excludes docstrings and blank lines, so a well-documented module is
not penalised for the documentation this project's own conventions require.
main_window.py was exempted until milestone 19 (MainWindow decomposition)
actually shrank it (942 -> 238 non-docstring lines, by moving every
project/dataset/visualization/report/assistant handler into
src/ui/controllers/) -- the exemption is removed now that the real fix has
landed, per _LEGACY_EXEMPTIONS' own docstring below.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.core.constants import PROJECT_ROOT

_MAX_LINES = 400

# Modules that predate this limit and are explicitly scheduled to shrink in a
# later milestone rather than being padded out today just to pass this test.
# main_window.py was removed from this set in milestone 19, once its own
# decomposition actually shrank it below the budget.
_LEGACY_EXEMPTIONS = {"src/ui/dialogs/settings_dialog.py"}


def _non_docstring_line_count(path: Path) -> int:
    """Count lines that are not blank and not part of a module/class/function docstring."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    docstring_lines: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            docstring_node = ast.get_docstring(node, clean=False)
            if docstring_node is not None and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr):
                    docstring_lines.update(
                        range(first.lineno, (first.end_lineno or first.lineno) + 1)
                    )

    lines = source.splitlines()
    return sum(
        1
        for index, line in enumerate(lines, start=1)
        if line.strip() and index not in docstring_lines
    )


def _ui_modules() -> list[Path]:
    ui_root = PROJECT_ROOT / "src" / "ui"
    return sorted(path for path in ui_root.rglob("*.py") if path.name != "__init__.py")


@pytest.mark.parametrize(
    "path", _ui_modules(), ids=lambda p: str(p.relative_to(PROJECT_ROOT))
)
def test_ui_module_stays_under_the_line_budget(path: Path) -> None:
    relative = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    if relative in _LEGACY_EXEMPTIONS:
        pytest.skip(
            f"{relative} is exempted pending its scheduled decomposition milestone"
        )
    count = _non_docstring_line_count(path)
    assert count <= _MAX_LINES, (
        f"{relative} has {count} non-docstring lines (budget {_MAX_LINES}). "
        f"Split it rather than raising the budget."
    )

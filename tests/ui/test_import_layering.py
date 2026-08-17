# File: tests/ui/test_import_layering.py
"""Enforces the plan's R5 mitigation: src/ui/ imports downward only.

Parses every module with ``ast`` rather than importing it, specifically so
this test can run before any Qt-dependent module is constructed and so it
inspects the *source* import graph rather than whatever happened to already
be cached in sys.modules by import order.

Two rules, both graph-shape rules rather than opinions about style:

1. Nothing **outside** src/ui/ may import src.ui -- the dependency direction
   documented in docs/ARCHITECTURE.md ("ui is the only package that depends
   on nearly everything else... nothing in core/services/readers/cleaning/
   analysis/forecasting/visualization imports from ui").
2. Within src/ui/, src/ui/theme/, src/ui/a11y/, and src/ui/ui_state_bus.py
   (once it exists) must import nothing from src.ui itself -- these are the
   foundation layer every other UI module is allowed to depend on, and a
   foundation that depends back on what it supports is not a foundation.

As later milestones add src/ui/actions/, controllers/, workbench/, and
results/, this file's _LEAF_PACKAGES and the widgets-never-import-controllers
rule should grow with them rather than being deferred to milestone 27.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.core.constants import PROJECT_ROOT

_SRC_ROOT = PROJECT_ROOT / "src"

# Packages/modules within src/ui/ that must import nothing from src.ui
# EXCEPT each other -- the foundation layer. Paths are relative to src/ui/.
# a11y legitimately depends on theme (contrast_manifest.py references
# ContrastRequirement/AA_BODY_TEXT from theme.contrast); that is a DAG edge
# within the foundation, not a violation of it, so long as theme never
# imports a11y back. Milestone 17 adds actions/ to this set for the same
# reason: action_binder.py depends on theme.icon_provider (another
# leaf-to-leaf edge), and action_registry.py/action_context.py import
# nothing from src.ui at all. What this rule actually forbids is a leaf
# depending on a *non-leaf* UI module (workbench/, controllers/, ...),
# which would make it not a foundation at all.
_LEAF_PACKAGES = ("theme", "a11y", "actions")

# src/core/app.py is the application's composition root -- the one place
# documented in docs/ARCHITECTURE.md that constructs QApplication, MainWindow,
# and ThemeManager and wires them together. It importing src.ui is the whole
# point of it, not a layering violation.
_COMPOSITION_ROOTS = ("src/core/app.py",)


def _module_dotted_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    return ".".join(relative.parts)


def _imported_modules(path: Path) -> set[str]:
    """Return every dotted module name this file imports, resolved absolutely."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    package_parts = _module_dotted_name(path).split(".")[:-1]  # this file's own package

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    imported.add(node.module)
            else:
                # Relative import: resolve against this file's package.
                base = (
                    package_parts[: len(package_parts) - (node.level - 1)]
                    if node.level > 1
                    else package_parts
                )
                prefix = ".".join(base)
                imported.add(f"{prefix}.{node.module}" if node.module else prefix)
    return imported


def _all_src_modules() -> list[Path]:
    return sorted(_SRC_ROOT.rglob("*.py"))


def _all_ui_modules() -> list[Path]:
    return sorted((_SRC_ROOT / "ui").rglob("*.py"))


@pytest.mark.parametrize(
    "path", _all_src_modules(), ids=lambda p: str(p.relative_to(PROJECT_ROOT))
)
def test_nothing_outside_ui_imports_ui(path: Path) -> None:
    relative = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    if "src/ui" in relative:
        pytest.skip("this test only checks modules outside src/ui")
    if relative in _COMPOSITION_ROOTS:
        pytest.skip(f"{relative} is a documented composition root")
    offenders = {
        name
        for name in _imported_modules(path)
        if name == "src.ui" or name.startswith("src.ui.")
    }
    assert not offenders, (
        f"{path.relative_to(PROJECT_ROOT)} imports from src.ui ({offenders}), "
        f"violating the one-way ui-depends-on-everything-else direction."
    )


@pytest.mark.parametrize("package", _LEAF_PACKAGES, ids=lambda p: f"src.ui.{p}")
def test_leaf_ui_package_imports_nothing_from_ui(package: str) -> None:
    package_root = _SRC_ROOT / "ui" / package
    offenders: dict[str, set[str]] = {}
    for path in sorted(package_root.rglob("*.py")):
        bad = {
            name
            for name in _imported_modules(path)
            if (name == "src.ui" or name.startswith("src.ui."))
            and not any(name.startswith(f"src.ui.{leaf}") for leaf in _LEAF_PACKAGES)
        }
        if bad:
            offenders[str(path.relative_to(PROJECT_ROOT))] = bad
    assert not offenders, (
        f"src/ui/{package}/ must import nothing else from src.ui (it is a "
        f"foundation layer other UI modules depend on): {offenders}"
    )


def test_theme_manager_does_not_import_the_rest_of_ui() -> None:
    """theme_manager.py sits alongside the theme/ and a11y/ leaf packages
    conceptually (every other UI module may depend on it), so it is held to
    the same rule even though it is a single file, not a package.
    """
    path = _SRC_ROOT / "ui" / "theme_manager.py"
    offenders = {
        name
        for name in _imported_modules(path)
        if (name == "src.ui" or name.startswith("src.ui."))
        and not name.startswith("src.ui.theme")
    }
    assert not offenders, f"theme_manager.py imports from src.ui: {offenders}"


def test_ui_state_bus_does_not_import_the_rest_of_ui() -> None:
    """ui_state_bus.py is the third single-file foundation module (alongside
    theme_manager.py), anticipated by name in this file's own original
    docstring before it existed. Every other UI module may depend on it
    (see its own module docstring for why menu_bar.py/main_window.py call
    ``request_refresh()``), so it must depend on nothing in src.ui itself.
    """
    path = _SRC_ROOT / "ui" / "ui_state_bus.py"
    offenders = {
        name
        for name in _imported_modules(path)
        if name == "src.ui" or name.startswith("src.ui.")
    }
    assert not offenders, f"ui_state_bus.py imports from src.ui: {offenders}"


def test_every_ui_module_parses_and_resolves_its_own_dotted_name() -> None:
    """A guard against the helper functions above silently no-op'ing on a
    syntax error or an empty file list -- if src/ui/ has no .py files at all,
    every other test in this module passes vacuously.
    """
    modules = _all_ui_modules()
    assert (
        len(modules) > 5
    ), "src/ui/ appears empty; the layering tests would pass vacuously"
    for path in modules:
        ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path)
        )  # raises on syntax error

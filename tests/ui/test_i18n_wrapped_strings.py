# File: tests/ui/test_i18n_wrapped_strings.py
"""Enforces milestone 27's i18n-scaffolding criterion: no un-wrapped literal user-facing text.

Scope, deliberately narrow and named exactly as the milestone's own acceptance criterion states
it: a bare string literal passed to ``QLabel(...)``, ``<widget>.setText(...)``, or
``<widget>.setWindowTitle(...)`` anywhere under ``src/ui/``. This is the smallest concrete,
mechanically-checkable slice of "every user-visible string is translatable" -- it does not (and,
per this milestone's own scope, is not meant to) catch every user-facing string in the codebase
(``QPushButton`` labels, ``QMessageBox`` titles/bodies, tooltips, status-bar messages, menu/action
text are all real user-facing strings this test does not scan). Widening it to every widget
constructor/string-setter across the UI layer was judged a materially larger sweep than this
milestone's "M" size budget -- see ``plans/ui-overhaul-pioneering-adaptive-workbench.md``'s M27
entry for the honest accounting of what was and was not covered.

At the time this test was written, a real full-repo AST sweep against exactly this narrow scope
found only 9 violations across 8 files -- small enough that every one was fixed directly (wrapped
in ``self.tr(...)``, or ``QCoreApplication.translate(...)`` for the one call site,
``DockManager``, that is not itself a ``QObject`` subclass) rather than deferred to an allowlist.
``_LEGACY_EXEMPTIONS`` below is consequently empty today -- kept, not deleted, as the place a
future violation gets a dated, named exemption if fixing it immediately is ever not practical,
matching ``tests/ui/test_module_size.py``'s own ``_LEGACY_EXEMPTIONS`` precedent (a documented
escape hatch, not a blanket one).

Uses ``ast``, not import + inspection, for the same reason ``test_module_size.py`` and
``test_import_layering.py`` already do: it runs without constructing any Qt object (source-level
static analysis), and inspects what the file actually says rather than whatever happened to
already be cached in ``sys.modules``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.core.constants import PROJECT_ROOT

# Call names this test inspects arguments of. A bare method/function name, not a dotted path --
# Qt call sites read as `widget.setText(...)`/`QLabel(...)`/`self.setWindowTitle(...)`, and this
# test does not attempt full name resolution (the same "check the call shape, not the type"
# trade-off test_import_layering.py's own _imported_modules makes for import statements).
_SCANNED_CALL_NAMES = frozenset({"QLabel", "setText", "setWindowTitle"})

# Call names that mark an argument as already translatable -- an argument nested inside one of
# these calls is not a bare literal even though ast.walk would otherwise find the ast.Constant
# node beneath it. Kept as a set of the *inner* call's own name (`tr`, `translate`) rather than
# trying to match `self.tr(...)` as one dotted path, for the same "check the call shape" reason
# _SCANNED_CALL_NAMES is name-only.
_TRANSLATION_CALL_NAMES = frozenset({"tr", "translate"})

# See this module's own docstring: empty today, a real sweep fixed every violation found rather
# than deferring any of them. A future entry must be a "path": "YYYY-MM-DD milestone NN: reason"
# mapping, not a bare path, so an exemption records *why* and *when* -- the same shape this
# project's CLAUDE.md instructs for a "documented, dated allowlist (not a blanket exemption)".
_LEGACY_EXEMPTIONS: dict[str, str] = {}


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_translation_wrapped(arg: ast.expr) -> bool:
    """``True`` if ``arg`` is itself a call to ``.tr(...)``/``QCoreApplication.translate(...)``.

    Only the direct wrapping shape is recognised (``self.tr("x")``, ``self.tr("x").format(y)``'s
    outer ``.format`` call would need its own recursive unwrap -- not needed by anything this
    sweep actually found, so not built speculatively). A ``.format(...)`` call *around* a
    translation call, e.g. ``self.tr("{0} illustration").format(heading)`` (see
    ``src/ui/widgets/empty_state.py``), is handled by :func:`_string_literal_violations` checking
    ``arg.func.value`` when ``arg`` is itself a ``.format`` call -- see there.
    """
    if not isinstance(arg, ast.Call):
        return False
    name = _call_name(arg)
    return name in _TRANSLATION_CALL_NAMES


def _string_literal_violations(path: Path) -> list[tuple[int, str, str]]:
    """Return ``(lineno, call_name, literal)`` for every un-wrapped literal ``path`` contains."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in _SCANNED_CALL_NAMES:
            continue

        for arg in node.args:
            candidate = arg
            # self.tr("...").format(...) -- unwrap one .format() layer to reach the translation
            # call underneath, matching this module's own EmptyState/ErrorState illustration
            # description pattern (see this file's docstring on _is_translation_wrapped).
            if (
                isinstance(candidate, ast.Call)
                and isinstance(candidate.func, ast.Attribute)
                and candidate.func.attr == "format"
            ):
                candidate = candidate.func.value

            if _is_translation_wrapped(candidate):
                continue
            if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                if candidate.value.strip():
                    violations.append((node.lineno, name, candidate.value))

    return violations


def _ui_modules() -> list[Path]:
    ui_root = PROJECT_ROOT / "src" / "ui"
    return sorted(path for path in ui_root.rglob("*.py") if path.name != "__init__.py")


@pytest.mark.parametrize(
    "path", _ui_modules(), ids=lambda p: str(p.relative_to(PROJECT_ROOT))
)
def test_no_unwrapped_string_literals_in_label_or_title_calls(path: Path) -> None:
    relative = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    if relative in _LEGACY_EXEMPTIONS:
        pytest.skip(f"{relative} is exempted: {_LEGACY_EXEMPTIONS[relative]}")

    violations = _string_literal_violations(path)
    assert not violations, (
        f"{relative} passes an un-wrapped string literal to QLabel/setText/setWindowTitle: "
        f"{violations}. Wrap it in self.tr(...) (or QCoreApplication.translate(...) for a "
        f"non-QObject class -- see src/ui/dock_manager.py for the existing pattern)."
    )


def test_the_sweep_itself_is_not_vacuous() -> None:
    """Guards against _ui_modules() silently no-op'ing, the same concern
    test_import_layering.py's own vacuity guard exists for.
    """
    modules = _ui_modules()
    assert len(modules) > 5, "src/ui/ appears empty; this sweep would pass vacuously"


def _violations_in_source(source: str) -> list[tuple[int, str, str]]:
    """Same detection logic as :func:`_string_literal_violations`, against in-memory source --
    used only by the two self-tests below, which must prove the detector actually detects
    something rather than merely finding the real codebase already clean.
    """
    tree = ast.parse(source)
    violations: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in _SCANNED_CALL_NAMES:
            continue
        for arg in node.args:
            candidate = arg
            if (
                isinstance(candidate, ast.Call)
                and isinstance(candidate.func, ast.Attribute)
                and candidate.func.attr == "format"
            ):
                candidate = candidate.func.value
            if _is_translation_wrapped(candidate):
                continue
            if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
                if candidate.value.strip():
                    violations.append((node.lineno, name, candidate.value))
    return violations


def test_the_detector_actually_flags_an_unwrapped_literal() -> None:
    """A detector that never fires is indistinguishable from a passing suite -- this proves it
    fires on the exact shape it exists to catch.
    """
    violations = _violations_in_source('QLabel("Hello")\n')
    assert violations == [(1, "QLabel", "Hello")]


def test_the_detector_accepts_tr_wrapped_and_translate_wrapped_literals() -> None:
    """The two real wrapping shapes this sweep found in the codebase (self.tr(...) everywhere,
    QCoreApplication.translate(...) in the one non-QObject caller, DockManager) must both read
    as clean -- otherwise fixing every real violation the way this milestone did would have left
    the suite red regardless.
    """
    assert _violations_in_source('QLabel(self.tr("Hello"))\n') == []
    assert (
        _violations_in_source('QLabel(QCoreApplication.translate("Ctx", "Hello"))\n')
        == []
    )
    # The self.tr("{0} x").format(heading) shape src/ui/widgets/empty_state.py itself uses.
    assert _violations_in_source('QLabel(self.tr("{0} x").format(heading))\n') == []

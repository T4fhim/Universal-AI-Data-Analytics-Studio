# File: scripts/codemod_lift_result_renderers.py
"""Phase 1.5: lift the Qt-free result renderers from src/ui/results/ to
uadas_core/results/. Runs from the scratchpad. Final form copied to scripts/.

MOVE  -> uadas_core/results/ :  base_result_renderer.py  result_view.py
                                result_renderer_registry.py  renderers/  (+ new __init__.py)
STAY  in src/ui/results/     :  __init__.py  result_card.py  explanation_panel.py  (Qt)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

MOVE = ("base_result_renderer", "result_view", "result_renderer_registry", "renderers")
_ALT = "|".join(MOVE)
RE_DOT = re.compile(rf"\bsrc\.ui\.results\.(?P<x>{_ALT})\b")
RE_SLASH = re.compile(rf"\bsrc/ui/results/(?P<x>{_ALT})\b")
RE_FROM_IMPORT = re.compile(rf"from src\.ui\.results import (?P<x>{_ALT})\b")
ROOTS = ("uadas_core", "src", "tests", "scripts")


def sh(*a, check=True):
    return subprocess.run(a, cwd=REPO, check=check, capture_output=True, text=True)


def git_mv(s, d):
    sp, dp = REPO / s, REPO / d
    if not sp.exists() or dp.exists():
        return False
    dp.parent.mkdir(parents=True, exist_ok=True)
    sh("git", "mv", s, d)
    print(f"  git mv {s} -> {d}")
    return True


def moves():
    print("[1/3] git mv")
    for f in (
        "base_result_renderer.py",
        "result_view.py",
        "result_renderer_registry.py",
    ):
        git_mv(f"src/ui/results/{f}", f"uadas_core/results/{f}")
    git_mv("src/ui/results/renderers", "uadas_core/results/renderers")
    ri = REPO / "uadas_core" / "results" / "__init__.py"
    if not ri.exists():
        ri.write_text(
            "# File: uadas_core/results/__init__.py\n"
            '"""Qt-free result rendering: analysis/forecast result dataclasses -> a list of\n'
            "plain ``ResultSection`` dataclasses (see ``base_result_renderer``), testable with\n"
            "zero QApplication. Lifted out of ``src/ui/results/`` in web-transition Phase 1.5;\n"
            "the Qt display layer (``src/ui/results/result_card.py`` /\n"
            "``explanation_panel.py``) still lives in the desktop shell and consumes this.\n"
            '"""\n\nfrom __future__ import annotations\n',
            encoding="utf-8",
        )
        sh("git", "add", "uadas_core/results/__init__.py")
        print("  create uadas_core/results/__init__.py")


def rewrites():
    print("[2/3] rewrites")
    n = 0
    for r in ROOTS:
        base = REPO / r
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            o = p.read_text(encoding="utf-8")
            w = RE_FROM_IMPORT.sub(
                lambda m: f"from uadas_core.results import {m.group('x')}", o
            )
            w = RE_DOT.sub(lambda m: f"uadas_core.results.{m.group('x')}", w)
            w = RE_SLASH.sub(lambda m: f"uadas_core/results/{m.group('x')}", w)
            if w != o:
                p.write_text(w, encoding="utf-8")
                n += 1
                print(f"  rewrote {p.relative_to(REPO).as_posix()}")
    print(f"  {n} files rewritten")


def surgical():
    print("[3/3] ci.yml mypy list: add uadas_core/results")
    ci = REPO / ".github" / "workflows" / "ci.yml"
    t = ci.read_text(encoding="utf-8")
    if "uadas_core/results" not in t:
        t = t.replace(
            "run: python -m mypy uadas_core/core uadas_core/services uadas_core/analysis uadas_core/database",
            "run: python -m mypy uadas_core/core uadas_core/services uadas_core/analysis uadas_core/database uadas_core/results",
        )
        ci.write_text(t, encoding="utf-8")
        print("  added")
    else:
        print("  already present")
    for p in (REPO / "uadas_core" / "results").rglob("*.py"):
        rel = p.relative_to(REPO).as_posix()
        lines = p.read_text(encoding="utf-8").splitlines()
        if (
            lines
            and lines[0].startswith("# File:")
            and lines[0].strip() != f"# File: {rel}"
        ):
            lines[0] = f"# File: {rel}"
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"  header: {rel}")


if __name__ == "__main__":
    moves()
    rewrites()
    surgical()
    left = subprocess.run(
        ["git", "grep", "-nE", rf"src\.ui\.results\.({_ALT})\b", "--", "*.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout
    print("residual src.ui.results.<moved>:", left.strip() or "NONE")
    print("\nDONE.")

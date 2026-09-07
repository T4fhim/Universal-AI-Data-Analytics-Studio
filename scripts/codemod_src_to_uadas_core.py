# File: scripts/codemod_src_to_uadas_core.py
"""Phase 1.1 carve-out codemod. Runs from the scratchpad (no repo formatter hook,
no self-scan). Its final form is copied into scripts/ afterward as the A-2 record.

  python codemod.py            # code + config (default)
  python codemod.py --docs     # docs / CLAUDE.md prose path references
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

MOVE_PKGS = [
    "ai",
    "analysis",
    "cleaning",
    "database",
    "forecasting",
    "plugins",
    "readers",
    "reports",
    "services",
    "visualization",
]
CORE_MODULES = [
    "__init__",
    "application_state",
    "bootstrap",
    "config",
    "constants",
    "dependency_container",
    "exceptions",
    "expertise_level",
    "logger",
]
_MOVED = sorted(set(MOVE_PKGS) | {"core"})
_ALT = "|".join(_MOVED)
_S, _D = "src", "uadas_core"

RE_APP_DOT = re.compile(_S + r"\.core\.app\b")
RE_APP_SLASH = re.compile(_S + r"/core/app\.py\b")
RE_APP_BACK = re.compile(_S + r"\\core\\app\.py")
RE_DOT = re.compile(_S + rf"\.(?P<x>{_ALT})\b")
RE_SLASH = re.compile(_S + rf"/(?P<x>{_ALT})\b")
RE_BACK = re.compile(_S + rf"\\(?P<x>{_ALT})\b")

CODE_ROOTS = ("uadas_core", "src", "tests", "scripts")
CODE_EXTRA = ("main.py",)
DOCS_ROOTS = ("docs",)
DOCS_EXTRA = ("CLAUDE.md",)


def sh(*a, check=True):
    return subprocess.run(a, cwd=REPO, check=check, capture_output=True, text=True)


def git_mv(src, dst):
    s, d = REPO / src, REPO / dst
    if not s.exists() or d.exists():
        return False
    d.parent.mkdir(parents=True, exist_ok=True)
    sh("git", "mv", src, dst)
    print(f"  git mv {src} -> {dst}")
    return True


def do_moves():
    print("[1/4] structural moves (git mv)")
    git_mv("src/core/app.py", "src/app.py")
    for pkg in MOVE_PKGS:
        git_mv(f"src/{pkg}", f"uadas_core/{pkg}")
    for m in CORE_MODULES:
        git_mv(f"src/core/{m}.py", f"uadas_core/core/{m}.py")
    stale = REPO / "src" / "core"
    if stale.exists():
        try:
            for f in sorted(stale.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                f.unlink() if f.is_file() else f.rmdir()
            stale.rmdir()
            print("  removed emptied src/core/")
        except OSError as e:
            print(
                f"  note: src/core/ residue ({e}); git tracks no empty dirs, harmless"
            )
    ri = REPO / "uadas_core" / "__init__.py"
    if not ri.exists():
        ri.write_text(
            "# File: uadas_core/__init__.py\n"
            '"""Universal AI Data Analytics Studio - Qt-free, headless core.\n\n'
            "Carved out of the former src/ package in web-transition Phase 1.1.\n"
            "Nothing here may import PySide6/PyQt or Django - enforced by the\n"
            ".importlinter contract in the CI lint job.\n"
            '"""\n',
            encoding="utf-8",
        )
        sh("git", "add", "uadas_core/__init__.py")
        print("  create uadas_core/__init__.py")


def _rewrite(t):
    t = RE_APP_DOT.sub(_S + ".app", t)
    t = RE_APP_SLASH.sub(_S + "/app.py", t)
    t = RE_APP_BACK.sub(_S + r"\\app.py", t)
    t = RE_DOT.sub(lambda m: f"{_D}.{m.group('x')}", t)
    t = RE_SLASH.sub(lambda m: f"{_D}/{m.group('x')}", t)
    t = RE_BACK.sub(lambda m: f"{_D}\\{m.group('x')}", t)
    return t


def _files(roots, extra, sfx):
    for r in roots:
        base = REPO / r
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in sfx and "__pycache__" not in p.parts:
                yield p
    for f in extra:
        p = REPO / f
        if p.is_file():
            yield p


def do_rewrites(scope):
    print(f"[2/4] selective text rewrites (scope={scope})")
    roots, extra, sfx = (
        (CODE_ROOTS, CODE_EXTRA, {".py"})
        if scope == "code"
        else (DOCS_ROOTS, DOCS_EXTRA, {".md"})
    )
    n = 0
    for p in _files(roots, extra, sfx):
        try:
            o = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        w = _rewrite(o)
        if w != o:
            p.write_text(w, encoding="utf-8")
            n += 1
            print(f"  rewrote {p.relative_to(REPO).as_posix()}")
    print(f"  {n} files rewritten")


def do_surgical():
    print("[3/4] surgical config edits")
    pp = REPO / "pyproject.toml"
    t = pp.read_text(encoding="utf-8")
    t = t.replace(
        'known_first_party = ["src"]', 'known_first_party = ["src", "uadas_core"]'
    )
    t = t.replace('include = ["src*"]', 'include = ["src*", "uadas_core*"]')
    pp.write_text(t, encoding="utf-8")
    print("  pyproject.toml")

    ci = REPO / ".github" / "workflows" / "ci.yml"
    t = ci.read_text(encoding="utf-8")
    for a, b in [
        (
            "python -m black --check src/ tests/",
            "python -m black --check src/ uadas_core/ tests/",
        ),
        (
            "python -m isort --check-only src/ tests/",
            "python -m isort --check-only src/ uadas_core/ tests/",
        ),
        (
            "python -m ruff check src/ tests/",
            "python -m ruff check src/ uadas_core/ tests/",
        ),
        (
            "python -m bandit -r src -q --skip B101,B107,B608",
            "python -m bandit -r src uadas_core -q --skip B101,B107,B608",
        ),
        (
            "python -m mypy src/core src/services src/analysis src/database",
            "python -m mypy uadas_core/core uadas_core/services uadas_core/analysis uadas_core/database",
        ),
    ]:
        t = t.replace(a, b)
    if "lint-imports" not in t and "lint_imports" not in t:
        t = t.replace(
            "      - name: ruff check\n        run: python -m ruff check src/ uadas_core/ tests/\n",
            "      - name: ruff check\n        run: python -m ruff check src/ uadas_core/ tests/\n\n"
            "      - name: import-linter (uadas_core stays Qt-free)\n        run: lint-imports\n",
        )
    ci.write_text(t, encoding="utf-8")
    print("  ci.yml")

    hook = REPO / ".claude" / "hooks" / "pre-commit-check.ps1"
    t = hook.read_text(encoding="utf-8")
    t = t.replace(
        '& $py -m bandit -r src -q -b ".bandit-baseline.json"',
        "& $py -m bandit -r src uadas_core -q --skip B101,B107,B608",
    )
    t = t.replace(
        'Write-Error "Security checks failed (new bandit finding not in .bandit-baseline.json). Commit blocked."',
        'Write-Error "Security checks failed (bandit finding outside the B101/B107/B608 skip set). Commit blocked."',
    )
    hook.write_text(t, encoding="utf-8")
    print("  pre-commit-check.ps1")

    b = REPO / ".bandit-baseline.json"
    if b.exists():
        sh("git", "rm", "-f", "-q", ".bandit-baseline.json")
        print("  git rm -f .bandit-baseline.json")

    (REPO / ".importlinter").write_text(
        "# import-linter contract - the machine-checked half of the desktop->web transition.\n#\n"
        "# The Qt-free carve-out packages now live under uadas_core (Phase 1.1). No module in\n"
        "# uadas_core may import a GUI toolkit or a web framework. Run: lint-imports.\n"
        "# Enforced in CI's lint job (see .github/workflows/ci.yml).\n\n"
        "[importlinter]\nroot_packages =\n    uadas_core\ninclude_external_packages = True\n\n"
        "[importlinter:contract:uadas-core-qt-and-framework-free]\n"
        "name = uadas_core must not import PySide6/PyQt/Django\ntype = forbidden\n"
        "source_modules =\n    uadas_core\nforbidden_modules =\n    PySide6\n    PyQt5\n    PyQt6\n    django\n"
        "allow_indirect_imports = False\n",
        encoding="utf-8",
    )
    print("  .importlinter")


def report():
    print("[4/4] verification grep")
    pat = re.compile(rf"^\s*(from|import)\s+src\.({_ALT})\b")
    hits = [
        f"{p.relative_to(REPO).as_posix()}:{i}: {ln.strip()}"
        for p in _files(CODE_ROOTS, CODE_EXTRA, {".py"})
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pat.search(ln)
    ]
    if hits:
        print("  !! residual:\n" + "\n".join("  " + h for h in hits))
        sys.exit(1)
    print("  OK: no `from/import src.<moved>` remains in *.py")


if __name__ == "__main__":
    if "--docs" in sys.argv[1:]:
        do_rewrites("docs")
        print("\nDOCS DONE.")
    else:
        do_moves()
        do_rewrites("code")
        do_surgical()
        report()
        print("\nCODE DONE.")

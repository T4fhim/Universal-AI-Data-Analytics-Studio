# File: apps/api/tests/test_sandbox_boundary.py
"""Readers run only in the sandbox child: proved statically and at runtime.

Why two proofs: ``.importlinter`` (contract ``readers-only-in-the-sandbox-child``) is a static
check of *direct* imports, and it deliberately allows the one indirect route the core's own
composition root brings (``core_bridge`` -> ``uadas_core.bootstrap`` -> services). A static
contract cannot show that the *parent side of the sandbox and the job machinery* never load a
parser, so here a **fresh interpreter** imports every parent-side module and the test asserts
that no parsing library -- and no ``uadas_core.readers`` -- is in ``sys.modules`` afterwards.
That is the property that matters: a web process or worker that has never imported a reader
cannot be exploited through one.

The contract's text is also exercised on a synthetic package tree (``tmp_path``) so that "the
contract can fail" is a standing, automated fact and not a one-off demonstration: the *real*
section is read from ``.importlinter`` and run against a tree where only the child, or someone
else, imports a reader or a reader library.
"""

from __future__ import annotations

import configparser
import json
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
IMPORTLINTER = REPO / ".importlinter"
CONTRACT = "importlinter:contract:readers-only-in-the-sandbox-child"
EnvBuilder = Callable[..., dict[str, str]]

PARSER_LIBRARIES = (
    "camelot",
    "fitz",
    "pymupdf",
    "pdfplumber",
    "docx",
    "openpyxl",
    "cv2",
    "pytesseract",
    "pptx",
    "odf",
    "pyxlsb",
    "lxml",
    "bs4",
)

# Every module of the parent side: the sandbox's parent half, the job machinery, ingest, the
# storage layer ingest uses. `core_bridge` is excluded on purpose: it is the core's composition
# root and reaches the readers through the core's own services (see the contract's comment).
PARENT_SIDE_MODULES = (
    "uadas_api.sandbox.admission",
    "uadas_api.sandbox.errors",
    "uadas_api.sandbox.limits",
    "uadas_api.sandbox.protocol",
    "uadas_api.sandbox.runner",
    "uadas_api.sandbox.isolation",
    "uadas_api.jobs.models",
    "uadas_api.jobs.services",
    "uadas_api.jobs.execution",
    "uadas_api.jobs.progress",
    "uadas_api.jobs.registry",
    "uadas_api.jobs.queue",
    "uadas_api.ingest.service",
    "uadas_api.storage.store",
    "uadas_api.storage.lifecycle",
    "uadas_api.workspaces.models",
)


def _run(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_importing_the_whole_parent_side_loads_no_reader_and_no_parsing_library(
    subprocess_env: EnvBuilder,
) -> None:
    env = subprocess_env(DJANGO_SETTINGS_MODULE="uadas_api.settings.test")
    result = _run(
        f"""
        import importlib, sys
        import django
        django.setup()
        for name in {PARENT_SIDE_MODULES!r}:
            importlib.import_module(name)
        loaded = sorted(
            m for m in sys.modules
            if m.split(".")[0] in {PARSER_LIBRARIES!r} or m.startswith("uadas_core.readers")
        )
        print("LOADED", loaded)
        """,
        env,
    )
    assert result.returncode == 0, result.stderr
    assert "LOADED []" in result.stdout, result.stdout


# Libraries that exist in the core ONLY to parse untrusted files: a process that has imported one
# of them has put a parser of attacker-controlled bytes in reach of its code paths.
PARSE_ONLY_LIBRARIES = (
    "camelot",
    "fitz",
    "pymupdf",
    "pdfplumber",
    "cv2",
    "pytesseract",
    "pptx",
    "odf",
    "pyxlsb",
    "bs4",
)
# Libraries the report *exporters* use to WRITE .xlsx / .docx files (and that python-docx and
# openpyxl pull lxml in for). They are loaded by ``uadas_core.reports`` -- writing -- not by any reader.
WRITER_LIBRARIES = ("openpyxl", "docx", "lxml")
EXPORTER_MODULES = (
    "uadas_core.reports.excel_exporter",
    "uadas_core.reports.word_exporter",
)
# The only modules of the readers package a process may hold without having imported a reader:
# the package itself and the type-inference helpers the analysis code shares.
ALLOWED_READER_MODULES = ("uadas_core.readers", "uadas_core.readers.type_inference")


def test_the_composition_root_builds_the_core_without_loading_any_reader(
    subprocess_env: EnvBuilder,
) -> None:
    # The import-linter contract is direct-only and ``core_bridge`` legitimately reaches the core's
    # bootstrap, so the static check cannot say what that chain loads. This does: build the
    # process context exactly as a web request would (server mode) and look at what is loaded.
    env = subprocess_env(DJANGO_SETTINGS_MODULE="uadas_api.settings.test")
    result = _run(
        f"""
        import json, sys
        import django
        django.setup()
        from uadas_api.core_bridge import get_process_context
        get_process_context()  # bootstrap_process(server_mode=True, ...)
        loaded = sorted(sys.modules)
        print("PROBE", json.dumps({{
            "reader_modules": [m for m in loaded if m.startswith("uadas_core.readers")],
            "parse_only": [m for m in loaded if m.split(".")[0] in {PARSE_ONLY_LIBRARIES!r}],
            "writers": sorted({{m.split(".")[0] for m in loaded if m.split(".")[0] in {WRITER_LIBRARIES!r}}}),
            "exporters": [m for m in loaded if m in {EXPORTER_MODULES!r}],
        }}))
        """,
        env,
    )
    assert result.returncode == 0, result.stderr
    probe = json.loads(result.stdout.split("PROBE ", 1)[1])
    assert set(probe["reader_modules"]) <= set(ALLOWED_READER_MODULES), probe
    assert probe["parse_only"] == [], probe
    # openpyxl / python-docx / lxml may be present only because an exporter (a writer) is loaded.
    assert not probe["writers"] or probe["exporters"], probe


def test_the_probe_above_would_see_a_reader_if_one_were_loaded(
    subprocess_env: EnvBuilder,
) -> None:
    # Positive twin: after the context is built, importing the reader registry makes the same
    # measurements light up (readers, and the parse-only libraries behind them).
    env = subprocess_env(DJANGO_SETTINGS_MODULE="uadas_api.settings.test")
    result = _run(
        f"""
        import json, sys
        import django
        django.setup()
        from uadas_api.core_bridge import get_process_context
        get_process_context()
        import uadas_core.readers.reader_registry  # noqa: F401
        loaded = sorted(sys.modules)
        print("PROBE", json.dumps({{
            "reader_modules": [m for m in loaded if m.startswith("uadas_core.readers.") and m not in {ALLOWED_READER_MODULES!r}],
            "parse_only": [m for m in loaded if m.split(".")[0] in {PARSE_ONLY_LIBRARIES!r}],
        }}))
        """,
        env,
    )
    assert result.returncode == 0, result.stderr
    probe = json.loads(result.stdout.split("PROBE ", 1)[1])
    assert "uadas_core.readers.reader_registry" in probe["reader_modules"], probe
    assert probe["parse_only"], probe


def test_the_sandbox_child_is_where_readers_do_load() -> None:
    # Positive twin of the test above: the same probe *does* see readers when the child's code
    # path is taken, so an always-empty result cannot be a broken probe.
    code = """
        import sys
        from uadas_core.readers.reader_registry import get_reader_for_path
        print("LOADED", "uadas_core.readers" in sys.modules or any(m.startswith("uadas_core.readers") for m in sys.modules))
    """
    result = subprocess.run(
        [sys.executable, "-I", "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "LOADED True" in result.stdout


def test_the_child_imports_no_django_and_no_celery() -> None:
    code = """
        import sys
        import uadas_api.sandbox.child  # noqa: F401  (imports guards / protocol only)
        print("DJANGO", "django" in sys.modules, "CELERY", "celery" in sys.modules)
    """
    result = subprocess.run(
        [sys.executable, "-I", "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "DJANGO False CELERY False" in result.stdout


# ------------------------------------------------------- the contract, run for real


def _contract_config(root_packages: str = "uadas_core\n    uadas_api") -> str:
    parser = configparser.RawConfigParser()
    parser.read(IMPORTLINTER, encoding="utf-8")
    section = parser[CONTRACT]
    lines = [
        "[importlinter]",
        f"root_packages =\n    {root_packages}",
        "include_external_packages = True",
        "",
        f"[{CONTRACT}]",
    ]
    for key, value in section.items():
        parts = [line.strip() for line in value.strip().splitlines()]
        # A one-line value stays on the line (`type = forbidden`); a list goes below the key.
        lines.append(
            f"{key} = {parts[0]}"
            if len(parts) == 1
            else f"{key} =\n    " + "\n    ".join(parts)
        )
    return "\n".join(lines) + "\n"


def _build_tree(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")


def _lint(root: Path) -> subprocess.CompletedProcess[str]:
    (root / ".importlinter").write_text(_contract_config(), encoding="utf-8")
    runner = "import sys; from importlinter.cli import lint_imports_command as main; sys.exit(main())"
    return subprocess.run(
        [sys.executable, "-c", runner, "--config", str(root / ".importlinter")],
        cwd=root,
        env={"PYTHONPATH": str(root), "PATH": "", "SYSTEMROOT": "C:\\Windows"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


BASE_TREE = {
    "uadas_core/__init__.py": "",
    "uadas_core/readers/__init__.py": "",
    "uadas_core/readers/reader_registry.py": "def get_reader_for_path(p): ...\n",
    "uadas_api/__init__.py": "",
    "uadas_api/sandbox/__init__.py": "",
    "uadas_api/jobs/__init__.py": "",
}


def test_the_contract_passes_when_only_the_sandbox_child_imports_a_reader(
    tmp_path: Path,
) -> None:
    _build_tree(
        tmp_path,
        {
            **BASE_TREE,
            "uadas_api/sandbox/child.py": """
                from uadas_core.readers.reader_registry import get_reader_for_path
                import json
            """,
            "uadas_api/jobs/ok.py": "import json\n",
        },
    )
    result = _lint(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KEPT" in result.stdout


@pytest.mark.parametrize(
    ("offender", "source", "mentions"),
    [
        (
            "uadas_api/jobs/bad_reader.py",
            "from uadas_core.readers.reader_registry import get_reader_for_path\n",
            "uadas_core.readers",
        ),
        ("uadas_api/jobs/bad_lib.py", "import openpyxl\n", "openpyxl"),
        ("uadas_api/jobs/bad_pdf.py", "import fitz\n", "fitz"),
        # the contract is stricter than it has to be: even the child goes through the core's
        # readers, never a parsing library of its own
        (
            "uadas_api/sandbox/child.py",
            "from uadas_core.readers.reader_registry import get_reader_for_path\nimport openpyxl\n",
            "openpyxl",
        ),
        ("uadas_api/sandbox/runner.py", "from lxml import etree\n", "lxml"),
        # a sibling of the child is not the child
        (
            "uadas_api/sandbox/guards.py",
            "import uadas_core.readers.reader_registry\n",
            "uadas_core.readers",
        ),
    ],
    ids=[
        "reader-in-jobs",
        "openpyxl-in-jobs",
        "pymupdf-in-jobs",
        "library-in-the-child",
        "lxml-in-runner",
        "reader-in-guards",
    ],
)
def test_the_contract_fails_for_any_other_module_and_names_it(
    tmp_path: Path, offender: str, source: str, mentions: str
) -> None:
    _build_tree(
        tmp_path,
        {
            **BASE_TREE,
            "uadas_api/sandbox/child.py": "from uadas_core.readers.reader_registry import get_reader_for_path\n",
            offender: source,
        },
    )
    result = _lint(tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "BROKEN" in output
    module = offender[: -len(".py")].replace("/", ".")
    assert module in output and mentions in output

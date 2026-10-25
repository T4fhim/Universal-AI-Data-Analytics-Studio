# File: apps/api/tests/test_sql_capability_boundary.py
"""The raw-SQL capability is not exposed by the web API: proved by contract and by source scan.

Why this exists: ``uadas_core.database`` can run caller-supplied SQL against a database the user
names (``BaseDatabaseConnection.execute_query``, off unless ``allow_arbitrary_queries``). Phase 3.8
decided to build *nothing* user-facing for it -- doing it safely needs a read-only role, a statement
timeout and a manual security review (CI's bandit skips B608, so SQL construction has no automated
gate). The decision is only worth anything if it cannot be undone by an accident, so two independent
checks hold it:

* the ``.importlinter`` contract ``api-avoids-raw-sql-connectors`` -- a static check of *direct*
  imports. It is **run here against the real tree** (so a violation fails the test suite, not just
  CI's lint job) and against **synthetic trees** (so "the contract can fail" is a standing,
  automated fact, the same technique as ``test_sandbox_boundary.py``);
* a source scan of ``uadas_api`` that sees what an import graph cannot: a dotted-path *string*
  handed to ``importlib.import_module`` and any use of the SQL entry points by name. Its positive
  twin runs the same scanner on snippets that contain each forbidden form.

The contract is deliberately direct-only: ``uadas_api.core_bridge`` legitimately reaches the
connectors through the core's own bootstrap (``DatabaseConnectionService`` is a session service), so
a runtime ``sys.modules`` probe could not tell the API's imports from the core's and is not used.
"""

from __future__ import annotations

import ast
import configparser
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
API_PACKAGE = REPO / "apps" / "api" / "uadas_api"
IMPORTLINTER = REPO / ".importlinter"
CONTRACT = "importlinter:contract:api-avoids-raw-sql-connectors"

# Module paths the API must never name, import or hand to ``import_module``.
FORBIDDEN_MODULE = re.compile(
    r"uadas_core\.(database|services\.database_connection_service)(\.\w+)*"
)
# Names that are the SQL entry points themselves; none belongs in API code today.
FORBIDDEN_NAMES = frozenset(
    {"execute_query", "allow_arbitrary_queries", "DatabaseConnectionService"}
)


def violations(source: str) -> list[str]:
    """Return what in ``source`` reaches the raw-SQL capability (empty means clean)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if FORBIDDEN_MODULE.fullmatch(a.name)]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if FORBIDDEN_MODULE.fullmatch(module):
                found.append(module)
            # `from uadas_core import database` / `from uadas_core.services import ...`
            found += [
                f"{module}.{a.name}"
                for a in node.names
                if FORBIDDEN_MODULE.fullmatch(f"{module}.{a.name}")
            ]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # A *whole-string* module path (an import_module argument), not prose in a docstring.
            if FORBIDDEN_MODULE.fullmatch(node.value):
                found.append(node.value)
        elif isinstance(node, ast.alias) and node.name in FORBIDDEN_NAMES:
            found.append(node.name)  # `from anywhere import DatabaseConnectionService`
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found.append(node.attr)
        elif isinstance(node, ast.keyword) and node.arg in FORBIDDEN_NAMES:
            found.append(str(node.arg))
    return found


# ------------------------------------------------------------------ source scan


def test_no_api_module_reaches_the_raw_sql_capability() -> None:
    sources = sorted(API_PACKAGE.rglob("*.py"))
    assert len(sources) > 100  # the whole package was scanned (guards the guard)
    offenders = {
        str(path.relative_to(REPO)): found
        for path in sources
        if (found := violations(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


@pytest.mark.parametrize(
    "snippet",
    [
        "import uadas_core.database.base_connection",
        "from uadas_core.database.postgres_connection import PostgresConnection",
        "from uadas_core import database\nfrom uadas_core.database import x",
        "from uadas_core.services.database_connection_service import S",
        "import importlib\nimportlib.import_module('uadas_core.database.connection_registry')",
        "def f(c):\n    return c.execute_query('select 1')",
        "x = make(allow_arbitrary_queries=True)",
        "from somewhere import DatabaseConnectionService",
    ],
    ids=[
        "import",
        "from-import",
        "from-package-import-name",
        "service-module",
        "import_module-string",
        "execute_query-call",
        "capability-flag",
        "service-name",
    ],
)
def test_the_scan_detects_each_form_of_reaching_the_capability(snippet: str) -> None:
    assert violations(snippet)


def test_the_scan_ignores_prose_and_unrelated_code() -> None:
    clean = '''
        """Mentions uadas_core.database in prose, and a query in a docstring: not a use."""
        from uadas_core.services.workspace_service import WorkspaceService
        import uadas_core.database_adjacent_but_not_it  # a different module name
        '''
    assert violations(textwrap.dedent(clean)) == []


# ----------------------------------------------------------- the contract, run for real


def _contract_config() -> str:
    parser = configparser.RawConfigParser()
    parser.read(IMPORTLINTER, encoding="utf-8")
    lines = [
        "[importlinter]",
        "root_packages =\n    uadas_core\n    uadas_api",
        "include_external_packages = True",
        "",
        f"[{CONTRACT}]",
    ]
    for key, value in parser[CONTRACT].items():
        parts = [line.strip() for line in value.strip().splitlines()]
        lines.append(
            f"{key} = {parts[0]}"
            if len(parts) == 1
            else f"{key} =\n    " + "\n    ".join(parts)
        )
    return "\n".join(lines) + "\n"


def _lint(root: Path, config_dir: Path) -> subprocess.CompletedProcess[str]:
    config = config_dir / "sql_boundary.importlinter"
    config.write_text(_contract_config(), encoding="utf-8")
    runner = "import sys; from importlinter.cli import lint_imports_command as main; sys.exit(main())"
    paths = [str(root), str(root / "apps" / "api")]
    return subprocess.run(
        [sys.executable, "-c", runner, "--config", str(config)],
        cwd=root,
        env={
            "PYTHONPATH": (
                ";".join(paths) if sys.platform == "win32" else ":".join(paths)
            ),
            "PATH": "",
            "SYSTEMROOT": "C:\\Windows",
        },
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _build_tree(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")


BASE_TREE = {
    "uadas_core/__init__.py": "",
    "uadas_core/database/__init__.py": "",
    "uadas_core/database/base_connection.py": "class BaseDatabaseConnection: ...\n",
    "uadas_core/bootstrap.py": "import uadas_core.database.base_connection\n",
    "uadas_api/__init__.py": "",
    "uadas_api/web/__init__.py": "",
    "uadas_api/web/ok.py": "import json\n",
}


def test_the_contract_holds_for_the_real_tree(tmp_path: Path) -> None:
    result = _lint(REPO, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KEPT" in result.stdout


def test_the_contract_allows_a_transitive_route_through_the_core(
    tmp_path: Path,
) -> None:
    # The composition root reaches the connectors through the core's bootstrap; that is allowed.
    _build_tree(
        tmp_path,
        {
            **BASE_TREE,
            "uadas_api/core_bridge.py": "from uadas_core import bootstrap\n",
        },
    )
    result = _lint(tmp_path, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "KEPT" in result.stdout


@pytest.mark.parametrize(
    ("offender", "source"),
    [
        (
            "uadas_api/web/bad_from.py",
            "from uadas_core.database.base_connection import BaseDatabaseConnection\n",
        ),
        ("uadas_api/web/bad_import.py", "import uadas_core.database.base_connection\n"),
        ("uadas_api/jobs/bad_task.py", "from uadas_core import database\n"),
    ],
    ids=["from-import-in-web", "import-in-web", "package-import-in-jobs"],
)
def test_the_contract_fails_for_a_direct_import_and_names_the_module(
    tmp_path: Path, offender: str, source: str
) -> None:
    _build_tree(
        tmp_path,
        {**BASE_TREE, "uadas_api/jobs/__init__.py": "", offender: source},
    )
    result = _lint(tmp_path, tmp_path)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "BROKEN" in output
    assert offender[: -len(".py")].replace("/", ".") in output

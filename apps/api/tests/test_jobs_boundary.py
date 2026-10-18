# File: apps/api/tests/test_jobs_boundary.py
"""Celery is imported by three modules and no others.

Why: the queue is behind a facade (``uadas_api.jobs.queue``) so the courier can be swapped
(Django's ``django.tasks`` backends, RQ) without touching a call site. That only stays true if
nothing else imports ``celery`` or ``kombu`` -- so, like the storage boundary test, this scans the
package: a static check that cannot see dynamic imports, which is why it is paired with the
fresh-interpreter test in ``test_sandbox_boundary.py`` (importing services / execution loads no
Celery) and with the facade being the only code that names the broker's exception types.
"""

from __future__ import annotations

import ast
from pathlib import Path

API_PACKAGE = Path(__file__).resolve().parents[1] / "uadas_api"
ALLOWED = {
    "uadas_api/jobs/celery_app.py",
    "uadas_api/jobs/tasks.py",
    "uadas_api/jobs/queue.py",
}
COURIERS = ("celery", "kombu", "redis")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def _modules_importing(names: tuple[str, ...]) -> set[str]:
    return {
        path.relative_to(API_PACKAGE.parent).as_posix()
        for path in API_PACKAGE.rglob("*.py")
        if _imports(path) & set(names)
    }


def test_only_the_facade_modules_import_celery_or_kombu() -> None:
    importers = _modules_importing(("celery", "kombu"))
    assert (
        importers == ALLOWED
    ), f"unexpected: {sorted(importers - ALLOWED)}; missing: {sorted(ALLOWED - importers)}"


def test_redis_is_imported_by_nothing_in_the_api_package() -> None:
    # The cache backend is configured by name in settings; no module talks to Redis directly.
    assert _modules_importing(("redis",)) == set()


def test_the_scan_itself_sees_imports() -> None:
    # Positive twin: the scanner finds a module known to import something.
    assert "django" in _imports(API_PACKAGE / "jobs" / "models.py")


def test_the_child_module_imports_no_framework() -> None:
    imports = _imports(API_PACKAGE / "sandbox" / "child.py")
    assert not imports & {"django", "celery", "kombu"}

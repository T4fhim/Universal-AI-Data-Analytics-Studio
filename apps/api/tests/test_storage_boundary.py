# File: apps/api/tests/test_storage_boundary.py
"""Nothing but ``uadas_api.storage`` touches the bucket (3.4): a static, whole-source check.

Why: ``TenantObjectStore`` is only an isolation guarantee if it is the *only* way in. A view
that opens its own boto3 client, asks django-storages' ``default_storage`` for a path, or pulls
``storages["tenant_objects"]`` out of Django's registry (an alternate, overwrite-capable path
that skips the tenant prefix, the size cap and the integrity check) would bypass it without any
test noticing. This scans the source of ``uadas_api`` **and** ``uadas_core`` (a core module
reaching for the bucket would be worse) for:

* imports of ``boto3`` / ``botocore`` / ``s3transfer`` / ``storages``, in every spelling the AST
  shows -- ``import``, ``from ... import``, ``importlib.import_module("boto3")``,
  ``__import__("boto3")``;
* any use of the names ``default_storage`` or ``storages`` (name or attribute), and the string
  ``"tenant_objects"``;
* imports of the backend modules from outside ``uadas_api/storage/``.

It is a static scan, so it cannot see ``getattr(module, "stor" + "ages")`` or code loaded at
run time; it exists to make the *ordinary* mistake fail loudly, and the facade's own tests carry
the behavioural guarantees. The scanner itself is tested on synthetic snippets (each bypass is
flagged, each innocent snippet is not), so a broken walker cannot pass vacuously.

Allowed: ``storage/s3.py`` (the one SDK seam), ``storage/store.py`` (names the registry entry
once, to build the S3 backend) and ``settings/_storage.py`` (builds the ``STORAGES`` entry).
The ``tenant_objects`` registry entry stays reachable through ``django.core.files.storage`` --
Django offers no way to hide it -- which is why a name scan, not an API, is the guard.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "uadas_api"
REPO_ROOT = PACKAGE.parents[2]
CORE = REPO_ROOT / "uadas_core"
SDK_ROOTS = {"boto3", "botocore", "s3transfer", "storages"}
SDK_ALLOWED = {
    PACKAGE / "storage" / "s3.py",
    PACKAGE / "settings" / "_storage.py",
}
REGISTRY_ALLOWED = SDK_ALLOWED | {PACKAGE / "storage" / "store.py"}
BACKEND_MODULES = {
    "uadas_api.storage.s3",
    "uadas_api.storage.memory",
    "uadas_api.storage.backend",
}
FORBIDDEN_NAMES = {"default_storage", "storages"}
REGISTRY_ENTRY = "tenant_objects"


def _sdk_imports(source: str) -> list[str]:
    """Every storage-SDK module imported (or dynamically imported) in ``source``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
        elif isinstance(node, ast.Call):
            target = node.func
            called = (
                target.attr
                if isinstance(target, ast.Attribute)
                else target.id if isinstance(target, ast.Name) else ""
            )
            if called in {"import_module", "__import__"} and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    modules = [first.value]
        found += [m for m in modules if m.split(".")[0] in SDK_ROOTS]
    return found


def _registry_uses(source: str) -> list[str]:
    """Uses of ``default_storage`` / ``storages`` (name or attribute) or ``"tenant_objects"``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            found.append(node.attr)
        elif isinstance(node, ast.alias) and node.name in FORBIDDEN_NAMES:
            found.append(
                node.name
            )  # `from django.core.files.storage import default_storage`
        elif isinstance(node, ast.Constant) and node.value == REGISTRY_ENTRY:
            found.append(REGISTRY_ENTRY)
    return found


def _modules(root: Path) -> Iterator[Path]:
    yield from sorted(root.rglob("*.py"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- the scanner, on synthetic source -------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import boto3",
        "import botocore.config",
        "from boto3.s3.transfer import TransferConfig",
        "from storages.backends.s3 import S3Storage",
        "import importlib\nimportlib.import_module('boto3')",
        "from importlib import import_module\nimport_module('storages.backends.s3')",
        "__import__('botocore')",
    ],
)
def test_every_spelling_of_an_sdk_import_is_seen(source: str) -> None:
    assert _sdk_imports(source)


@pytest.mark.parametrize(
    "source",
    [
        "import os\nimport json",
        "from django.core.files import File",
        "import importlib\nimportlib.import_module('json')",
        "name = 'boto3'  # a string is not an import",
        "from uadas_api.storage.store import get_store",
    ],
)
def test_innocent_source_is_not_flagged_as_an_sdk_import(source: str) -> None:
    assert _sdk_imports(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "from django.core.files.storage import default_storage",
        "from django.core.files.storage import storages\nstorages['x']",
        "import django.core.files.storage as s\ns.storages['tenant_objects']",
        "x = {'k': 'tenant_objects'}",
        "def f(storage):\n    return storage.default_storage",
    ],
)
def test_every_way_of_reaching_the_registry_is_seen(source: str) -> None:
    assert _registry_uses(source)


@pytest.mark.parametrize(
    "source",
    [
        "storage = object()\nstorage.save('x')",
        "my_storages = []",
        "from x import store",
    ],
)
def test_innocent_source_is_not_flagged_as_a_registry_use(source: str) -> None:
    assert _registry_uses(source) == []


# --- the real source ------------------------------------------------------------------


def test_only_the_s3_backend_and_the_settings_builder_import_the_storage_sdks() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {module}"
        for root in (PACKAGE, CORE)
        for path in _modules(root)
        if path not in SDK_ALLOWED
        for module in _sdk_imports(_read(path))
    ]
    assert offenders == []


def test_the_scan_finds_the_sdk_import_where_it_is_allowed() -> None:
    """Positive control on the real tree: the one seam *is* detected."""
    assert _sdk_imports(_read(PACKAGE / "storage" / "s3.py"))
    assert _sdk_imports(_read(PACKAGE / "settings" / "_storage.py"))


def test_only_the_storage_package_imports_a_backend_module() -> None:
    storage_dir = PACKAGE / "storage"
    offenders: list[str] = []
    for path in _modules(PACKAGE):
        if storage_dir in path.parents:
            continue
        for node in ast.walk(ast.parse(_read(path))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            offenders += [
                f"{path.relative_to(PACKAGE.parent)}: {n}"
                for n in names
                if n in BACKEND_MODULES
            ]
    assert offenders == []


def test_nothing_reaches_for_the_storage_registry_outside_the_allowed_modules() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {use}"
        for root in (PACKAGE, CORE)
        for path in _modules(root)
        if path not in REGISTRY_ALLOWED
        for use in _registry_uses(_read(path))
    ]
    assert offenders == []


def test_the_registry_entry_is_named_only_where_the_s3_backend_is_built() -> None:
    """Positive control: the allowed modules do use the names the scan forbids elsewhere."""
    assert REGISTRY_ENTRY in _registry_uses(_read(PACKAGE / "storage" / "store.py"))
    assert REGISTRY_ENTRY in _registry_uses(_read(PACKAGE / "settings" / "_storage.py"))


@pytest.mark.parametrize(
    "module",
    [
        "uadas_api.storage.store",
        "uadas_api.storage.keys",
        "uadas_api.storage.workspace",
    ],
)
def test_the_public_modules_do_not_import_the_sdk_either(module: str) -> None:
    path = PACKAGE.parent / (module.replace(".", "/") + ".py")
    assert _sdk_imports(_read(path)) == []

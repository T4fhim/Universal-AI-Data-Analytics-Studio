# File: tests/plugins/test_plugin_loader.py
"""Tests for src.plugins.plugin_loader.discover_plugins.

Builds real plugin directories under pytest's tmp_path fixture (a
manifest plus an importable Python package) rather than mocking
importlib — the whole point of this module is genuine dynamic import
and Base* validation, so a test that mocked either would verify
nothing about whether discovery actually works end-to-end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cleaning.operation_registry import get_operation, unregister_operation
from src.core.exceptions import ServiceError
from src.plugins.plugin_loader import discover_plugins


def _make_plugin(
    tmp_path: Path,
    plugin_name: str,
    provides: dict[str, list[str]],
    module_files: dict[str, str],
) -> None:
    """Create a plugin directory: plugin.json + an importable package."""
    plugin_dir = tmp_path / plugin_name
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_name,
                "version": "1.0.0",
                "description": "test plugin",
                "provides": provides,
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    for filename, content in module_files.items():
        (plugin_dir / filename).write_text(content, encoding="utf-8")


_VALID_OPERATION_MODULE = """
from __future__ import annotations
from src.cleaning.base_operation import BaseOperation

class TestOperation(BaseOperation):
    @classmethod
    def apply(cls, dataset, **kwargs):
        raise NotImplementedError
"""

_WRONG_BASE_CLASS_MODULE = """
class NotAnOperation:
    pass
"""


@pytest.fixture(autouse=True)
def _cleanup_test_operation():
    yield
    unregister_operation("plugin_ok_testoperation")
    unregister_operation("plugin_wrongbase_notanoperation")


def test_discover_plugins_registers_valid_operation(tmp_path: Path) -> None:
    _make_plugin(
        tmp_path,
        "plugin_ok",
        {"cleaning_operations": ["plugin_ok.ops:TestOperation"]},
        {"ops.py": _VALID_OPERATION_MODULE},
    )

    results = discover_plugins([tmp_path])

    assert len(results) == 1
    assert results[0].loaded_successfully
    assert results[0].registered == {"cleaning_operations": ["plugin_ok_testoperation"]}
    assert get_operation("plugin_ok_testoperation").__name__ == "TestOperation"


def test_discover_plugins_records_error_for_wrong_base_class(tmp_path: Path) -> None:
    _make_plugin(
        tmp_path,
        "plugin_wrongbase",
        {"cleaning_operations": ["plugin_wrongbase.ops:NotAnOperation"]},
        {"ops.py": _WRONG_BASE_CLASS_MODULE},
    )

    results = discover_plugins([tmp_path])

    assert len(results) == 1
    assert not results[0].loaded_successfully
    assert "does not subclass BaseOperation" in results[0].errors[0]


def test_discover_plugins_records_error_for_missing_module(tmp_path: Path) -> None:
    _make_plugin(
        tmp_path,
        "plugin_badimport",
        {"cleaning_operations": ["plugin_badimport.does_not_exist:Foo"]},
        {},
    )

    results = discover_plugins([tmp_path])

    assert len(results) == 1
    assert not results[0].loaded_successfully
    assert "Could not import" in results[0].errors[0]


def test_discover_plugins_skips_names_in_skip_set(tmp_path: Path) -> None:
    _make_plugin(
        tmp_path,
        "plugin_ok",
        {"cleaning_operations": ["plugin_ok.ops:TestOperation"]},
        {"ops.py": _VALID_OPERATION_MODULE},
    )

    results = discover_plugins([tmp_path], skip_names={"plugin_ok"})

    # A disabled plugin still appears (so a settings panel can re-enable
    # it) but is never imported/registered — see LoadedPlugin's own
    # docstring for why zero side effects still means "not vanished".
    assert len(results) == 1
    assert results[0].manifest.name == "plugin_ok"
    assert results[0].registered == {}
    with pytest.raises(ServiceError, match="Unknown cleaning operation"):
        get_operation("plugin_ok_testoperation")


def test_discover_plugins_nonexistent_search_path_returns_empty(tmp_path: Path) -> None:
    results = discover_plugins([tmp_path / "does_not_exist"])
    assert results == []


def test_discover_plugins_directory_without_manifest_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "not_a_plugin").mkdir()
    results = discover_plugins([tmp_path])
    assert results == []


def test_discover_plugins_one_bad_plugin_does_not_block_others(tmp_path: Path) -> None:
    _make_plugin(
        tmp_path,
        "plugin_ok",
        {"cleaning_operations": ["plugin_ok.ops:TestOperation"]},
        {"ops.py": _VALID_OPERATION_MODULE},
    )
    (tmp_path / "plugin_malformed").mkdir()
    (tmp_path / "plugin_malformed" / "plugin.json").write_text(
        "{ not valid json", encoding="utf-8"
    )

    results = discover_plugins([tmp_path])

    names = {r.manifest.name for r in results}
    assert "plugin_ok" in names
    assert any(not r.loaded_successfully for r in results)

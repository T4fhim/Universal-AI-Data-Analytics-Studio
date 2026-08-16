# File: tests/plugins/test_plugin_manager.py
"""Tests for src.plugins.plugin_manager.PluginManager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cleaning.operation_registry import get_operation
from src.core.exceptions import ServiceError
from src.plugins.plugin_manager import PluginManager

_VALID_OPERATION_MODULE = """
from __future__ import annotations
from src.cleaning.base_operation import BaseOperation

class ManagerTestOperation(BaseOperation):
    @classmethod
    def apply(cls, dataset, **kwargs):
        raise NotImplementedError
"""


def _make_plugin(tmp_path: Path, plugin_name: str) -> None:
    plugin_dir = tmp_path / plugin_name
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin_name,
                "version": "1.0.0",
                "provides": {
                    "cleaning_operations": [f"{plugin_name}.ops:ManagerTestOperation"]
                },
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "ops.py").write_text(_VALID_OPERATION_MODULE, encoding="utf-8")


def test_load_plugins_disabled_registers_nothing(tmp_path: Path) -> None:
    _make_plugin(tmp_path, "mgr_plugin_disabled")
    manager = PluginManager([str(tmp_path)], enabled=False)

    loaded = manager.load_plugins()

    assert loaded == []
    with pytest.raises(ServiceError):
        get_operation("mgr_plugin_disabled_managertestoperation")


def test_load_plugins_registers_found_plugin(tmp_path: Path) -> None:
    _make_plugin(tmp_path, "mgr_plugin_ok")
    manager = PluginManager([str(tmp_path)], enabled=True)

    loaded = manager.load_plugins()

    assert len(loaded) == 1
    assert loaded[0].loaded_successfully
    assert get_operation("mgr_plugin_ok_managertestoperation").__name__ == (
        "ManagerTestOperation"
    )


def test_disable_plugin_unregisters_immediately(tmp_path: Path) -> None:
    _make_plugin(tmp_path, "mgr_plugin_toggle")
    manager = PluginManager([str(tmp_path)], enabled=True)
    manager.load_plugins()

    manager.disable_plugin("mgr_plugin_toggle")

    assert manager.is_disabled("mgr_plugin_toggle")
    with pytest.raises(ServiceError):
        get_operation("mgr_plugin_toggle_managertestoperation")


def test_enable_plugin_reregisters(tmp_path: Path) -> None:
    _make_plugin(tmp_path, "mgr_plugin_reenable")
    manager = PluginManager([str(tmp_path)], enabled=True)
    manager.load_plugins()
    manager.disable_plugin("mgr_plugin_reenable")

    manager.enable_plugin("mgr_plugin_reenable")

    assert not manager.is_disabled("mgr_plugin_reenable")
    assert get_operation("mgr_plugin_reenable_managertestoperation").__name__ == (
        "ManagerTestOperation"
    )


def test_load_plugins_twice_does_not_duplicate_registration(tmp_path: Path) -> None:
    _make_plugin(tmp_path, "mgr_plugin_reload")
    manager = PluginManager([str(tmp_path)], enabled=True)

    manager.load_plugins()
    loaded_again = (
        manager.load_plugins()
    )  # must not raise a duplicate-name ServiceError

    assert loaded_again[0].loaded_successfully


def test_disabled_plugin_names_honored_at_first_load(tmp_path: Path) -> None:
    _make_plugin(tmp_path, "mgr_plugin_preseeded")
    manager = PluginManager(
        [str(tmp_path)], enabled=True, disabled_plugin_names={"mgr_plugin_preseeded"}
    )

    loaded = manager.load_plugins()

    # Still appears (so it can be re-enabled later — see
    # discover_plugins's own docstring) but was never imported/
    # registered.
    assert len(loaded) == 1
    assert loaded[0].registered == {}
    assert manager.is_disabled("mgr_plugin_preseeded")
    with pytest.raises(ServiceError):
        get_operation("mgr_plugin_preseeded_managertestoperation")


def test_list_plugins_returns_a_copy(tmp_path: Path) -> None:
    _make_plugin(tmp_path, "mgr_plugin_copy")
    manager = PluginManager([str(tmp_path)], enabled=True)
    manager.load_plugins()

    plugins = manager.list_plugins()
    plugins.clear()

    assert len(manager.list_plugins()) == 1

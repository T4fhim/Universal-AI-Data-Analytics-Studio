# File: tests/plugins/test_plugin_manifest.py
"""Tests for src.plugins.plugin_manifest.PluginManifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.exceptions import ServiceError
from src.plugins.plugin_manifest import PluginManifest


def _write_manifest(tmp_path: Path, data: dict) -> Path:
    manifest_path = tmp_path / "plugin.json"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    return manifest_path


def test_load_valid_manifest(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        {
            "name": "example",
            "version": "1.2.3",
            "description": "An example plugin.",
            "provides": {"readers": ["example.readers:ExampleReader"]},
        },
    )
    manifest = PluginManifest.load(manifest_path)
    assert manifest.name == "example"
    assert manifest.version == "1.2.3"
    assert manifest.provides == {"readers": ["example.readers:ExampleReader"]}


def test_load_missing_name_raises(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, {"provides": {}})
    with pytest.raises(ServiceError, match="'name' is required"):
        PluginManifest.load(manifest_path)


def test_load_unsupported_category_raises(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        {"name": "example", "provides": {"forecast_models": ["x.y:Z"]}},
    )
    with pytest.raises(ServiceError, match="unsupported"):
        PluginManifest.load(manifest_path)


def test_load_invalid_json_raises(tmp_path: Path) -> None:
    manifest_path = tmp_path / "plugin.json"
    manifest_path.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ServiceError, match="not valid JSON"):
        PluginManifest.load(manifest_path)


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ServiceError, match="Could not read"):
        PluginManifest.load(tmp_path / "does_not_exist.json")


def test_load_defaults_version_and_description(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, {"name": "minimal"})
    manifest = PluginManifest.load(manifest_path)
    assert manifest.version == "0.0.0"
    assert manifest.description == ""
    assert manifest.provides == {}

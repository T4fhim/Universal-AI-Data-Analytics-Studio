# File: tests/core/test_config.py
"""Tests for src.core.config: load_config, validate_config_structure, AppConfig.

Covers config.py's self-healing behavior (missing/empty file recreation),
schema validation failures, and AppConfig.to_dict()'s deep-copy isolation
contract, all against isolated temp paths — never the project's real
config/config.yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.core.config import AppConfig, load_config, validate_config_structure
from src.core.exceptions import ConfigError


def test_missing_config_file_is_created_with_defaults(config_path: Path) -> None:
    assert not config_path.exists()

    data = load_config(config_path)

    assert config_path.exists()
    assert data["theme"] in ("dark", "light")
    assert data["recent_projects"] == []


def test_empty_config_file_is_recreated_with_defaults(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("", encoding="utf-8")

    data = load_config(config_path)

    assert data["theme"] in ("dark", "light")
    # The file on disk must have been rewritten with real content, not
    # left empty.
    assert config_path.read_text(encoding="utf-8").strip() != ""


def test_valid_config_file_round_trips(config_path: Path) -> None:
    first = load_config(config_path)
    second = load_config(config_path)

    assert first == second


def test_missing_top_level_key_raises_config_error(config_path: Path) -> None:
    load_config(config_path)  # write a valid default first
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    del loaded["theme"]
    config_path.write_text(yaml.safe_dump(loaded), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_wrong_type_for_top_level_key_raises_config_error(config_path: Path) -> None:
    load_config(config_path)
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    loaded["window"] = "not-a-dict"
    config_path.write_text(yaml.safe_dump(loaded), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_invalid_theme_value_raises_config_error(config_path: Path) -> None:
    load_config(config_path)
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    loaded["theme"] = "not-a-real-theme"
    config_path.write_text(yaml.safe_dump(loaded), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_validate_config_structure_rejects_non_dict_input() -> None:
    with pytest.raises(ConfigError):
        validate_config_structure(["not", "a", "dict"])  # type: ignore[arg-type]


def test_app_config_to_dict_is_a_deep_copy(config_path: Path) -> None:
    config = AppConfig.load(config_path)

    exported = config.to_dict()
    exported["window"]["width"] = 999999
    exported["recent_projects"].append("should-not-leak-back")

    # Mutating the exported dict must never leak back into the frozen
    # AppConfig's own internal state, per to_dict()'s documented deep
    # copy contract (config.py: shallow copy would alias nested dicts
    # and lists between the export and self._raw).
    assert config.window_width != 999999
    assert "should-not-leak-back" not in config.recent_projects
    assert config.to_dict()["window"]["width"] == config.window_width

# File: tests/services/test_settings_service_in_memory.py
"""``SettingsService(config, None)``: in-memory settings with no persistence.

Server mode must never read or write ``config.yaml`` (it is one shared file for every
tenant). ``config_path=None`` is the switch. Each "writes nothing" assertion has the
persisting twin beside it, so a service whose ``save()`` were simply broken could not
satisfy them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uadas_core.core.config import AppConfig
from uadas_core.core.exceptions import ConfigError
from uadas_core.services.settings_service import SettingsService


def test_save_with_no_path_writes_no_file_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    service = SettingsService(AppConfig.defaults(), None)

    service.set("autosave", "interval_minutes", value=9)
    service.save()

    assert service.get("autosave", "interval_minutes") == 9  # held in memory
    assert list(tmp_path.iterdir()) == []


def test_save_with_a_path_still_persists_twin(tmp_path: Path) -> None:
    target = tmp_path / "config" / "config.yaml"
    service = SettingsService(AppConfig.defaults(), target)

    service.save()

    assert target.exists()


def test_save_with_no_path_still_validates(tmp_path: Path) -> None:
    service = SettingsService(AppConfig.defaults(), None)
    service.set("autosave", "interval_minutes", value="not-an-int")

    with pytest.raises(ConfigError):
        service.save()


def test_reload_with_no_path_restores_the_initial_snapshot_not_disk() -> None:
    service = SettingsService(AppConfig.defaults(), None)
    service.set("autosave", "interval_minutes", value=99)

    service.reload()

    assert service.get("autosave", "interval_minutes") == 5


def test_two_in_memory_services_do_not_share_state() -> None:
    config = AppConfig.defaults()
    first = SettingsService(config, None)
    second = SettingsService(config, None)

    first.set("theme", value="light")

    assert first.get("theme") == "light"
    assert second.get("theme") == "dark"
    assert config.theme == "dark"

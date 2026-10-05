# File: tests/core/test_data_root.py
"""The explicit data-root override (``UADAS_DATA_ROOT``) for fixed on-disk paths.

``PROJECT_ROOT`` is derived from ``constants.py``'s own location (``parents[2]``),
which is only the repository root in an editable/source checkout; in a non-editable
install it points into ``site-packages``. Anything that must not depend on that --
the server -- sets ``UADAS_DATA_ROOT``. Unset, behaviour is exactly today's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uadas_core.core import constants
from uadas_core.core.config import AppConfig
from uadas_core.core.exceptions import ConfigError


def test_unset_env_var_resolves_to_the_project_root_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(constants.DATA_ROOT_ENV_VAR, raising=False)

    assert constants.data_root() == constants.PROJECT_ROOT
    assert constants.config_file_path() == constants.CONFIG_FILE_PATH
    assert constants.log_dir() == constants.LOG_DIR
    assert constants.projects_dir() == constants.PROJECTS_DIR


def test_env_var_relocates_every_fixed_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(constants.DATA_ROOT_ENV_VAR, str(tmp_path))

    assert constants.data_root() == tmp_path.resolve()
    assert constants.config_file_path() == tmp_path.resolve() / "config" / "config.yaml"
    assert constants.log_dir() == tmp_path.resolve() / "logs"
    assert constants.projects_dir() == tmp_path.resolve() / "projects"
    # The import-time constants stay anchored to the project root: they are the
    # documented default, not something the environment may silently rewrite.
    assert tmp_path.resolve() != constants.PROJECT_ROOT


def test_blank_env_var_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(constants.DATA_ROOT_ENV_VAR, "   ")

    assert constants.data_root() == constants.PROJECT_ROOT


@pytest.mark.parametrize("relative", ["relative-data", "./here", "../../..", "a/../b"])
def test_relative_override_is_rejected_not_resolved_against_the_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, relative: str
) -> None:
    """A relative value would silently depend on the launch directory (``../../..`` once
    resolved to somewhere nobody intended), which is exactly what the override exists to
    avoid -- so it is a configuration error."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(constants.DATA_ROOT_ENV_VAR, relative)

    with pytest.raises(ConfigError, match=constants.DATA_ROOT_ENV_VAR):
        constants.data_root()
    with pytest.raises(ConfigError):
        constants.config_file_path()


def test_absolute_override_is_normalised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    messy = tmp_path / "a" / ".." / "data"
    monkeypatch.setenv(constants.DATA_ROOT_ENV_VAR, str(messy))

    assert constants.data_root() == (tmp_path / "data").resolve()
    assert ".." not in constants.data_root().parts


def test_app_config_defaults_needs_no_file_and_no_project_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Server mode builds its config from in-code defaults, never from disk."""
    monkeypatch.chdir(tmp_path)

    config = AppConfig.defaults()

    assert isinstance(config, AppConfig)
    assert (
        config.plugins_enabled is True
    )  # the *desktop* default; server mode overrides
    assert config.recent_projects == []
    assert list(tmp_path.iterdir()) == []  # nothing written anywhere

# File: src/core/constants.py
"""Fixed values shared across more than one module in this package.

Only values referenced from at least two places live here. A value
used by exactly one file should stay local to that file — promoting
single-use values to this module just adds an extra import for no
benefit and makes it harder to tell, at a glance, which constants
actually govern cross-cutting behavior.

Path constants are anchored to the project root rather than to the
current working directory. The project root is derived from this
file's own location (three parents up: src/core/constants.py ->
src/core -> src -> project root) rather than from ``Path.cwd()``, so
that the application resolves its config and log locations the same
way regardless of the directory a caller happens to launch it from
(a plain terminal in the repo root, an IDE run configuration with a
different default working directory, a test runner, or a future
packaged executable).
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Application identity
# --------------------------------------------------------------------------

APP_NAME: str = "Universal AI Data Analytics Studio"
APP_VERSION: str = "0.1.0"
ORGANIZATION_NAME: str = "Universal AI Data Analytics Studio Project"

# --------------------------------------------------------------------------
# Path anchors
# --------------------------------------------------------------------------
# constants.py -> src/core -> src -> project root
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

CONFIG_DIR: Path = PROJECT_ROOT / "config"
CONFIG_FILE_PATH: Path = CONFIG_DIR / "config.yaml"

LOG_DIR: Path = PROJECT_ROOT / "logs"

PROJECTS_DIR: Path = PROJECT_ROOT / "projects"

# --------------------------------------------------------------------------
# Logging defaults
# --------------------------------------------------------------------------
# These are the values used if config.yaml does not specify its own
# logging section, or specifies it incompletely. config.py is
# responsible for merging user-supplied values over these defaults;
# logger.py consumes only the final, merged values and does not read
# these defaults directly, so that config.py remains the single place
# where "what logging configuration is actually in effect" is decided.

DEFAULT_LOG_LEVEL: str = "INFO"
DEFAULT_LOG_FILE_MAX_BYTES: int = 5 * 1024 * 1024  # 5 MiB per rotated file
DEFAULT_LOG_FILE_BACKUP_COUNT: int = 5
DEFAULT_LOG_FILENAME: str = "application.log"

# --------------------------------------------------------------------------
# Window defaults
# --------------------------------------------------------------------------
# Referenced by config.py's defaults today and will be consumed by
# src/ui/main_window.py in milestone 1b. Defined here now because the
# config default structure needs a concrete value to write into
# config.yaml on first run, even though nothing in this milestone
# constructs a window.

DEFAULT_WINDOW_WIDTH: int = 1600
DEFAULT_WINDOW_HEIGHT: int = 900


# --------------------------------------------------------------------------
# Theme defaults
# --------------------------------------------------------------------------

DEFAULT_THEME: str = "dark"
AVAILABLE_THEMES: tuple[str, ...] = ("dark", "light")

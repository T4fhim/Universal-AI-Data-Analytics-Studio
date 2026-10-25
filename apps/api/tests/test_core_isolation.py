# File: apps/api/tests/test_core_isolation.py
"""``uadas_core`` stays framework-free even with the web backend installed.

Why: the import-linter contracts prove this statically; this is the runtime half.
Importing the core in a fresh interpreter must not pull Django into ``sys.modules`` --
if it ever does, the server-only dependency has leaked into the library that the
desktop-era tooling and any future non-web consumer share.
"""

from __future__ import annotations

import subprocess
import sys

_PROBE = """
import sys
import uadas_core
import uadas_core.bootstrap
import uadas_core.services.workspace_service
import uadas_core.ai.assistant_service
leaked = sorted(m for m in sys.modules if m == "django" or m.startswith("django."))
assert "django" not in sys.modules, f"django leaked into uadas_core imports: {leaked[:5]}"
print("core imports clean")
"""


def test_importing_uadas_core_does_not_import_django() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "core imports clean" in result.stdout

# File: apps/api/uadas_api/web/openapi.py
"""Export the OpenAPI 3.1 document offline, deterministically, and check it against the committed copy.

Why offline: the HTTP route (``/api/openapi.json``) exists only when ``DEBUG`` is on, because an
unauthenticated schema in production is an endpoint map handed to an attacker. The contract itself
-- what ``openapi-typescript`` (Phase 4.1) and Schemathesis consume -- is generated here from
``api.get_openapi_schema()`` with no server and no database, and **committed** at
``apps/api/openapi.json``. CI regenerates it and fails on any difference (``--check``), so a route
change that does not update the committed contract cannot merge.

Deterministic: ``sort_keys``, two-space indent, a trailing newline, ``ensure_ascii`` off. Nothing
in the document depends on the environment (the settings only decide whether the docs routes
exist; the paths come from the routers).

Usage (from ``apps/api``; ``DJANGO_SETTINGS_MODULE`` defaults to the hermetic test settings)::

    python -m uadas_api.web.openapi            # rewrite apps/api/openapi.json
    python -m uadas_api.web.openapi --check    # exit 1 (and say how to fix) on drift

``--committed PATH`` points either mode at another file (the drift test uses it).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

COMMITTED_PATH = Path(__file__).resolve().parents[2] / "openapi.json"


def schema_text(schema: dict[str, Any]) -> str:
    """``schema`` as the committed file's exact text."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def current_text() -> str:
    """The live API's schema as committed-file text (Django must already be set up)."""
    from uadas_api.api import api

    return schema_text(api.get_openapi_schema())


def main(argv: list[str]) -> int:
    """Write (default) or ``--check`` the committed schema; returns the process exit code."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "uadas_api.settings.test")
    import django

    django.setup()
    text = current_text()
    target = (
        Path(argv[argv.index("--committed") + 1])
        if "--committed" in argv
        else COMMITTED_PATH
    )
    if "--check" in argv:
        committed = target.read_text(encoding="utf-8") if target.exists() else ""
        if committed == text:
            print("openapi.json is up to date")
            return 0
        print(
            "openapi.json is out of date: run `python -m uadas_api.web.openapi` "
            "from apps/api and commit the result",
            file=sys.stderr,
        )
        return 1
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess in tests
    raise SystemExit(main(sys.argv[1:]))

# File: apps/api/manage.py
"""Django's command-line entry point for the ``uadas_api`` backend.

Why it defaults to ``uadas_api.settings.dev``: running ``python manage.py check`` or
``runserver`` from a fresh clone should need no configuration. Production processes do
not go through here -- ``wsgi`` / ``asgi`` default to ``prod`` and fail closed.
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Run Django's management utility."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "uadas_api.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Is it installed? "
            "Run: pip install -r requirements.txt -e . -e apps/api"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

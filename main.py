

from __future__ import annotations

import sys

from src.core.app import Application


def main() -> int:
    """Constructing and running the application, while returning its exit code."""
    application = Application.create()
    return application.run()


if __name__ == "__main__":
    sys.exit(main())

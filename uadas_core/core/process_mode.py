# File: uadas_core/core/process_mode.py
"""A one-way, thread-safe latch recording whether this process is desktop or server.

Why: server mode's guarantees (no plugin loading, no YAML, no log files, no
process-global job-runner bridge) are conventions of ``bootstrap_process(server_mode=
True)`` -- nothing in the import graph stops other code in the same process from also
calling the legacy ``bootstrap()`` and quietly undoing them (the ``.importlinter`` edges
that let ``uadas_api`` reach the composition root also let it *import* the legacy
functions). And the reverse order is just as bad: a desktop process that later starts
"server mode" keeps its rotating-file log handler and its loaded plugins. So the first
:func:`~uadas_core.bootstrap.bootstrap_process` call *claims* the process mode here and a
conflicting later claim raises a :class:`~uadas_core.core.exceptions.BootstrapError`
naming both modes. Repeating the same mode is legal (the legacy desktop app and the test
suite bootstrap more than once).

There is deliberately no production way to release the latch: a process does not change
its nature. :func:`reset_process_mode_for_tests` exists solely for test fixtures
(``tests/conftest.py``'s ``reset_logging_state``, the API's ``fresh_bridge``); it is an
explicit function, not an environment variable, so it cannot be flipped by deployment
configuration.
"""

from __future__ import annotations

import threading
from enum import StrEnum

from uadas_core.core.exceptions import BootstrapError


class ProcessMode(StrEnum):
    """The two ways a process can run the core."""

    DESKTOP = "desktop"
    SERVER = "server"


_lock = threading.Lock()
_mode: ProcessMode | None = None


def claim_process_mode(mode: ProcessMode) -> None:
    """Claim ``mode`` for this process, or raise if the other mode already holds it.

    Raises:
        BootstrapError: If the process is already in the opposite mode. Nothing is
            changed by a refused claim.
    """
    global _mode
    with _lock:
        if _mode is None:
            _mode = mode
            return
        if _mode is mode:
            return
        raise BootstrapError(
            f"This process already runs the core in {_mode.value} mode, so it cannot "
            f"start {mode.value} mode: the modes are mutually exclusive (server mode's "
            "no-plugins / no-YAML / no-log-files guarantees, and desktop mode's "
            "file-backed config and logging, cannot be mixed in one process)."
        )


def current_process_mode() -> ProcessMode | None:
    """Return the claimed mode, or ``None`` if no ``bootstrap_process`` has run yet."""
    with _lock:
        return _mode


def reset_process_mode_for_tests() -> None:
    """Release the latch. **Test fixtures only** -- never call this from production code."""
    global _mode
    with _lock:
        _mode = None

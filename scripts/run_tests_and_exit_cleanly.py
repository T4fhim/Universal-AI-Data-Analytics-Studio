# File: scripts/run_tests_and_exit_cleanly.py
"""Runs pytest, then bypasses CPython's own interpreter finalization.

Non-shipping infrastructure, alongside ``screenshot_app_state.py`` and
``preview_manual.py`` under ``scripts/`` -- a CI-invoked tool, never
imported by ``src/`` or ``tests/`` themselves.

Why this exists: a real, confirmed, reproduced CI-only failure (found via
``.github/workflows/ci.yml``'s own ``pytest-output.log`` capture, added
investigating this exact problem) showed pytest completing a fully clean
run --

    1371 passed, 103 skipped, 3 deselected, ... in 359.16s (0:05:59)
    Windows fatal exception: access violation

    Current thread 0x00000d54 (most recent call first):

-- with zero failed tests, immediately followed by a native access
violation with an *empty* thread traceback (no Python frames at all).
An empty native traceback at that exact point in the log means the crash
happens after ``pytest.main()`` has already returned its result, during
``Py_Finalize()``'s own native cleanup -- almost certainly the same class
of Windows Qt-platform-integration-destruction crash
``tests/ui/conftest.py``'s own ``qapp`` fixture docstring already
documents and works around *mid-session* ("calling quit() between tests
crashes on Windows, because Qt destroys the platform integration while
widgets from the previous test are still pending deletion") -- just
occurring once, unavoidably, at final process teardown instead, where
nothing can call ``quit()`` earlier to prevent it.

Since pytest has already fully determined and reported its real result
before this crash occurs, the crash carries no information about test
correctness -- it is pure interpreter-shutdown noise. ``os._exit()``
terminates the process immediately, skipping ``atexit`` handlers,
garbage collection, and every native destructor ``Py_Finalize()`` would
otherwise run (including whatever in Qt's own native teardown chain is
actually crashing) -- exactly the risky path this script exists to skip,
once pytest's own real exit code is already safely captured.
"""

from __future__ import annotations

import os
import sys

import pytest

if __name__ == "__main__":
    exit_code = pytest.main(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(exit_code))

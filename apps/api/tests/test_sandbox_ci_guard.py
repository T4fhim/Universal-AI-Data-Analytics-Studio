# File: apps/api/tests/test_sandbox_ci_guard.py
"""CI must not quietly skip the sandbox's Linux-only guarantees (3.5).

Why: the memory, CPU, file-size, descriptor and process limits can only be proven on Linux, so
those tests carry ``skipif`` marks and skip -- by design -- on a Windows laptop. A skip is a
green build, so a CI job that ran on the wrong platform, or as root (where ``RLIMIT_NPROC`` is
not enforced and the fork-bomb tests skip), would drop the strongest evidence for the sandbox
with nobody noticing. Two layers, the same shape as ``test_storage_ci_guard.py``:

* this test fails when GitHub Actions' ``CI=true`` is set but the environment could not run the
  rlimit tests (not Linux, or root);
* ``ci.yml`` fails the job if more tests skip than the budgeted ones (explained there).

The guard does not carry its own copy of the skip condition: it reads it back out of the very
``skipif`` marks the tests use (``sandbox_support.marks_would_skip``), so the two cannot drift.
"""

from __future__ import annotations

import os
import sys

import pytest
from sandbox_support import (
    LINUX_ONLY_MARKS,
    current_euid,
    linux_only,
    marks_would_skip,
    needs_non_root,
    skip_conditions,
)

from uadas_api.sandbox.limits import limits_enforceable


def ci_requires_rlimit_tests(env: dict[str, str]) -> bool:
    """Whether this run is a CI run (the platform that must prove the Linux guarantees)."""
    return env.get("CI", "").lower() == "true"


@pytest.mark.parametrize(
    ("enforceable", "euid", "linux_skips", "non_root_skips"),
    [
        (True, 1000, False, False),  # a Linux CI runner, unprivileged: everything runs
        (
            True,
            0,
            False,
            True,
        ),  # root: RLIMIT_NPROC is not enforced, the fork tests skip
        (False, 1000, True, False),  # Windows / macOS: nothing is enforceable
        (False, None, True, False),
        (True, None, False, False),
    ],
)
def test_the_skip_conditions(
    enforceable: bool, euid: int | None, linux_skips: bool, non_root_skips: bool
) -> None:
    linux, non_root, _ = skip_conditions(enforceable, euid)
    assert (linux, non_root) == (linux_skips, non_root_skips)


def test_the_root_only_tests_run_only_for_a_root_worker_on_linux() -> None:
    assert skip_conditions(True, 0)[2] is False
    assert skip_conditions(True, 1000)[2] is True
    assert skip_conditions(False, 0)[2] is True


def test_the_marks_carry_the_live_conditions() -> None:
    # The marks the tests use were built from the same function and the same live inputs.
    linux, non_root, _ = skip_conditions(limits_enforceable(), current_euid())
    assert bool(linux_only.mark.args[0]) is linux
    assert bool(needs_non_root.mark.args[0]) is non_root


def test_ci_detection() -> None:
    assert ci_requires_rlimit_tests({"CI": "true"})
    assert ci_requires_rlimit_tests({"CI": "TRUE"})
    assert not ci_requires_rlimit_tests({"CI": "false"})
    assert not ci_requires_rlimit_tests({})


def test_this_run_can_execute_the_linux_only_sandbox_tests_when_it_is_a_ci_run() -> (
    None
):
    if ci_requires_rlimit_tests(dict(os.environ)):
        assert not marks_would_skip(*LINUX_ONLY_MARKS), (
            f"CI=true but the sandbox's rlimit tests would skip (platform={sys.platform}, "
            f"euid={current_euid()}): run the api-test job on an unprivileged Linux user"
        )

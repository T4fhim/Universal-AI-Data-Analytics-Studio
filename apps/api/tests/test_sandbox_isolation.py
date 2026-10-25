# File: apps/api/tests/test_sandbox_isolation.py
"""What separates the parser child from the worker, from the network and from a dead parent.

Why this file exists: a security review ran the child as an attacker would and found that the
earlier claims ("owner-only temp dir", "stripped environment", "network guard") were weaker than
written. Each finding is a test here, proved against the *production* runner and child (the
hostile reader of ``sandbox_launcher.py`` is the only fake part):

* **Same uid, so /proc is open.** A child of the same user can read ``/proc/<ppid>/environ`` (the
  worker's ``SECRET_KEY``, ``DATABASE_URL``). The worker therefore makes itself non-dumpable
  (``prctl(PR_SET_DUMPABLE, 0)``), which makes its ``/proc`` entries unreadable to the same uid;
  and a worker that may switch identity runs the child as a dedicated uid
  (``SANDBOX_CHILD_UID``). Each has a positive twin: without the hardening the very same probe
  *does* read the secret, so a probe that only ever fails would prove nothing.
* **The socket shim is bypassable** (the raw ``_socket`` class is one ``__mro__`` lookup away), so
  it is no longer counted as enforcement. The real layer is a network namespace the child unshares;
  where the kernel refuses (Docker's default seccomp, an AppArmor-restricted runner) the child
  reports ``network_isolated=False`` and the test asserts that honest report -- it does not skip.
  ``SANDBOX_REQUIRE_NETNS=1`` (set where the platform is known to allow it) makes the same test
  demand isolation.
* **Kill paths.** A worker killed with SIGKILL must take its child with it (``PR_SET_PDEATHSIG``),
  the child has its own wall-clock alarm, and a directory a dead worker left behind is reaped.
  Grandchildren that call ``setsid()`` escape all of this; the documented bound is
  ``RLIMIT_NPROC`` and the deployment's cgroup ``pids_limit`` (``plans/phase-3-5-jobs.md``).
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sandbox_support import (
    HERE,
    LAUNCHER,
    LAZY_LAUNCHER,
    linux_only,
    make_limits,
    needs_non_root,
    needs_root,
    run_probe,
)

from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.sandbox.limits import SandboxLimits
from uadas_api.sandbox.protocol import OUTPUT_NAME, encode_request
from uadas_api.sandbox.runner import SandboxWorkspace

SECRET = "uadas-probe-secret-7f3a91"
# /proc/<pid>/environ is the *initial* environment of the process (a later ``os.environ[...] =``
# does not change it), so the probe looks for a variable every process starts with: the same
# kind of block that holds a worker's SECRET_KEY and DATABASE_URL when they come from the
# environment, which is how production supplies them.
ENV_MARKER = "PATH="


@pytest.fixture
def work(tmp_path: Path) -> Path:
    root = tmp_path / "sandbox-work"
    root.mkdir()
    return root


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    yield server
    server.close()


def _set_dumpable(flag: int) -> None:
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(4, flag, 0, 0, 0) == 0  # PR_SET_DUMPABLE


# ------------------------------------------------------------ S1: the worker's secrets


@linux_only
def test_the_child_cannot_read_the_workers_environment(work: Path) -> None:
    # No network namespace here (a user namespace would by itself hide the parent's /proc from
    # the child on current kernels, which would make this test pass for the wrong reason): the
    # denial must come from the worker being non-dumpable.
    note, _ = run_probe(
        work, f"probe_parent_env {ENV_MARKER}", network_isolation="none-acknowledged"
    )
    assert note.startswith("DENIED"), note


@linux_only
def test_without_the_hardening_the_same_probe_reads_the_secret(
    work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Positive twin: the probe is capable of reading a same-uid parent's environment.
    from uadas_api.sandbox import runner

    monkeypatch.setattr(runner, "harden_worker", lambda: False, raising=False)
    _set_dumpable(1)
    note, _ = run_probe(
        work, f"probe_parent_env {ENV_MARKER}", network_isolation="none-acknowledged"
    )
    assert note == "READ:found", note


def _get_dumpable() -> int:
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    return int(libc.prctl(3, 0, 0, 0, 0))  # PR_GET_DUMPABLE returns the flag itself


@linux_only
def test_the_worker_reports_that_it_hardened_itself() -> None:
    from uadas_api.sandbox.isolation import harden_worker

    _set_dumpable(1)
    assert _get_dumpable() == 1
    assert harden_worker() is True
    assert _get_dumpable() == 0


@linux_only
def test_the_worker_is_not_dumpable_after_a_parse(work: Path) -> None:
    _set_dumpable(1)
    run_probe(work, "benign")
    assert _get_dumpable() == 0


def test_hardening_is_a_no_op_off_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    from uadas_api.sandbox import isolation

    monkeypatch.setattr(isolation.sys, "platform", "win32")
    assert isolation.harden_worker() is False  # nothing to do, and it says so


@linux_only
def test_same_uid_children_can_read_each_others_files_which_is_why_isolation_is_documented(
    work: Path, tmp_path: Path
) -> None:
    # Said plainly, as a test: 0700 means nothing between processes of one uid. Another job's
    # input is readable by this job's child unless a dedicated uid or a container separates them.
    other = tmp_path / "other-job"
    other.mkdir(mode=0o700)
    (other / "input.csv").write_text(f"a,b\n{SECRET},2\n")
    note, _ = run_probe(work, f"probe_file {other / 'input.csv'} {SECRET}")
    assert note == "READ:found", note


# ------------------------------------------------------------- S1(b): a dedicated uid


CHILD_UID = 61234


@pytest.fixture
def open_work(tmp_path: Path) -> Iterator[Path]:
    """A traversable root (the dedicated-uid child must reach its own job directory)."""
    root = tmp_path / "open-work"
    root.mkdir()
    for part in (root, *root.parents):
        if part == Path(part.anchor):
            break
        try:
            os.chmod(part, os.stat(part).st_mode | 0o755)
        except PermissionError:  # a directory we do not own (/tmp): already traversable
            break
    yield root


@needs_root
def test_a_dedicated_uid_child_has_its_own_identity_no_capabilities_and_no_access(
    open_work: Path, tmp_path: Path
) -> None:
    identity, result = run_probe(
        open_work,
        "probe_identity",
        child_uid=CHILD_UID,
        child_gid=CHILD_UID,
        network_isolation="none-acknowledged",  # (a user namespace shows the uid as 65534)
        require_enforcement=True,
    )
    assert identity.startswith(f"uid={CHILD_UID} gid={CHILD_UID}"), identity
    assert identity.endswith("0000000000000000"), identity  # CapEff empty
    # RLIMIT_NPROC now applies: the child is not root, even though the worker is.
    assert result.enforcement["nproc"] is True
    # With the network namespace on, the identity is the same user (the namespace merely shows it
    # unmapped) and the capabilities the new user namespace granted are dropped again.
    isolated, _ = run_probe(
        open_work, "probe_identity", child_uid=CHILD_UID, child_gid=CHILD_UID
    )
    assert isolated.endswith("0000000000000000"), isolated

    env_note, _ = run_probe(
        open_work,
        f"probe_parent_env {ENV_MARKER}",
        child_uid=CHILD_UID,
        child_gid=CHILD_UID,
        network_isolation="none-acknowledged",
    )
    assert env_note.startswith("DENIED"), env_note

    private = tmp_path / "worker-only"
    private.mkdir(mode=0o700)
    (private / "secret.txt").write_text(SECRET)
    file_note, _ = run_probe(
        open_work,
        f"probe_file {private / 'secret.txt'} {SECRET}",
        child_uid=CHILD_UID,
        child_gid=CHILD_UID,
        network_isolation="none-acknowledged",
    )
    assert file_note.startswith("DENIED"), file_note
    # Twin: the same file IS readable by a child that runs as the worker's own uid (root here).
    same_uid, _ = run_probe(open_work, f"probe_file {private / 'secret.txt'} {SECRET}")
    assert same_uid == "READ:found", same_uid


@needs_root
def test_a_dedicated_uid_child_still_parses_a_good_file(open_work: Path) -> None:
    # Positive twin of the test above: the privilege drop does not break the happy path.
    _, result = run_probe(open_work, "benign", child_uid=CHILD_UID, child_gid=CHILD_UID)
    assert (result.row_count, result.column_count) == (3, 2)


def test_an_identity_that_cannot_be_switched_is_unavailable_not_silently_ignored(
    work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uadas_api.sandbox import runner

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError

    real = subprocess.Popen
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: refuse() if k.get("user") is not None else real(*a, **k),
    )
    # Let the directory hand-over pass (a worker that may chown) so the refusal under test is the
    # one at spawn time: the kernel refusing setuid to a worker that may not.
    monkeypatch.setattr(os, "chown", lambda *a, **k: None, raising=False)
    limits = make_limits(work, child_uid=CHILD_UID, child_gid=CHILD_UID)
    workspace = SandboxWorkspace(
        limits, child_command=LAUNCHER, require_enforcement=False
    )
    with pytest.raises(SandboxError) as excinfo, workspace:
        workspace.input_path(".csv").write_text("benign")
        workspace.parse(".csv")
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_UNAVAILABLE
    assert list(work.iterdir()) == []  # and nothing was left behind


def test_a_worker_that_cannot_hand_over_the_directory_is_unavailable(
    work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "chown", refuse, raising=False)
    limits = make_limits(work, child_uid=CHILD_UID, child_gid=CHILD_UID)
    with (
        pytest.raises(SandboxError) as excinfo,
        SandboxWorkspace(limits, child_command=LAUNCHER, require_enforcement=False),
    ):
        pass
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_UNAVAILABLE
    assert list(work.iterdir()) == []


# --------------------------------------------------------- S2: the network, for real


@linux_only
def test_the_raw_socket_bypass_is_stopped_exactly_when_the_child_reports_isolation(
    work: Path, listener: socket.socket
) -> None:
    port = listener.getsockname()[1]
    note, result = run_probe(work, f"probe_raw_socket {port}")
    isolated = result.enforcement["network_isolated"]
    if os.environ.get("SANDBOX_REQUIRE_NETNS") == "1":
        assert (
            isolated
        ), "SANDBOX_REQUIRE_NETNS=1 but the kernel refused unshare(CLONE_NEWNET)"
    if isolated:
        assert note.startswith(
            "FAILED"
        ), note  # the namespace has no route to the listener
    else:
        # Honest, and documented: where the kernel refuses (Docker's default seccomp profile, an
        # AppArmor-restricted runner) only the bypassable shim stands, and the child says so.
        assert note == "CONNECTED", note
        assert result.network_isolated is False


@linux_only
def test_with_no_isolation_attempted_the_bypass_connects_which_proves_the_probe_works(
    work: Path, listener: socket.socket
) -> None:
    # Positive twin: the explicit acknowledgement turns the namespace off, and the very same raw
    # connect then reaches the listener. (The shim is installed in both runs.)
    port = listener.getsockname()[1]
    note, result = run_probe(
        work, f"probe_raw_socket {port}", network_isolation="none-acknowledged"
    )
    assert note == "CONNECTED"
    assert result.enforcement["network_isolated"] is False
    assert result.enforcement["network_guard"] is True  # present, and not counted
    assert result.network_isolated is False


@linux_only
def test_the_shim_still_stops_the_ordinary_connect(
    work: Path, listener: socket.socket
) -> None:
    # Defence in depth is kept: the plain `socket.create_connection` route is refused.
    port = listener.getsockname()[1]
    with pytest.raises(SandboxError) as excinfo:
        run_probe(work, f"socket {port}")
    assert excinfo.value.code is SandboxErrorCode.BLOCKED_OPERATION


# ------------------------------------------------------- S3: dead parents and stale dirs


def _alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as handle:
            state = handle.read().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state not in {
        "Z",
        "X",
    }  # a zombie is dead; its parent has just not reaped it


def _wait_for(path: Path, seconds: float = 30.0) -> str:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(0.1)
    raise AssertionError(f"{path.name} never appeared")


@linux_only
def test_killing_the_worker_with_sigkill_takes_the_child_with_it_and_the_dir_is_reaped(
    work: Path, tmp_path: Path
) -> None:
    pidfile, info = tmp_path / "child.pid", tmp_path / "workspace.path"
    parent = subprocess.Popen(
        [
            sys.executable,
            str(HERE / "sandbox_parent_probe.py"),
            str(work),
            str(pidfile),
            str(info),
        ]
    )
    try:
        child_pid = int(_wait_for(pidfile))
        workspace = Path(_wait_for(info))
        assert _alive(child_pid)  # twin: while the worker lives, so does its child
        parent.kill()  # SIGKILL: what Celery's hard time limit and the OOM killer do
        parent.wait(timeout=30)
        deadline = time.monotonic() + 15
        while _alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(child_pid), "the child outlived a SIGKILLed worker"
        # Nothing cleaned up the job directory (the worker could not): it holds the tenant's input.
        assert workspace.exists()
        from uadas_api.sandbox.isolation import reap_stale_workspaces

        assert reap_stale_workspaces(work, older_than=0) == 1
        assert not workspace.exists()
    finally:
        if parent.poll() is None:
            parent.kill()


@linux_only
def test_the_child_has_its_own_wall_clock_alarm(work: Path) -> None:
    # The parent enforces the wall limit; this is for when it cannot (stuck, or dead and PDEATHSIG
    # unavailable). The real child, a reader that sleeps forever, a one-second alarm.
    (work / "input.csv").write_text("sleep")
    request = encode_request(
        "input.csv",
        OUTPUT_NAME,
        {**SandboxLimits().child_payload(), "wall_alarm_seconds": 1},
    )
    process = subprocess.Popen(
        LAZY_LAUNCHER,
        cwd=work,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    started = time.monotonic()
    try:
        assert process.stdin is not None
        process.stdin.write(request)
        process.stdin.close()
        code = process.wait(timeout=30)
    finally:
        process.kill()
        process.communicate()
    assert code == -signal.SIGALRM
    assert time.monotonic() - started < 25


def test_the_reaper_removes_only_old_job_directories_it_owns(tmp_path: Path) -> None:
    from uadas_api.sandbox.isolation import reap_stale_workspaces

    if os.name != "posix":
        pytest.skip("ownership checks use POSIX uids")
    old = tmp_path / "uadas-sbx-old"
    young = tmp_path / "uadas-sbx-young"
    other = tmp_path / "other-dir"
    for directory in (old, young, other):
        directory.mkdir()
        (directory / "input.csv").write_text("a\n1\n")
    marker_file = tmp_path / "uadas-sbx-a-file"
    marker_file.write_text("not a directory")
    target = tmp_path / "precious"
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    link = tmp_path / "uadas-sbx-link"
    link.symlink_to(target, target_is_directory=True)
    long_ago = time.time() - 7200
    for path in (old, other, marker_file):
        os.utime(path, (long_ago, long_ago))
    os.utime(old / "input.csv", (long_ago, long_ago))

    assert reap_stale_workspaces(tmp_path, older_than=3600) == 1
    assert not old.exists()
    assert young.exists() and other.exists() and marker_file.exists()
    assert link.is_symlink() and (target / "keep.txt").read_text() == "keep"


def test_the_reaper_leaves_directories_of_other_users_alone(tmp_path: Path) -> None:
    from uadas_api.sandbox.isolation import reap_stale_workspaces

    if os.name != "posix":
        pytest.skip("ownership checks use POSIX uids")
    stale = tmp_path / "uadas-sbx-foreign"
    stale.mkdir()
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    # Pretend the only uid we may clean for is not the owner's.
    assert (
        reap_stale_workspaces(tmp_path, older_than=3600, owner_uids={os.geteuid() + 1})
        == 0
    )
    assert stale.exists()
    assert (
        reap_stale_workspaces(tmp_path, older_than=3600, owner_uids={os.geteuid()}) == 1
    )


def test_a_missing_root_is_nothing_to_reap(tmp_path: Path) -> None:
    from uadas_api.sandbox.isolation import reap_stale_workspaces

    assert reap_stale_workspaces(tmp_path / "does-not-exist", older_than=0) == 0


@needs_non_root
@linux_only
def test_a_real_parse_reports_every_enforcement_the_gate_requires(work: Path) -> None:
    _, result = run_probe(work, "benign", require_enforcement=True)
    for key in ("memory", "cpu", "fsize", "nproc"):
        assert result.enforcement[key] is True, key
    assert json.dumps(result.enforcement)  # a plain mapping of booleans

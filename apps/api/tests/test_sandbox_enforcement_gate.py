# File: apps/api/tests/test_sandbox_enforcement_gate.py
"""What the parent insists the child proved before it trusts a parse (platform independent).

Why: ``require_enforcement`` is the one place the parent turns "the child says it applied its
limits" into "refuse the result". The review found it counted the bypassable socket shim as
network enforcement and ignored ``nproc`` and ``fsize``. These tests drive the gate with a fake
child that replies with an exact ``enforcement`` mapping, so each requirement is isolated, and
each refusal has an accepted twin (the same reply plus the one missing key).
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.sandbox.limits import SandboxLimits
from uadas_api.sandbox.runner import SandboxWorkspace

PARQUET = b"PAR1" + b"\x00" * 64 + b"PAR1"
BASE = {
    "core": True,
    "memory": True,
    "cpu": True,
    "fsize": True,
    "nofile": True,
    "nproc": True,
    "network_guard": True,
    "network_isolated": False,
    "hardened": True,
}


def reply(**enforcement: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "source_format": "csv",
        "row_count": 3,
        "column_count": 2,
        "columns": [["a", "int64"], ["b", "object"]],
        "warning_count": 0,
        "enforcement": {**BASE, **enforcement},
    }


def parse_with(tmp_path: Path, body: dict[str, Any], **limit_overrides: Any) -> Any:
    script = tmp_path / "fake_child.py"
    script.write_text(
        textwrap.dedent(f"""
            import sys
            sys.stdin.buffer.read()
            open("out.parquet", "wb").write({PARQUET!r})
            print({json.dumps(body)!r})
        """),
        encoding="utf-8",
    )
    root = tmp_path / "work"
    root.mkdir(exist_ok=True)
    limits = SandboxLimits(tmp_root=str(root), wall_seconds=30, **limit_overrides)
    workspace = SandboxWorkspace(
        limits,
        child_command=[sys.executable, "-I", str(script)],
        require_enforcement=True,
    )
    with workspace:
        workspace.input_path(".csv").write_text("a,b\n1,x\n")
        return workspace.parse(".csv")


def refused(tmp_path: Path, body: dict[str, Any], **limits: Any) -> None:
    with pytest.raises(SandboxError) as excinfo:
        parse_with(tmp_path, body, **limits)
    assert excinfo.value.code is SandboxErrorCode.SANDBOX_UNAVAILABLE


def test_a_child_that_applied_everything_is_accepted(tmp_path: Path) -> None:
    result = parse_with(tmp_path, reply())
    assert (result.row_count, result.limits_enforced) == (3, True)


@pytest.mark.parametrize("missing", ["memory", "cpu", "fsize", "nproc"])
def test_every_required_limit_is_required(tmp_path: Path, missing: str) -> None:
    refused(tmp_path, reply(**{missing: False}))
    # twin: the same reply with the limit applied is accepted (and nofile / core are not required)
    parse_with(tmp_path, reply(nofile=False, core=False))


def test_the_process_cap_is_not_required_when_it_was_switched_off(
    tmp_path: Path,
) -> None:
    refused(tmp_path, reply(nproc=False))
    parse_with(tmp_path, reply(nproc=False), process_headroom=0)


def test_the_process_cap_is_not_required_for_an_acknowledged_container(
    tmp_path: Path,
) -> None:
    # A root worker in a container loses RLIMIT_NPROC; the operator says the cgroup bounds it.
    parse_with(tmp_path, reply(nproc=False), isolation_acknowledged="container")


def test_the_socket_shim_is_not_network_enforcement(tmp_path: Path) -> None:
    shim_only = reply(network_guard=True, network_isolated=False)
    result = parse_with(
        tmp_path, shim_only
    )  # best effort: nothing required, nothing claimed
    assert result.network_isolated is False
    refused(tmp_path, shim_only, network_isolation="unshare")
    isolated = parse_with(
        tmp_path, reply(network_isolated=True), network_isolation="unshare"
    )
    assert isolated.network_isolated is True


def test_an_acknowledged_container_counts_as_network_isolation(tmp_path: Path) -> None:
    result = parse_with(tmp_path, reply(), network_isolation="container")
    assert result.network_isolated is True  # stated by the operator, not measured
    assert result.enforcement["network_isolated"] is False


def test_accepting_the_shim_alone_is_an_explicit_choice_and_stays_unisolated(
    tmp_path: Path,
) -> None:
    result = parse_with(tmp_path, reply(), network_isolation="none-acknowledged")
    assert result.network_isolated is False


# ------------------------------------------------------------------ the limits object


def test_the_request_carries_the_parent_pid_the_alarm_and_the_network_choice() -> None:
    payload = SandboxLimits(wall_seconds=30).child_payload(parent_pid=4242)
    assert payload["parent_pid"] == 4242
    assert payload["wall_alarm_seconds"] > 30  # the parent acts first
    assert payload["isolate_network"] == 1
    off = SandboxLimits(network_isolation="none-acknowledged").child_payload()
    assert off["isolate_network"] == 0 and "parent_pid" not in off
    assert (
        SandboxLimits(network_isolation="container").child_payload()["isolate_network"]
        == 0
    )
    assert (
        SandboxLimits(network_isolation="unshare").child_payload()["isolate_network"]
        == 1
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"child_uid": 1000},  # a uid without a gid
        {"child_gid": 1000},
        {"child_uid": 0, "child_gid": 0},  # root is not a dedicated user
        {"child_uid": 1000, "child_gid": 0},
        {"child_uid": -5, "child_gid": 7},
        {"network_isolation": "yes"},
        {"isolation_acknowledged": "host"},
    ],
)
def test_nonsense_isolation_settings_are_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SandboxLimits(**bad)
    SandboxLimits(
        child_uid=61234, child_gid=61234, network_isolation="unshare"
    )  # twin: sane values pass

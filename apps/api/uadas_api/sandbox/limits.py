# File: apps/api/uadas_api/sandbox/limits.py
"""The sandbox's resource limits, and the one honest answer to "can they be enforced here?".

Why one frozen dataclass: the limits travel from settings to the parent's checks (input size,
zip budget, wall clock) and into the child (rlimits, row / column caps) and must be the same
numbers on both sides. Validation lives here so a nonsensical value (zero, negative, a
memory cap below what Python itself needs) stops start-up instead of failing every job.

:func:`limits_enforceable` is the platform truth the production settings gate on. Memory and
CPU limits are ``setrlimit`` calls, which exist only on POSIX and are only *meaningful* on
Linux (``RLIMIT_AS`` is not enforced on macOS). On Windows the sandbox still runs -- with a
wall-clock timeout, size caps and a process-tree kill -- but it reports
``limits_enforced=False`` and ``prod`` settings refuse to start (``settings/prod.py``).

The isolation fields (``child_uid``/``child_gid``, ``network_isolation``,
``isolation_acknowledged``) say *how* the child is separated from the worker and the network and
what the parent must see proven before it trusts a parse (:meth:`SandboxLimits.required_enforcement`).
The in-process socket shim is deliberately absent from that list: it is bypassable.

Standard library only (the child process imports this module and must not load Django).
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, fields
from typing import Any

KIB = 1024
MIB = 1024 * KIB
GIB = 1024 * MIB

# How far above the parent's wall limit the child's own alarm fires (the parent normally acts first).
ALARM_SLACK_SECONDS = 10
NETWORK_ISOLATION_MODES = ("", "unshare", "container", "none-acknowledged")
# Fields that are not "a positive number": a float, strings, optional ids, a zero-able cap.
_NOT_POSITIVE_INTS = frozenset(
    {
        "wall_seconds",
        "tmp_root",
        "process_headroom",
        "child_uid",
        "child_gid",
        "network_isolation",
        "isolation_acknowledged",
    }
)

# Names of the limits the child needs (a subset of the dataclass: the parent keeps the rest).
CHILD_FIELDS: tuple[str, ...] = (
    "cpu_seconds",
    "memory_bytes",
    "max_output_bytes",
    "max_rows",
    "max_columns",
    "max_open_files",
    "process_headroom",
)


def limits_enforceable(platform: str | None = None) -> bool:
    """Whether memory and CPU limits can really be enforced on this platform (Linux only)."""
    name = sys.platform if platform is None else platform
    if not name.startswith("linux"):
        return False
    try:
        import resource  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class SandboxLimits:
    """Every cap the sandbox applies; the defaults are deliberately conservative."""

    wall_seconds: float = 120.0
    cpu_seconds: int = 120
    memory_bytes: int = 4 * GIB
    max_input_bytes: int = 100 * MIB
    max_output_bytes: int = 512 * MIB
    max_rows: int = 10_000_000
    max_columns: int = 5_000
    max_response_bytes: int = 256 * KIB
    max_open_files: int = 256
    # How many more processes (threads count on Linux) the child's user may have than it
    # has now; 0 turns the RLIMIT_NPROC cap off (see guards.apply_resource_limits).
    process_headroom: int = 64
    max_archive_entries: int = 10_000
    max_decompressed_bytes: int = 1 * GIB
    max_compression_ratio: int = 200
    # Directory under which each job gets a private temp dir; "" = the system temp dir.
    tmp_root: str = ""
    # --- isolation (see ``uadas_api.sandbox.isolation`` and plans/phase-3-5-jobs.md) ---------
    # A dedicated uid/gid the child switches to (needs a worker that may switch identity). Both
    # or neither. Without them the child runs as the worker's own user, and 0700 directories and
    # a stripped environment separate nothing from it.
    child_uid: int | None = None
    child_gid: int | None = None
    # "" = try to unshare a network namespace, report the outcome, require nothing;
    # "unshare" = the same, but refuse a parse whose child could not isolate itself;
    # "container" = the deployment gives the worker no network (acknowledged, not measured);
    # "none-acknowledged" = the operator accepts the bypassable in-process shim only.
    network_isolation: str = ""
    # "" or "container": the operator states that the worker runs in a container (or a uid)
    # that separates it from other jobs and from the host, in place of ``child_uid``.
    isolation_acknowledged: str = ""

    def __post_init__(self) -> None:
        if self.wall_seconds <= 0:
            raise ValueError("wall_seconds must be positive")
        for field in fields(self):
            if field.name in _NOT_POSITIVE_INTS:
                continue
            if getattr(self, field.name) <= 0:
                raise ValueError(f"{field.name} must be positive")
        if self.process_headroom < 0:
            raise ValueError("process_headroom must not be negative")
        if self.memory_bytes < 256 * MIB:
            raise ValueError(
                "memory_bytes below 256 MiB cannot even import the readers"
            )
        if (self.child_uid is None) != (self.child_gid is None):
            raise ValueError("child_uid and child_gid must be set together")
        if self.child_uid is not None and not (
            0 < self.child_uid < 2**31 and 0 < (self.child_gid or 0) < 2**31
        ):
            raise ValueError("child_uid and child_gid must be positive (not root)")
        if self.network_isolation not in NETWORK_ISOLATION_MODES:
            raise ValueError("network_isolation is not a known mode")
        if self.isolation_acknowledged not in ("", "container"):
            raise ValueError("isolation_acknowledged must be empty or 'container'")

    @property
    def wall_alarm_seconds(self) -> int:
        """The child's own alarm: a little above the parent's wall limit (the parent acts first)."""
        return math.ceil(self.wall_seconds) + ALARM_SLACK_SECONDS

    @property
    def wants_network_namespace(self) -> bool:
        """Whether the child should try to unshare a network namespace."""
        return self.network_isolation in ("", "unshare")

    def required_enforcement(self) -> tuple[str, ...]:
        """The enforcement keys a child's reply must carry as ``True`` (on a Linux platform).

        The in-process socket shim (``network_guard``) is *not* in this list: it can be bypassed
        from Python in two lines, so counting it would be a claim the sandbox cannot keep.
        ``nproc`` is dropped for a root worker in a container that the operator acknowledges
        (the cgroup ``pids_limit`` is then the bound), or when the cap was switched off.
        """
        required = ["memory", "cpu", "fsize"]
        if self.process_headroom > 0 and self.isolation_acknowledged != "container":
            required.append("nproc")
        if self.network_isolation == "unshare":
            required.append("network_isolated")
        return tuple(required)

    def child_payload(self, parent_pid: int | None = None) -> dict[str, int]:
        """The limits the child applies to itself, as plain JSON numbers.

        ``parent_pid`` lets the child notice that its parent died before it armed
        ``PR_SET_PDEATHSIG`` (the race is closed by comparing ``getppid()`` with it).
        """
        payload = {name: int(getattr(self, name)) for name in CHILD_FIELDS}
        payload["wall_alarm_seconds"] = self.wall_alarm_seconds
        payload["isolate_network"] = int(self.wants_network_namespace)
        if parent_pid is not None:
            payload["parent_pid"] = int(parent_pid)
        return payload

    @classmethod
    def from_mapping(cls, config: dict[str, Any]) -> SandboxLimits:
        """Build from a settings mapping, ignoring keys that are not limits."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in config.items() if k in known})

    @classmethod
    def from_settings(cls) -> SandboxLimits:
        """Build from ``settings.UADAS_SANDBOX`` (imported lazily: parent side only)."""
        from django.conf import settings

        return cls.from_mapping(dict(settings.UADAS_SANDBOX))

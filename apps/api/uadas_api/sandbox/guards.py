# File: apps/api/uadas_api/sandbox/guards.py
"""Process-level guards the sandbox child puts on itself *before* it imports a single reader.

Why in the child and not as ``preexec_fn``: ``preexec_fn`` runs between ``fork`` and ``exec``
in a multi-threaded parent, which CPython documents as unsafe, and applying the limits after
the interpreter has started (but before any reader code is imported) means they bind exactly
the code that handles the untrusted file. The cost is that the child could in principle raise
a *soft* limit again; every limit here sets soft = hard, so a compromised parser cannot.

What is applied (Linux; each is reported back to the parent so "enforced" is a measured fact,
not an assumption -- the parent never trusts a default):

* ``RLIMIT_CORE = 0`` -- no core dump of a process that held a tenant's data.
* ``RLIMIT_AS`` -- address-space (memory) cap; allocations past it raise ``MemoryError``.
* ``RLIMIT_CPU`` -- CPU seconds; the soft limit sends SIGXCPU (default action: terminate), the
  hard limit five seconds later is SIGKILL.
* ``RLIMIT_FSIZE`` -- largest file the child may write (the output cap, plus slack); past it a
  write fails with ``EFBIG`` (CPython ignores SIGXFSZ).
* ``RLIMIT_NOFILE`` -- open descriptors.
* ``RLIMIT_NPROC`` -- *current tasks of this user* plus ``process_headroom``. The kernel counts
  every process and thread of the user, so an absolute number would be wrong on every host;
  the count read from ``/proc`` is exact on a dedicated sandbox uid and an under-estimate on
  a shared one (then forks -- and thread creation -- fail with ``EAGAIN``, which surfaces as
  ``resource_limit``: it fails closed). Not enforced for root, and reported as such.

Then, in this order (:func:`harden_process`, :func:`isolate_network`, :func:`install_network_block`):

* **Hardening** -- ``PR_SET_DUMPABLE=0`` (a sibling child of the same uid cannot read this
  process's ``/proc`` entries or ptrace it), ``PR_SET_NO_NEW_PRIVS``, ``PR_SET_PDEATHSIG=SIGKILL``
  (the kernel kills this process when the worker that started it dies, however it dies) and an
  own ``alarm`` a little above the parent's wall-clock limit. The parent's pid is passed in the
  request so a parent that died *before* the signal was armed is noticed too.
* **A network namespace** (:func:`isolate_network`): ``unshare(CLONE_NEWNET)`` -- with
  ``CLONE_NEWUSER`` when unprivileged -- leaving only a downed loopback, verified by listing the
  interfaces, and the capabilities of the new user namespace dropped. This is the one *real*
  network layer inside the process, and it is only reported when it was verified. Docker's
  default seccomp profile and an AppArmor-restricted host both refuse the call; the child then
  reports ``network_isolated=False`` and the operator must supply isolation from outside
  (``SANDBOX_NETWORK_ISOLATION=container``).
* **The shim** (:func:`install_network_block`): a Python-level block on creating internet
  sockets, resolving names and the ``_socket`` module, with every attempt remembered in
  :func:`violation_kind` even if the caller swallows the exception. It is *bypassable* (the raw
  ``_socket`` base class is reachable through ``socket.socket.__mro__``, and C code or a helper
  process such as Tesseract never goes through Python), so it is defence in depth that catches
  honest mistakes and noisy attacks, **not** enforcement, and the parent does not count it as
  such.

On Windows (and macOS, where ``RLIMIT_AS`` is not meaningful) the limits are not applied and
the report says ``False`` for each. Standard library only: the child imports this first.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Any

from uadas_api.sandbox.limits import MIB

_CPU_HARD_SLACK_SECONDS = 5
_FSIZE_SLACK = 1 * MIB
_VIOLATION: str | None = None

_PR_SET_PDEATHSIG = 1
_PR_SET_DUMPABLE = 4
_PR_SET_NO_NEW_PRIVS = 38
_LINUX_CAPABILITY_VERSION_3 = 0x20080522
# ``capset(2)`` has no glibc wrapper; the syscall number depends on the architecture.
_SYS_CAPSET = {
    "x86_64": 126,
    "aarch64": 91,
    "i686": 185,
    "armv7l": 185,
    "ppc64le": 184,
    "s390x": 185,
    "riscv64": 91,
}
_EXIT_PARENT_GONE = 113


class SandboxViolation(PermissionError):
    """The sandboxed code tried something the sandbox forbids (a network socket)."""


def violation_kind() -> str | None:
    """The first forbidden operation attempted in this process (``"socket"``, ``"connect"`` ...)."""
    return _VIOLATION


def _violate(kind: str) -> SandboxViolation:
    global _VIOLATION
    if _VIOLATION is None:
        _VIOLATION = kind
    return SandboxViolation(f"{kind} is not allowed in the sandbox")


def count_user_tasks() -> int:
    """Processes plus threads owned by the current real user, as visible in ``/proc``."""
    uid = os.getuid()
    total = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(
                f"/proc/{entry}/status", encoding="ascii", errors="replace"
            ) as handle:
                fields = {}
                for line in handle:
                    name, _, value = line.partition(":")
                    if name in {"Uid", "Threads"}:
                        fields[name] = value.split()
                        if len(fields) == 2:
                            break
            if int(fields["Uid"][0]) == uid:
                total += int(fields["Threads"][0])
        except (OSError, KeyError, IndexError, ValueError):
            continue  # the process exited between listing and reading
    return total


def _lower(resource: Any, name: str, value: int, hard_slack: int = 0) -> bool:
    """Set soft = hard = ``value`` (clamped to the existing hard limit) and read it back."""
    kind = getattr(resource, name, None)
    if kind is None:
        return False
    try:
        _, existing_hard = resource.getrlimit(kind)
        hard = value + hard_slack
        if existing_hard != resource.RLIM_INFINITY:
            hard = min(hard, existing_hard)
            value = min(value, hard)
        resource.setrlimit(kind, (value, hard))
        return bool(resource.getrlimit(kind) == (value, hard))
    except (ValueError, OSError):
        return False


def apply_resource_limits(limits: Mapping[str, int]) -> dict[str, bool]:
    """Apply the rlimits in ``limits`` to this process and report which actually took effect.

    The returned mapping has the keys ``core, memory, cpu, fsize, nofile, nproc``; each is
    ``True`` only if the limit was set *and read back* as set. Never raises: a limit that
    cannot be applied is reported ``False`` and the parent decides what that means.
    """
    report = dict.fromkeys(("core", "memory", "cpu", "fsize", "nofile", "nproc"), False)
    if not sys.platform.startswith("linux"):
        return report
    try:
        import resource
    except ImportError:
        return report
    report["core"] = _lower(resource, "RLIMIT_CORE", 0)
    report["memory"] = _lower(resource, "RLIMIT_AS", int(limits["memory_bytes"]))
    report["cpu"] = _lower(
        resource, "RLIMIT_CPU", int(limits["cpu_seconds"]), _CPU_HARD_SLACK_SECONDS
    )
    report["fsize"] = _lower(
        resource, "RLIMIT_FSIZE", int(limits["max_output_bytes"]) + _FSIZE_SLACK
    )
    report["nofile"] = _lower(resource, "RLIMIT_NOFILE", int(limits["max_open_files"]))
    headroom = int(limits.get("process_headroom", 0))
    # Root is exempt from RLIMIT_NPROC in the kernel, so claiming it applies would be a lie.
    if headroom > 0 and os.geteuid() != 0:
        try:
            ceiling = count_user_tasks() + headroom
        except OSError:
            ceiling = 0
        if ceiling:
            report["nproc"] = _lower(resource, "RLIMIT_NPROC", ceiling)
    return report


def _libc() -> Any:
    import ctypes

    return ctypes.CDLL(None, use_errno=True)


def harden_process(*, parent_pid: int | None, alarm_seconds: int) -> bool:
    """Make this process hard to reach and impossible to orphan; ``True`` only if all of it held.

    Non-dumpable and no-new-privileges (Linux ``prctl``), killed by the kernel when the process
    that started it dies (``PR_SET_PDEATHSIG``, with the pid check that closes the race of a
    parent that died first), and an own ``SIGALRM`` after ``alarm_seconds`` (the default action
    terminates, even a process stuck in native code). Not Linux: nothing is done and ``False``
    is returned -- the caller reports it, it does not pretend.
    """
    if not sys.platform.startswith("linux"):
        return False
    import signal

    try:
        libc = _libc()
        held = all(
            libc.prctl(option, value, 0, 0, 0) == 0
            for option, value in (
                (_PR_SET_DUMPABLE, 0),
                (_PR_SET_NO_NEW_PRIVS, 1),
                (_PR_SET_PDEATHSIG, int(signal.SIGKILL)),
            )
        )
    except (OSError, AttributeError):
        return False
    if parent_pid is not None and os.getppid() != parent_pid:
        os._exit(_EXIT_PARENT_GONE)  # the parent died before the signal was armed
    if alarm_seconds > 0:
        signal.alarm(int(alarm_seconds))
    else:
        held = False
    return bool(held)


def _drop_capabilities() -> bool:
    """Empty the effective, permitted and inheritable capability sets of this process."""
    import ctypes
    import platform

    number = _SYS_CAPSET.get(platform.machine())
    if number is None:
        return False

    class Header(ctypes.Structure):
        _fields_ = (("version", ctypes.c_uint32), ("pid", ctypes.c_int))

    class Data(ctypes.Structure):
        _fields_ = (
            ("effective", ctypes.c_uint32),
            ("permitted", ctypes.c_uint32),
            ("inheritable", ctypes.c_uint32),
        )

    header = Header(_LINUX_CAPABILITY_VERSION_3, 0)
    data = (Data * 2)()  # two 32-bit words: capabilities 0-31 and 32-63, all zero
    try:
        result = _libc().syscall(number, ctypes.byref(header), ctypes.byref(data))
    except (OSError, AttributeError):
        return False
    return bool(result == 0)


def _only_loopback() -> bool:
    import socket

    try:
        return {name for _, name in socket.if_nameindex()} <= {"lo"}
    except OSError:
        return False


def isolate_network() -> bool:
    """Move this process into a network namespace with no interface but loopback; verify it.

    ``unshare(CLONE_NEWNET)`` when the process has ``CAP_SYS_ADMIN``, else with
    ``CLONE_NEWUSER`` too (the usual unprivileged route; it needs unprivileged user namespaces,
    which Docker's default seccomp profile and AppArmor-restricted hosts refuse). The capabilities
    gained in a new user namespace are dropped at once. Returns ``True`` only if the namespace
    exists *and* the interface list shows nothing but loopback; every failure is ``False`` and
    leaves the process exactly as it was (a failed ``unshare`` changes nothing).

    Must run in a single-threaded process (``CLONE_NEWUSER`` requires it): the child calls it
    right after the rlimits, which count this user's tasks and so must come first (inside the
    new user namespace the uid is unmapped and the count would be wrong).
    """
    if not sys.platform.startswith("linux") or not hasattr(os, "unshare"):
        return False
    try:
        try:
            os.unshare(os.CLONE_NEWNET)
        except PermissionError:
            os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)
            _drop_capabilities()
    except OSError:
        return False
    return _only_loopback()


def install_network_block() -> None:
    """Forbid internet sockets and name resolution in this interpreter (see the module docs).

    Defence in depth, **bypassable** (``socket.socket.__mro__`` leads to the raw class), and
    therefore not counted as enforcement by the parent; the real layer is :func:`isolate_network`
    or the deployment's network policy.

    Must run before anything else imports ``socket`` and keeps a reference to the original
    class. Local (``AF_UNIX``) sockets and sockets built from an existing descriptor
    (``socketpair``) are left alone: the interpreter itself uses them.
    """
    import socket

    import _socket

    inet = {socket.AF_INET, socket.AF_INET6}

    def refuse(kind: str) -> Any:
        def blocked(*_args: Any, **_kwargs: Any) -> Any:
            raise _violate(kind)

        return blocked

    def make_guarded(base: type) -> type:
        def init(
            self: Any,
            family: int = -1,
            type: int = -1,
            proto: int = -1,
            fileno: Any = None,
        ) -> None:
            # family == -1 is "the default", AF_INET.
            if fileno is None and (family == -1 or family in inet):
                raise _violate("socket")
            base.__init__(self, family, type, proto, fileno)  # type: ignore[misc]

        namespace: dict[str, Any] = {"__init__": init}
        for method in (
            "connect",
            "connect_ex",
            "bind",
            "listen",
            "sendto",
            "sendmsg",
            "sendmsg_afalg",
        ):
            if hasattr(base, method):
                namespace[method] = refuse(method)
        return type(base.__name__, (base,), namespace)

    socket.socket = make_guarded(socket.socket)  # type: ignore[assignment,misc]
    _socket.socket = make_guarded(_socket.socket)  # type: ignore[assignment,misc]
    for name in (
        "create_connection",
        "create_server",
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
        "getnameinfo",
    ):
        setattr(socket, name, refuse(name))

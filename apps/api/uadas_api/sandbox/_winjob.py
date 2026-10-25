# File: apps/api/uadas_api/sandbox/_winjob.py
"""A Windows Job Object that kills a child and every descendant, even after the child exited.

Why: on POSIX the child leads its own process group and ``killpg`` reaches grandchildren
whether or not the child is still alive. Windows has no equivalent keyed on a group: once the
child has exited, ``taskkill /T`` can no longer find its descendants (the parent link is
gone), so a helper process it started would outlive the job. A job object has no such
blind spot -- membership is inherited by every process a member starts, and
``TerminateJobObject`` ends all of them. ``KILL_ON_JOB_CLOSE`` makes the kernel do the same if
this process itself dies.

Scope, stated plainly: this is *containment of the process tree* only. It deliberately does not
set memory or CPU limits, so the sandbox still reports ``limits_enforced=False`` on Windows
(production refuses to start there; see ``settings/prod.py``). A job object *can* carry
``JOB_OBJECT_LIMIT_PROCESS_MEMORY``; that is the natural next step if Windows ever has to be a
production platform.

The child is assigned right after it starts, so a grandchild forked in those first
microseconds could escape; ``taskkill /T`` in the runner is the fallback for that window.
Used only when ``os.name == "nt"``; the module imports ``ctypes.wintypes`` lazily.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class WindowsJob:
    """One job object. ``None`` from :meth:`create` means jobs are unavailable here."""

    def __init__(self, kernel32: Any, handle: Any) -> None:
        self._kernel32 = kernel32
        self._handle = handle

    @classmethod
    def create(cls) -> WindowsJob | None:
        """Create a kill-on-close job, or return ``None`` (not Windows, or the call failed)."""
        if sys.platform != "win32":
            return None
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = (
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            )

        class IoCounters(ctypes.Structure):
            _fields_ = tuple(
                (name, ctypes.c_uint64) for name in ("a", "b", "c", "d", "e", "f")
            )

        class ExtendedLimits(ctypes.Structure):
            _fields_ = (
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            )

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        info = ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            kernel32.CloseHandle(handle)
            return None
        return cls(kernel32, handle)

    def assign(self, pid: int) -> bool:
        """Put the process ``pid`` (and so everything it starts) into the job."""
        process = self._kernel32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid
        )
        if not process:
            return False
        try:
            return bool(self._kernel32.AssignProcessToJobObject(self._handle, process))
        finally:
            self._kernel32.CloseHandle(process)

    def terminate(self) -> None:
        """End every process in the job."""
        if self._handle:
            self._kernel32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        """Release the handle (kill-on-close also ends any survivor)."""
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

# File: apps/api/uadas_api/jobs/checks.py
"""System checks that keep the queue's safety settings from being weakened by an override.

Why checks on top of the settings parser: ``settings/_jobs.py`` builds a safe configuration,
but Django settings are plain Python -- a module that does ``CELERY_ACCEPT_CONTENT = [...,
"pickle"]`` after the star-import, or an ``override_settings`` in a test that outlives it,
would silently undo the invariant. These run with every ``manage.py check`` (errors) and with
``check --deploy`` (warnings), which CI runs against the production settings with
``--fail-level WARNING``.

* ``uadas_jobs.E001`` -- anything but JSON-only serialization (pickle is code execution).
* ``uadas_jobs.E002`` -- late acknowledgement and reject-on-worker-lost must both be on, or a
  worker that dies mid-job loses the job instead of getting it redelivered.
* ``uadas_jobs.E003`` -- the visibility timeout must exceed the hard time limit plus the longest
  retry backoff, or Redis redelivers a task that is still running.
* ``uadas_jobs.E004`` (deploy) -- the sandbox child cannot start in this installation (the usual
  cause: the packages were installed with ``pip install --user``, which ``python -I`` ignores).
* ``uadas_jobs.E005`` / ``E006`` / ``E007`` (deploy) -- a root worker with nothing separating the
  child from it; a dedicated child uid the worker cannot switch to; a demanded network
  namespace the host refuses (see :func:`check_sandbox_isolation`).
* ``uadas_jobs.W001`` (deploy) -- eager mode is on: jobs would run inside web requests.
* ``uadas_jobs.W002`` (deploy) -- the platform cannot enforce the sandbox's memory/CPU limits.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404
from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Error, Warning, register

from uadas_api.sandbox.isolation import can_switch_identity, probe_network_isolation
from uadas_api.sandbox.limits import limits_enforceable


def _setting(name: str, default: Any = None) -> Any:
    return getattr(settings, name, default)


@register()
def check_queue_is_json_only_and_late_acked(**kwargs: Any) -> list[CheckMessage]:
    """Errors for a queue configuration that is unsafe regardless of environment."""
    errors: list[CheckMessage] = []
    serializers = {
        "CELERY_TASK_SERIALIZER": _setting("CELERY_TASK_SERIALIZER", "json"),
        "CELERY_RESULT_SERIALIZER": _setting("CELERY_RESULT_SERIALIZER", "json"),
        "CELERY_EVENT_SERIALIZER": _setting("CELERY_EVENT_SERIALIZER", "json"),
    }
    accept = list(_setting("CELERY_ACCEPT_CONTENT", ["json"]))
    bad = [name for name, value in serializers.items() if value != "json"]
    if accept != ["json"] or bad:
        errors.append(
            Error(
                "The job queue must accept and produce JSON only.",
                hint="Set CELERY_ACCEPT_CONTENT=['json'] and every *_SERIALIZER to 'json'; "
                "a pickle message is arbitrary code execution for whoever can write to the broker.",
                id="uadas_jobs.E001",
            )
        )
    if not (
        _setting("CELERY_TASK_ACKS_LATE") is True
        and _setting("CELERY_TASK_REJECT_ON_WORKER_LOST") is True
    ):
        errors.append(
            Error(
                "CELERY_TASK_ACKS_LATE and CELERY_TASK_REJECT_ON_WORKER_LOST must both be True.",
                hint="Otherwise a worker that dies mid-job loses the job instead of "
                "having it redelivered (the database attempt counter bounds the redelivery).",
                id="uadas_jobs.E002",
            )
        )
    jobs = _setting("UADAS_JOBS", {})
    transport = _setting("CELERY_BROKER_TRANSPORT_OPTIONS", {}) or {}
    visibility = transport.get("visibility_timeout")
    hard = _setting("CELERY_TASK_TIME_LIMIT")
    backoff = jobs.get("retry_backoff_max", 0) if isinstance(jobs, dict) else 0
    if (
        visibility is not None
        and hard is not None
        and not jobs.get("eager", False)
        and visibility <= hard + backoff
    ):
        errors.append(
            Error(
                "The broker visibility timeout must exceed the hard time limit plus the "
                "longest retry backoff.",
                hint="Raise JOBS_VISIBILITY_TIMEOUT_SECONDS; Redis redelivers anything "
                "unacknowledged for that long, including a task that is still running.",
                id="uadas_jobs.E003",
            )
        )
    return errors


@register(deploy=True)
def check_sandbox_child_starts(**kwargs: Any) -> list[CheckMessage]:
    """``uadas_jobs.E004``: the sandbox child must be able to start in this installation.

    The child is ``python -I -m uadas_api.sandbox.child``; ``-I`` ignores ``PYTHONPATH``, the
    current directory *and the user site-packages*, so it finds ``uadas_api`` / ``uadas_core``
    only if they are installed in the interpreter's own site-packages (a virtualenv or the system
    prefix -- **not** ``pip install --user``). A deployment that got this wrong would pass every
    other check and fail every upload, so the check starts the child with a deliberately
    malformed request and expects its ``protocol_error`` reply: proof that it imports and answers.
    Cheap: only the stdlib-only guards and protocol are imported, no reader.
    """
    from uadas_api.sandbox.errors import SandboxErrorCode
    from uadas_api.sandbox.protocol import Failure, ProtocolError, decode_response
    from uadas_api.sandbox.runner import default_child_command

    hint = (
        "Install uadas-api and the core into the interpreter's own site-packages (a "
        "virtualenv or the system prefix), not with `pip install --user`: the child runs "
        "`python -I`, which ignores the user site-packages and PYTHONPATH."
    )
    try:
        # Fixed argv, no shell: the same command the runner uses.
        completed = subprocess.run(  # nosec B603
            default_child_command(),
            input=b"not a request",
            capture_output=True,
            timeout=60,
            check=False,
            env={
                "PATH": os.environ.get("PATH", ""),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            },
        )
        reply = decode_response(completed.stdout, max_rows=1, max_columns=1)
        started = (
            isinstance(reply, Failure) and reply.code is SandboxErrorCode.PROTOCOL_ERROR
        )
    except (OSError, subprocess.SubprocessError, ProtocolError):
        started = False
    if started:
        return []
    return [
        Error("The parser sandbox child cannot start.", hint=hint, id="uadas_jobs.E004")
    ]


@register(deploy=True)
def check_sandbox_isolation(**kwargs: Any) -> list[CheckMessage]:
    """``uadas_jobs.E005-E007``: what actually separates the parser child from the worker.

    * ``E005`` -- the worker runs as root with neither a dedicated child uid nor the operator's
      statement that a container separates things. The child would run as root: able to read
      anything the worker can, and exempt from ``RLIMIT_NPROC`` (so the fork-bomb cap silently
      does not exist).
    * ``E006`` -- ``SANDBOX_CHILD_UID`` is set but this process may not switch identity (it needs
      root, or ``CAP_SETUID``, ``CAP_SETGID`` and ``CAP_CHOWN``): every parse would fail.
    * ``E007`` -- ``SANDBOX_NETWORK_ISOLATION=unshare`` demands a network namespace and this host
      refuses one to a fresh child (Docker's default seccomp profile, an AppArmor-restricted host):
      every parse would be refused.
    """
    sandbox = _setting("UADAS_SANDBOX", {}) or {}
    uid, acknowledged = sandbox.get("child_uid"), sandbox.get("isolation_acknowledged")
    errors: list[CheckMessage] = []
    if (
        hasattr(os, "geteuid")
        and os.geteuid() == 0
        and uid is None
        and acknowledged != "container"
    ):
        errors.append(
            Error(
                "The worker runs as root and the parser child would too.",
                hint="Set SANDBOX_CHILD_UID and SANDBOX_CHILD_GID to a dedicated unprivileged "
                "user, or run the worker as one; or, if a container does the separating, set "
                "SANDBOX_ISOLATION_ACKNOWLEDGED=container.",
                id="uadas_jobs.E005",
            )
        )
    if uid is not None and not can_switch_identity():
        errors.append(
            Error(
                "SANDBOX_CHILD_UID is set but this process cannot switch to it.",
                hint="Run the worker as root, or grant it CAP_SETUID, CAP_SETGID and "
                "CAP_CHOWN (the job directory is handed to the child's uid).",
                id="uadas_jobs.E006",
            )
        )
    if sandbox.get("network_isolation") == "unshare" and not probe_network_isolation():
        errors.append(
            Error(
                "SANDBOX_NETWORK_ISOLATION=unshare but a fresh child cannot unshare a network "
                "namespace on this host.",
                hint="Allow unprivileged user namespaces for the worker (Docker's default "
                "seccomp profile and Ubuntu 24.04's AppArmor restriction both block them), or "
                "set SANDBOX_NETWORK_ISOLATION=container and give the worker no network.",
                id="uadas_jobs.E007",
            )
        )
    return errors


@register(deploy=True)
def check_deployment(**kwargs: Any) -> list[CheckMessage]:
    """Warnings that matter only for a deployment."""
    warnings: list[CheckMessage] = []
    jobs = _setting("UADAS_JOBS", {})
    if _setting("CELERY_TASK_ALWAYS_EAGER") or (
        isinstance(jobs, dict) and jobs.get("eager")
    ):
        warnings.append(
            Warning(
                "Jobs run eagerly (inline in the calling process).",
                hint="Unset JOBS_EAGER; production needs a worker and a broker.",
                id="uadas_jobs.W001",
            )
        )
    if not limits_enforceable():
        warnings.append(
            Warning(
                "The parser sandbox cannot enforce memory and CPU limits on this platform.",
                hint="Run the API and its workers on Linux.",
                id="uadas_jobs.W002",
            )
        )
    return warnings

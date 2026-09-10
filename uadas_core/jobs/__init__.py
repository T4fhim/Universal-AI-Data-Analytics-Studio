# File: uadas_core/jobs/__init__.py
"""Qt-free background-job execution — the headless replacement for ``QThreadPool``.

Web-transition Phase 1.2 lifts the *policy* of "run this callable off the
calling thread and deliver its outcome through callbacks" out of
:mod:`src.workers.base_worker` (which is welded to ``QThread``/``QRunnable``
and dies with the desktop shell in Phase 2) and into this package, where it
carries no GUI-toolkit dependency. The ``.importlinter`` contract forbids
anything under :mod:`uadas_core` — this package included — from importing
PySide6/PyQt/Django.

The subsystem is deliberately shaped like Phase 3's ``django.tasks``: a
:class:`~uadas_core.jobs.job_runner.JobRunner` protocol with an in-process
:class:`~uadas_core.jobs.thread_pool_executor_job_runner.ThreadPoolExecutorJobRunner`
implementation now, and room for a ``DjangoTasksJobRunner`` (running ``fn``
in another *process*, posting results back over HTTP) later without a
breaking change — which is why the contract is callback-based rather than
handing back an in-process ``Future``.

**The module-level default-runner registry below is a Phase-1.2-only
bridge.** :class:`~src.workers.base_worker.BaseWorker` must acquire a
:class:`~uadas_core.jobs.job_runner.JobRunner` without a change to its
public ``__init__`` signature (de-risking plan Control A10 forbids
touching it), so ``bootstrap()`` stashes the one runner here via
:func:`set_default_job_runner` and ``BaseWorker.run()`` reads it back via
:func:`get_default_job_runner`. The explicit
``container.register(JobRunner, ...)`` path in ``bootstrap()`` is the
real wiring; this global exists solely so the disposable desktop shell
can reach the runner too. It dies with ``BaseWorker`` in Phase 2. *(Note
for the 1.3 de-globalization pass: this is one deliberate, scoped module
global — see plans/phase-1-2-jobrunner-design.md section 3.)*
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from uadas_core.core.logger import get_logger

if TYPE_CHECKING:
    from uadas_core.jobs.job_runner import JobRunner

__all__ = ["get_default_job_runner", "set_default_job_runner"]

_logger = get_logger(__name__)

# Not an ``AppConfig``/container-held value: the whole reason it lives here
# is that BaseWorker cannot be handed one through its constructor without
# breaking Control A10. One process, one runner, set exactly once by
# bootstrap().
_default_job_runner: JobRunner | None = None


def set_default_job_runner(runner: JobRunner) -> None:
    """Install the process-wide default :class:`JobRunner`.

    Called once, by :func:`uadas_core.core.bootstrap.bootstrap`, right
    after it registers the same instance into the dependency container.
    Calling it again replaces the previous runner — harmless in
    production (bootstrap runs once) and convenient for tests that need
    to swap in a synchronous fake.
    """
    global _default_job_runner
    previous = _default_job_runner
    _default_job_runner = runner
    if previous is not None and previous is not runner:
        # Re-install (a second bootstrap() in one process, or a test swapping
        # the runner): tear down the old pool so its idle worker threads don't
        # leak for the life of the process (whole-branch diagnosis). A
        # synchronous fake has no shutdown() -- skip it; failure is non-fatal.
        _shutdown = getattr(previous, "shutdown", None)
        if callable(_shutdown):
            try:
                _shutdown(wait=False)
            except Exception:
                _logger.exception("Tearing down the previous default JobRunner failed.")


def get_default_job_runner() -> JobRunner:
    """Return the runner installed by :func:`set_default_job_runner`.

    Raises:
        RuntimeError: If no runner has been installed yet. This is a
            wiring bug, not an application-domain failure (nothing
            should catch it): it means something asked for the default
            runner before ``bootstrap()`` ran, or outside an application
            session entirely. Deliberately a plain ``RuntimeError`` and
            not an :class:`~uadas_core.core.exceptions.ApplicationError`
            subclass — see that module's docstring on not adding
            speculative subclasses, and CLAUDE.md's exception guidance.
    """
    if _default_job_runner is None:
        raise RuntimeError(
            "No default JobRunner has been installed. "
            "uadas_core.core.bootstrap.bootstrap() installs one via "
            "set_default_job_runner(); this call happened before bootstrap ran "
            "(or outside an application session)."
        )
    return _default_job_runner

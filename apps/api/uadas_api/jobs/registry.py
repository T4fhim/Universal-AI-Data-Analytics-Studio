# File: apps/api/uadas_api/jobs/registry.py
"""Which code runs for which kind of job, and the contract a handler fulfils.

Why a registry keyed by the closed :class:`~uadas_api.jobs.choices.JobKind`: a task message
carries only a job id, so the *kind* on the row decides what runs, and it must be a value this
codebase defined -- never a dotted path read from a message or a row (that would be remote code
execution for anyone who could write a row). Handlers are therefore named *here*, as strings
resolved with :func:`importlib.import_module` only for the members of ``JobKind``
(``tests/test_jobs_registry.py`` fails if a kind has no handler or a handler has no kind), and
imported lazily so this module -- and everything that creates jobs -- never loads the code
behind a kind (the ingest handler pulls in the sandbox runner and the storage layer).

A handler is two functions:

* ``validate_params(organization_id, params) -> dict`` -- run when the job is *created*; raises
  Django's ``ValidationError`` for anything malformed and returns the normalised parameters that
  are stored. Parameters are ids, storage keys and a display name, never data.
* ``run(context) -> Completion`` -- run in the worker. It does the slow work (checking
  :meth:`JobContext.check_cancelled` between steps) and returns a :class:`Completion`: the
  result to store, an optional ``commit`` callable to run **in the same transaction** that marks
  the job ``succeeded`` (so a row the job creates and the job's success state commit together
  or not at all), and an optional ``cleanup`` to run if that transaction fails or the job is
  found cancelled/lost after the work was done.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from uadas_api.accounts.permissions import Capability
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.progress import ProgressSink

if TYPE_CHECKING:
    from uadas_api.accounts.models import Organization, User
    from uadas_api.jobs.models import Job
    from uadas_api.workspaces.models import Project


@dataclass(frozen=True)
class JobContext:
    """What a running handler is given: the re-resolved rows and the progress sink.

    Everything here was loaded from the database *by the worker* from the job row's own
    organization and project; nothing was taken from the task message.
    """

    job: Job
    organization: Organization
    project: Project
    actor: User | None
    sink: ProgressSink

    @property
    def params(self) -> Mapping[str, Any]:
        """The validated parameters stored on the job."""
        return self.job.params

    def report(self, percent: int, message: str = "", *, force: bool = False) -> None:
        """Record progress and a heartbeat (throttled unless ``force``)."""
        self.sink.report(percent, message, force=force)

    def check_cancelled(self) -> None:
        """Checkpoint: raise if the job was cancelled or is no longer this worker's."""
        self.sink.check_cancelled()


@dataclass(frozen=True)
class Completion:
    """A handler's outcome. ``result`` is ids/keys/counts only -- never rows of data."""

    result: Mapping[str, Any]
    commit: Callable[[], None] | None = None
    cleanup: Callable[[], None] | None = None
    # ``None`` = the default 16 KiB ("ids and counts"). A handler whose result is a bounded, display-
    # formatted document (the 3.6 stage result sections) names its own, larger cap.
    max_result_bytes: int | None = None


@dataclass(frozen=True)
class JobHandler:
    """The two functions behind a kind, and the capability the creator must (still) hold."""

    # (organization_id, params) -> normalised params; the organization is passed so a handler
    # can check that every key and id in ``params`` belongs to it before a row exists.
    validate_params: Callable[[Any, Mapping[str, Any]], dict[str, Any]]
    run: Callable[[JobContext], Completion]
    capability: Capability = Capability.WRITE_DATA
    # Called (best effort, errors logged by class only) once a job ends failed or cancelled
    # *for good*: where a kind retires what it staged (the ingest handler queues the dataset's
    # stored objects for deletion when no dataset was ever created).
    on_abandon: Callable[[Job], None] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


# kind -> "module:attribute" of the JobHandler. The only place a kind is tied to code.
_HANDLER_PATHS: dict[str, str] = {
    JobKind.INGEST_DATASET.value: "uadas_api.ingest.service:HANDLER",
    JobKind.RUN_OPERATION.value: "uadas_api.stages.run:HANDLER",
    JobKind.BUILD_REPORT.value: "uadas_api.exports.service:HANDLER",
}

_overrides: dict[str, JobHandler] = {}


def registered_kinds() -> frozenset[str]:
    """The kinds that have a handler path (parity-tested against ``JobKind``)."""
    return frozenset(_HANDLER_PATHS)


def get_handler(kind: str) -> JobHandler:
    """Return the handler for ``kind``; an unknown kind is a :class:`KeyError`."""
    if kind in _overrides:
        return _overrides[kind]
    path = _HANDLER_PATHS[kind]  # KeyError for a kind that is not a JobKind
    module_name, _, attribute = path.partition(":")
    handler = getattr(importlib.import_module(module_name), attribute)
    if not isinstance(handler, JobHandler):
        raise TypeError(f"{path} is not a JobHandler")
    return handler


@contextmanager
def override_handler(kind: str, handler: JobHandler) -> Iterator[None]:
    """Use ``handler`` for ``kind`` inside the block (tests only)."""
    if kind not in _HANDLER_PATHS:
        raise KeyError(kind)
    previous = _overrides.get(kind)
    _overrides[kind] = handler
    try:
        yield
    finally:
        if previous is None:
            _overrides.pop(kind, None)
        else:
            _overrides[kind] = previous

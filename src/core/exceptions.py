# File: src/core/exceptions.py
"""Application-wide exception hierarchy.

Every custom exception raised anywhere in the application inherits,
directly or indirectly, from :class:`ApplicationError`. This gives
callers a single type to catch when they want to handle "any error
this application defines" without also swallowing unrelated errors
from third-party libraries or the standard library.

Subclasses exist because a caller somewhere needs to catch that
specific failure mode — not as speculative coverage for scenarios that
don't yet occur in the codebase. As later milestones add readers,
services, and UI code, new subclasses should be added to this file
(or to milestone-appropriate exceptions modules that themselves
inherit from :class:`ApplicationError`) rather than overloading the
generic subclasses defined here with unrelated meanings.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for all application-defined exceptions.

    Catching this type means "something went wrong that this
    application anticipated and gave a name to." It does not mean
    "something went wrong" in general — unexpected errors from
    third-party libraries or programming mistakes should propagate as
    their own exception types so they are not silently absorbed by a
    broad ``except ApplicationError`` handler.
    """


class ConfigError(ApplicationError):
    """Raised when configuration cannot be loaded, parsed, or validated.

    This covers a missing or unreadable config file that also fails to
    be recreated from defaults, a config file that parses but does not
    match the expected structure (missing keys, wrong types), and any
    attempt to read a configuration value that was never loaded.
    """


class ServiceError(ApplicationError):
    """Raised for failures within a registered service's own logic.

    This is distinct from :class:`DependencyResolutionError`, which
    covers failures to *locate or construct* a service in the first
    place. ``ServiceError`` covers a service that was successfully
    constructed but then failed to do what it was asked to do.
    Service-specific modules introduced in later milestones (for
    example a project service or workspace service) may define
    subclasses of this for failures specific to their own domain.
    """


class DependencyResolutionError(ApplicationError):
    """Raised when the dependency container cannot resolve a request.

    Covers two distinct situations, both surfaced through this single
    type since callers generally handle them the same way (the
    requested capability is unavailable):

    * A caller asked the container for a service key that was never
      registered.
    * A registered factory raised while constructing its instance.
    """


class ApplicationStateError(ApplicationError):
    """Raised for invalid access to or mutation of session state.

    For example, asking :class:`~src.core.application_state.
    ApplicationState` for the active dataset when no dataset has been
    set. This milestone has no dataset or visualization objects yet,
    so this exception currently guards only the state accessors that
    exist today; later milestones will raise it from the same
    accessors as those concepts are filled in, not from new exception
    types.
    """


class BootstrapError(ApplicationError):
    """Raised when application startup fails before it can run.

    This is reserved for failures in the bootstrap sequence itself
    (see :mod:`src.core.bootstrap`) that are not already covered by a
    more specific exception above — for instance, a startup step
    completing but returning a value in a shape a later step cannot
    use. Prefer raising the more specific exception (``ConfigError``,
    ``DependencyResolutionError``, etc.) at the point of failure where
    one applies; this type exists for genuine bootstrap-sequencing
    failures rather than as a catch-all.
    """


class ReaderError(ApplicationError):
    """Raised when a format-specific reader fails to read or parse a file.

    Distinct from :class:`ServiceError`: a reader failure is about a
    specific file's content being missing, unreadable, or malformed in
    a way the reader cannot recover from — not about a running
    service's own logic failing. This distinction matters because a
    caller may want to react differently (try a different reader,
    surface a line number to the user) to a reader failure than to a
    generic service failure, which this being its own type makes
    possible without inspecting the exception's message text to guess
    which case occurred.

    Introduced in milestone 2a; see
    :mod:`src.readers.base_reader` for the reader interface that
    raises this.
    """

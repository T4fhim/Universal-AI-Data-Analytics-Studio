# File: uadas_core/core/dependency_container.py
"""Central dependency container for service registration and resolution.

Services are registered against a key — conventionally a type, but any
hashable identifier works — together with a zero-argument factory
function that constructs an instance. Resolution is lazy: the factory
does not run until something actually requests that key, and (for
singleton registrations) only runs once, with the same instance
returned on every subsequent request.

This module intentionally does not know about any specific service
(settings, project, workspace, etc.) — those are registered into a
container instance by whatever milestone introduces them.
:mod:`uadas_core.bootstrap` owns the one container instance the
application actually uses.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar, overload

from uadas_core.core.exceptions import DependencyResolutionError
from uadas_core.core.logger import get_logger

_logger = get_logger(__name__)

T = TypeVar("T")

# A factory takes no arguments and returns a fully constructed
# instance of whatever it produces. Factories are expected to raise on
# their own failures; the container wraps those failures in
# DependencyResolutionError so callers have one exception type to
# catch regardless of which factory failed or why.
_Factory = Callable[[], T]


class DependencyContainer:
    """Registers service factories and resolves instances on request.

    Two registration modes are supported:

    * **Singleton** (the default): the factory runs once, on first
      resolution, and the same instance is returned for every
      subsequent request of that key. Use this for services that hold
      shared state or are expensive to construct — which, in this
      application, is expected to be the common case (settings,
      project, and workspace services are all naturally singletons
      within a running session).
    * **Transient**: the factory runs on every resolution, producing a
      new instance each time. Use this for lightweight objects where
      sharing an instance would be incorrect (for example, if a later
      milestone needs a fresh, independent object per call site).

    Registration and resolution are independent of *when* a key is
    registered relative to when it is resolved, as long as
    registration happens before the first resolution — there is no
    requirement to register every service up front before any
    resolution occurs.

    **Scoping (Phase 3 core session seam).** A container may be given a
    ``parent``. A child resolves its *own* registrations first and falls
    back to the parent (and, transitively, the parent's parent); anything
    registered in a child stays in that child — it never leaks to the
    parent or to a sibling. That is the whole mechanism by which one
    process serves many tenants: the process-wide, tenant-free services
    live in one parent container and each session gets a child holding the
    stateful per-user services (see :func:`uadas_core.bootstrap.build_session`).
    This replaced the earlier ``(session, type)`` composite-key idea: a
    child container needs no new key type, keeps ``resolve(Type) -> Type``
    sound, and a session that is dropped takes its services with it.
    A singleton registered in the *parent* is constructed once and shared by
    every child; a singleton registered in a *child* is per-child.

    Construction of a singleton is guarded by a per-container re-entrant lock
    so concurrent first resolutions (several request threads resolving one
    parent service at once) build it exactly once. :meth:`resolve` releases a
    container's own lock *before* delegating to its parent, so the only way two
    container locks are ever held together is a child's factory resolving a
    parent key from inside its (held) construction -- child then parent. A parent
    factory never resolves a child key, so the order cannot invert and cannot
    deadlock.

    A key is conventionally a service *type*, and :meth:`resolve` is
    typed for that case (``resolve(SettingsService) -> SettingsService``).
    Any hashable value is still accepted, and that non-type path stays
    available for keys that are not types.

    Two honesty caveats on that typing. First, :meth:`register` does not
    correlate a key with its factory's return type — ``register(X, ...)``
    accepts a factory returning anything, so ``resolve(X) -> X`` is a
    trusted *convention*, not a checked guarantee; a mismatched
    registration is caught by review, not by the type checker. Second,
    the typed overload's parameter is ``type[T]``, which mypy treats as
    instantiable, so resolving by a :class:`~typing.Protocol` or abstract
    class as key trips ``type-abstract`` at the call site and needs a
    ``cast(type[Thing], Thing)`` there. The one such key today is
    :class:`~uadas_core.jobs.job_runner.JobRunner` (a ``Protocol``); its
    only ``resolve()`` sites are in tests, which are outside CI's mypy
    scope, so this stays latent until an in-scope module resolves it.
    Closing both gaps (a symmetric typed :meth:`register` overload; a
    ``ServiceKey[T]`` token that makes ``resolve`` sound rather than
    trusting) is deferred — the first is coupled to picking a sanctioned
    protocol-key pattern, the second belongs with the Phase-3 scoping
    work.
    """

    def __init__(self, parent: DependencyContainer | None = None) -> None:
        """Create a container, optionally scoped beneath ``parent``.

        Args:
            parent: A container to fall back to for keys this one has not
                registered. ``None`` (the default) is the original,
                unscoped behaviour: a missing key raises
                :class:`~uadas_core.core.exceptions.DependencyResolutionError`.
        """
        self._parent = parent
        self._factories: dict[object, _Factory] = {}
        self._singletons: dict[object, bool] = {}
        self._instances: dict[object, object] = {}
        # Re-entrant: a factory may resolve another key of the same container.
        self._lock = threading.RLock()

    @property
    def parent(self) -> DependencyContainer | None:
        """The container this one falls back to, or ``None`` for a root."""
        return self._parent

    def register(
        self,
        key: object,
        factory: _Factory,
        *,
        singleton: bool = True,
    ) -> None:
        """Register a factory for ``key``.

        Args:
            key: Identifier services will be resolved by. Conventionally
                the service's type (e.g. ``SettingsService``), but any
                hashable value is accepted.
            factory: Zero-argument callable that constructs and returns
                an instance. Any arguments the factory needs (for
                example, another service it depends on) should be
                captured in a closure or ``functools.partial`` at
                registration time, so that :meth:`resolve` itself never
                needs to know a factory's dependencies.
            singleton: If ``True`` (the default), the factory runs at
                most once and the result is cached. If ``False``, the
                factory runs on every :meth:`resolve` call for this
                key.

        Registering the same key twice replaces the previous
        registration and clears any cached singleton instance for that
        key, so re-registration behaves as "start fresh" rather than
        silently keeping a stale cached instance around under new
        factory logic.
        """
        with self._lock:
            self._factories[key] = factory
            self._singletons[key] = singleton
            self._instances.pop(key, None)
        _logger.debug("Registered %s (singleton=%s)", _describe_key(key), singleton)

    @overload
    def resolve(self, key: type[T]) -> T: ...

    @overload
    def resolve(self, key: object) -> Any: ...

    def resolve(self, key: object) -> Any:
        """Resolve and return an instance for ``key``.

        For singleton registrations, returns the cached instance if
        one already exists, constructing it via the registered factory
        on first request. For transient registrations, always
        constructs a new instance.

        Args:
            key: The identifier a service was registered under.
                Passing a **type** (the conventional case) is typed:
                ``resolve(SettingsService)`` is statically known to
                return a ``SettingsService``, so call sites do not need
                a ``cast``. Passing any other hashable key falls back
                to the second overload and returns
                :data:`~typing.Any` — the runtime behaviour is
                identical either way; only what the type checker infers
                differs.

        Raises:
            DependencyResolutionError: If ``key`` was never registered
                here or in any ancestor container, or if the registered
                factory raises during construction.
        """
        with self._lock:
            if key in self._factories:
                return self._resolve_own(key)

        if self._parent is not None:
            # Own registrations were checked first above; only an
            # unregistered key reaches the parent, whose own resolve()
            # raises the "No service registered" error if it is missing too.
            return self._parent.resolve(key)

        raise DependencyResolutionError(
            f"No service registered for key: {_describe_key(key)}. "
            f"Register it with DependencyContainer.register(...) "
            f"before requesting it."
        )

    def _resolve_own(self, key: object) -> Any:
        """Resolve ``key`` from this container's own registrations (lock held)."""
        is_singleton = self._singletons[key]

        if is_singleton and key in self._instances:
            return self._instances[key]

        factory = self._factories[key]
        try:
            instance = factory()
        except DependencyResolutionError:
            raise
        except Exception as exc:
            raise DependencyResolutionError(
                f"Factory for {_describe_key(key)} raised during construction: {exc}"
            ) from exc

        if is_singleton:
            self._instances[key] = instance
            _logger.debug("Constructed and cached singleton %s", _describe_key(key))
        else:
            _logger.debug("Constructed transient instance of %s", _describe_key(key))

        return instance

    def is_registered(self, key: object) -> bool:
        """Return whether ``key`` has a registered factory here or in an ancestor.

        Useful for optional dependencies, where a caller wants to use
        a service only if some earlier startup step chose to register
        it, without triggering :class:`DependencyResolutionError` for
        the common "not registered" case. A child container reports its
        parents' registrations too, since :meth:`resolve` would find them.
        """
        if key in self._factories:
            return True
        return self._parent is not None and self._parent.is_registered(key)


def _describe_key(key: object) -> str:
    """Return a human-readable description of a registration key.

    Types (the conventional key) render as their name; anything else
    renders via ``repr`` so error messages stay useful regardless of
    what a caller chooses to key on.
    """
    if isinstance(key, type):
        return key.__name__
    return repr(key)

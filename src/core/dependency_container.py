# File: src/core/dependency_container.py
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
:mod:`src.core.bootstrap` owns the one container instance the
application actually uses.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from src.core.exceptions import DependencyResolutionError
from src.core.logger import get_logger

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
    """

    def __init__(self) -> None:
        self._factories: dict[object, _Factory] = {}
        self._singletons: dict[object, bool] = {}
        self._instances: dict[object, object] = {}

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
        self._factories[key] = factory
        self._singletons[key] = singleton
        self._instances.pop(key, None)
        _logger.debug("Registered %s (singleton=%s)", _describe_key(key), singleton)

    def resolve(self, key: object) -> object:
        """Resolve and return an instance for ``key``.

        For singleton registrations, returns the cached instance if
        one already exists, constructing it via the registered factory
        on first request. For transient registrations, always
        constructs a new instance.

        Args:
            key: The identifier a service was registered under.

        Raises:
            DependencyResolutionError: If ``key`` was never registered,
                or if the registered factory raises during
                construction.
        """
        if key not in self._factories:
            raise DependencyResolutionError(
                f"No service registered for key: {_describe_key(key)}. "
                f"Register it with DependencyContainer.register(...) "
                f"before requesting it."
            )

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
                f"Factory for {_describe_key(key)} raised during "
                f"construction: {exc}"
            ) from exc

        if is_singleton:
            self._instances[key] = instance
            _logger.debug("Constructed and cached singleton %s", _describe_key(key))
        else:
            _logger.debug("Constructed transient instance of %s", _describe_key(key))

        return instance

    def is_registered(self, key: object) -> bool:
        """Return whether ``key`` has a registered factory.

        Useful for optional dependencies, where a caller wants to use
        a service only if some earlier startup step chose to register
        it, without triggering :class:`DependencyResolutionError` for
        the common "not registered" case.
        """
        return key in self._factories


def _describe_key(key: object) -> str:
    """Return a human-readable description of a registration key.

    Types (the conventional key) render as their name; anything else
    renders via ``repr`` so error messages stay useful regardless of
    what a caller chooses to key on.
    """
    if isinstance(key, type):
        return key.__name__
    return repr(key)

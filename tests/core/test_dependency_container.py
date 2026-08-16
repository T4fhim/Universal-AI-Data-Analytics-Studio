# File: tests/core/test_dependency_container.py
"""Tests for src.core.dependency_container.DependencyContainer.

Covers the registration/resolution contract documented in
dependency_container.py's own module and class docstrings: singleton
caching, transient re-construction, the unregistered-key error, and
re-registration clearing a previously cached singleton instance.
"""

from __future__ import annotations

import pytest

from src.core.dependency_container import DependencyContainer
from src.core.exceptions import DependencyResolutionError


class _Widget:
    """Trivial marker class used as both a registration key and a payload."""


def test_singleton_returns_same_instance_on_repeated_resolve() -> None:
    container = DependencyContainer()
    container.register(_Widget, lambda: _Widget(), singleton=True)

    first = container.resolve(_Widget)
    second = container.resolve(_Widget)

    assert first is second


def test_transient_returns_new_instance_per_resolve() -> None:
    container = DependencyContainer()
    container.register(_Widget, lambda: _Widget(), singleton=False)

    first = container.resolve(_Widget)
    second = container.resolve(_Widget)

    assert first is not second


def test_resolve_unregistered_key_raises_dependency_resolution_error() -> None:
    container = DependencyContainer()

    with pytest.raises(DependencyResolutionError):
        container.resolve(_Widget)


def test_factory_exception_is_wrapped_in_dependency_resolution_error() -> None:
    container = DependencyContainer()

    def _failing_factory() -> _Widget:
        raise ValueError("boom")

    container.register(_Widget, _failing_factory)

    with pytest.raises(DependencyResolutionError):
        container.resolve(_Widget)


def test_reregistration_clears_previously_cached_singleton() -> None:
    container = DependencyContainer()
    container.register(_Widget, lambda: _Widget(), singleton=True)
    first = container.resolve(_Widget)

    # Re-registering under the same key must start fresh, not keep the
    # first factory's cached instance around under the new factory.
    container.register(_Widget, lambda: _Widget(), singleton=True)
    second = container.resolve(_Widget)

    assert first is not second


def test_is_registered_reflects_registration_state() -> None:
    container = DependencyContainer()

    assert container.is_registered(_Widget) is False

    container.register(_Widget, lambda: _Widget())

    assert container.is_registered(_Widget) is True

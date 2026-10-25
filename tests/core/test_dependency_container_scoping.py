# File: tests/core/test_dependency_container_scoping.py
"""Tests for ``DependencyContainer(parent=...)`` -- the session-scoping seam.

A child resolves its own registrations first and falls back to its parent; nothing a
child registers is ever visible to the parent or to a sibling. Every reject-style
assertion has a positive twin in the same test so it cannot pass for the wrong
reason (a container that simply resolved nothing would satisfy "does not leak").
"""

from __future__ import annotations

import threading
import time

import pytest

from uadas_core.core.dependency_container import DependencyContainer
from uadas_core.core.exceptions import DependencyResolutionError


class _Service:
    pass


class _Shared:
    pass


def test_child_resolves_its_own_registration_and_falls_back_to_the_parent() -> None:
    parent = DependencyContainer()
    parent_service = _Service()
    parent.register(_Service, lambda: parent_service)
    child = DependencyContainer(parent=parent)
    child.register(str, lambda: "own")

    assert child.resolve(str) == "own"  # own registration
    assert child.resolve(_Service) is parent_service  # fallback to the parent


def test_child_registration_wins_over_the_parent_without_touching_it() -> None:
    parent = DependencyContainer()
    parent_service = _Service()
    parent.register(_Service, lambda: parent_service)
    child = DependencyContainer(parent=parent)
    child_service = _Service()
    child.register(_Service, lambda: child_service)

    assert child.resolve(_Service) is child_service
    assert parent.resolve(_Service) is parent_service


def test_child_registration_does_not_leak_to_parent_or_siblings() -> None:
    parent = DependencyContainer()
    first = DependencyContainer(parent=parent)
    second = DependencyContainer(parent=parent)
    first.register(_Service, _Service)

    assert isinstance(first.resolve(_Service), _Service)  # positive twin
    assert not parent.is_registered(_Service)
    assert not second.is_registered(_Service)
    with pytest.raises(DependencyResolutionError):
        parent.resolve(_Service)
    with pytest.raises(DependencyResolutionError):
        second.resolve(_Service)


def test_sibling_singletons_are_distinct_but_parent_singletons_are_shared() -> None:
    parent = DependencyContainer()
    parent.register(_Shared, _Shared, singleton=True)  # shared, constructed once
    first = DependencyContainer(parent=parent)
    second = DependencyContainer(parent=parent)
    first.register(_Service, _Service)
    second.register(_Service, _Service)

    assert first.resolve(_Service) is first.resolve(_Service)
    assert first.resolve(_Service) is not second.resolve(_Service)
    assert first.resolve(_Shared) is second.resolve(_Shared) is parent.resolve(_Shared)


def test_transient_parent_registration_stays_transient_through_a_child() -> None:
    parent = DependencyContainer()
    parent.register(_Service, _Service, singleton=False)
    child = DependencyContainer(parent=parent)

    assert child.resolve(_Service) is not child.resolve(_Service)


def test_is_registered_consults_the_parent_chain_but_not_children() -> None:
    root = DependencyContainer()
    middle = DependencyContainer(parent=root)
    leaf = DependencyContainer(parent=middle)
    root.register("a", lambda: 1)
    middle.register("b", lambda: 2)

    assert leaf.is_registered("a") and leaf.is_registered("b")
    assert leaf.resolve("a") == 1 and leaf.resolve("b") == 2
    assert not root.is_registered("b")
    assert not leaf.is_registered("c")


def test_missing_key_through_a_child_raises_the_same_error_type() -> None:
    child = DependencyContainer(parent=DependencyContainer())

    with pytest.raises(DependencyResolutionError, match="No service registered"):
        child.resolve(_Service)


def test_parent_factory_failure_is_wrapped_once_when_resolved_via_a_child() -> None:
    parent = DependencyContainer()

    def boom() -> _Service:
        raise ValueError("kaput")

    parent.register(_Service, boom)
    child = DependencyContainer(parent=parent)

    with pytest.raises(DependencyResolutionError, match="kaput") as excinfo:
        child.resolve(_Service)
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_parent_is_exposed_and_defaults_to_none() -> None:
    parent = DependencyContainer()

    assert parent.parent is None
    assert DependencyContainer(parent=parent).parent is parent


def test_concurrent_resolution_of_a_parent_singleton_constructs_it_once() -> None:
    parent = DependencyContainer()
    constructed: list[_Service] = []

    def slow_factory() -> _Service:
        time.sleep(0.02)  # widen the check-then-construct race window
        service = _Service()
        constructed.append(service)
        return service

    parent.register(_Service, slow_factory)
    children = [DependencyContainer(parent=parent) for _ in range(8)]
    results: list[object] = []
    barrier = threading.Barrier(len(children))

    def work(container: DependencyContainer) -> None:
        barrier.wait()
        results.append(container.resolve(_Service))

    threads = [threading.Thread(target=work, args=(c,)) for c in children]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(constructed) == 1
    assert len(results) == len(children)
    assert all(result is constructed[0] for result in results)

# File: tests/core/test_process_mode.py
"""The one-way process mode latch: a process is desktop or server, never both.

Server mode's guarantees (no plugins, no YAML, no log files, no global runner bridge)
are only worth anything if a *later* call cannot quietly undo them, and a desktop
process that later starts "server mode" would inherit its file-logging handler and
loaded plugins. So the first :func:`bootstrap_process` claims the mode and a conflicting
second claim raises, in both orders. Same-mode repeats stay legal (the desktop test
suite and the legacy single-user app both bootstrap more than once). Every reject test
has its positive twin beside it.
"""

from __future__ import annotations

import threading

import pytest

from uadas_core.bootstrap import bootstrap, bootstrap_process, build_session
from uadas_core.core.exceptions import BootstrapError
from uadas_core.core.process_mode import (
    ProcessMode,
    claim_process_mode,
    current_process_mode,
    reset_process_mode_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_latch():
    reset_process_mode_for_tests()
    yield
    reset_process_mode_for_tests()


def test_first_claim_wins_and_the_same_mode_may_be_claimed_again() -> None:
    assert current_process_mode() is None

    claim_process_mode(ProcessMode.SERVER)
    claim_process_mode(ProcessMode.SERVER)  # positive twin: repeat is fine

    assert current_process_mode() is ProcessMode.SERVER


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (ProcessMode.SERVER, ProcessMode.DESKTOP),
        (ProcessMode.DESKTOP, ProcessMode.SERVER),
    ],
)
def test_a_conflicting_claim_raises_in_both_orders_and_names_the_conflict(
    first: ProcessMode, second: ProcessMode
) -> None:
    claim_process_mode(first)

    with pytest.raises(BootstrapError) as excinfo:
        claim_process_mode(second)

    message = str(excinfo.value)
    assert first.value in message and second.value in message
    assert current_process_mode() is first  # the failed claim changed nothing


def test_the_test_only_reset_reopens_the_latch() -> None:
    claim_process_mode(ProcessMode.SERVER)

    reset_process_mode_for_tests()

    claim_process_mode(ProcessMode.DESKTOP)  # now legal
    assert current_process_mode() is ProcessMode.DESKTOP


def test_concurrent_conflicting_claims_have_exactly_one_winner() -> None:
    modes = [ProcessMode.SERVER, ProcessMode.DESKTOP] * 8
    barrier = threading.Barrier(len(modes))
    outcomes: list[tuple[ProcessMode, bool]] = []

    def work(mode: ProcessMode) -> None:
        barrier.wait(timeout=30)
        try:
            claim_process_mode(mode)
            outcomes.append((mode, True))
        except BootstrapError:
            outcomes.append((mode, False))

    threads = [threading.Thread(target=work, args=(m,)) for m in modes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    winner = current_process_mode()
    assert winner is not None
    assert {mode for mode, ok in outcomes if ok} == {winner}
    assert all(ok for mode, ok in outcomes if mode is winner)
    assert not any(ok for mode, ok in outcomes if mode is not winner)


# --- wired into bootstrap -------------------------------------------------------------


def test_server_then_desktop_is_refused_by_both_desktop_entry_points(
    config_path, log_dir, reset_logging_state
) -> None:
    server = bootstrap_process(server_mode=True)
    try:
        with pytest.raises(BootstrapError, match="server"):
            bootstrap_process(config_path=config_path, log_dir=log_dir)
        with pytest.raises(BootstrapError, match="server"):
            bootstrap(config_path=config_path, log_dir=log_dir)
        assert not config_path.exists() and not log_dir.exists()  # refused before I/O
        build_session(server)  # positive twin: the server process is still usable
        bootstrap_process(server_mode=True).close()  # and same-mode repeat is legal
    finally:
        server.close()


def test_desktop_then_server_is_refused_and_leaves_desktop_logging_alone(
    config_path, log_dir, reset_logging_state
) -> None:
    desktop = bootstrap_process(config_path=config_path, log_dir=log_dir)
    try:
        with pytest.raises(BootstrapError, match="desktop"):
            bootstrap_process(server_mode=True)
        bootstrap_process(config_path=config_path, log_dir=log_dir).close()  # twin
    finally:
        desktop.close()

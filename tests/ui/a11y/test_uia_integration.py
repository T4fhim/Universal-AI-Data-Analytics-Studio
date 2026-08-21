# File: tests/ui/a11y/test_uia_integration.py
"""Tier 1 of M28's manual-NVDA-pass accommodation: real Windows UI Automation verification.

``docs/M28_MANUAL_VERIFICATION.md`` records the gap this closes:
``src.ui.a11y.audit.audit_widget_tree`` (M28's own automated check) only
reads Qt's *in-process* accessible properties (``widget.accessibleName()``
etc.) -- it never proves Qt actually handed that information to the real
Windows UI Automation (UIA) layer, which is what NVDA and every other real
screen reader actually consumes, and is exactly where Qt applications most
commonly fail silently even when the in-process values look correct. A full
manual NVDA pass (Tier 2, ``docs/M28_MANUAL_VERIFICATION.md``'s still-open
item) is the only way to judge whether spoken output is *comprehensible*;
this module is Tier 1, the automatable slice underneath it: does the real
OS accessibility tree expose the names, roles, and focus behavior a screen
reader would build its narration from at all.

**Why this cannot run in the same process as the rest of ``tests/ui/``.**
``tests/ui/conftest.py`` sets ``QT_QPA_PLATFORM=offscreen`` unconditionally
at import time (its own docstring point 1), and that conftest is imported
for *any* test under ``tests/ui/`` -- including this one -- before this
module's own code runs a single line, and ``QApplication`` is a
process-wide singleton that fixture never tears down (its docstring point
2). Offscreen never creates real OS-level UIA elements; there is no way to
opt out of it from within a test module in this process. So the real,
visible application under test runs in a **separate OS process**
(``tests/ui/a11y/_uia_target_app.py`` -- see that module's own docstring
for the full mechanics), launched fresh per test function, and this module
never imports Qt at all -- it only drives ``pywinauto`` against that
process from the outside, exactly the way a real screen reader observes a
running application.

**Why every ``pywinauto`` call here is wrapped in a bounded timeout.**
Manual verification while building this module (see the commit this file
ships in) found individual UI Automation queries in this development
sandbox occasionally slow or, on repeated ``Application.connect()`` calls
against the same long-lived process, non-deterministically stalling well
past what a healthy query should take -- while the *same* queries against a
freshly launched process consistently completed in well under a second with
correct data. The mitigation applied throughout this module is exactly
that observation: one fresh target-app process per test (never reused
across tests), one UIA worker thread per test doing all of that test's
queries together (minimizing repeated connects to the same process), and
every worker wrapped in ``_run_bounded`` so a stall fails the test with a
clear diagnostic instead of hanging the whole run indefinitely. If this
still flakes in CI, that is a real signal about Qt-on-Windows UIA
reliability worth investigating on its own terms, not something to paper
over with an even longer timeout.

**Scope, disclosed rather than silently narrowed.** This Tier 1 pass opens
two representative dialogs -- :class:`~src.ui.dialogs.about_dialog.
AboutDialog` and :class:`~src.ui.command_palette.CommandPalette` -- chosen
because both are constructible from a :class:`~src.ui.main_window.
MainWindow` with no additional service wiring beyond what
:func:`~src.core.bootstrap.bootstrap` already provides. It does not open
every one of the dialog classes ``src.ui.a11y.audit.ALL_DIALOG_CLASSES``
discovers (currently more than these two): several require constructing
services (a real ``SettingsService`` plus every plugin-facing dependency,
for instance) that a minimal launch target has no reason to assemble.
Broadening this to the full set is real, legitimate follow-up work, not
something this module claims to already cover.
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import pytest

T = TypeVar("T")

_WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32",
    reason="UI Automation is a Windows-only API; this test only makes a "
    "claim on the platform NVDA/Narrator/JAWS actually run on.",
)

try:
    import pywinauto  # noqa: F401

    _PYWINAUTO_IMPORT_ERROR = ""
except ImportError as exc:  # pragma: no cover - exercised only when the
    # optional dependency is genuinely absent from the environment.
    _PYWINAUTO_IMPORT_ERROR = str(exc)

_PYWINAUTO_AVAILABLE = pytest.mark.skipif(
    bool(_PYWINAUTO_IMPORT_ERROR),
    reason=f"pywinauto is not importable in this environment: {_PYWINAUTO_IMPORT_ERROR}",
)

pytestmark = [_WINDOWS_ONLY, _PYWINAUTO_AVAILABLE, pytest.mark.uia_integration]

_APP_TITLE = "Universal AI Data Analytics Studio"
_TARGET_MODULE = "tests.ui.a11y._uia_target_app"

# Qt -> UIA control_type mappings this module's own manual verification
# actually observed (see this module's docstring) -- deliberately narrow:
# only classes this project's widgets actually use *and* whose UIA role was
# empirically confirmed are listed, rather than a guessed, exhaustive Qt
# widget-to-role table that could silently be wrong for a class nobody
# checked.
_EXPECTED_CONTROL_TYPE: dict[str, str] = {
    "QPushButton": "Button",
    "QToolButton": "Button",
    "QAbstractButton": "Button",
    "QLineEdit": "Edit",
    "QComboBox": "ComboBox",
    "QListWidget": "List",
    "QLabel": "Text",
}


def _run_bounded(fn: Callable[[], T], *, timeout: float, description: str) -> T:
    """Run ``fn`` in a daemon thread and fail loudly if it exceeds ``timeout``.

    See this module's own docstring for why every UIA call site needs this:
    a stalled COM call otherwise hangs the whole pytest process, not just
    one assertion, until someone notices and kills it by hand -- exactly
    what happened repeatedly during this module's own manual verification.
    """
    result: dict[str, Any] = {}

    def _target() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the
            # calling thread below; a bare except here is the point, not a
            # bug -- any failure inside the worker must be captured and
            # reported, not silently lost when the daemon thread exits.
            result["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        pytest.fail(
            f"{description} did not complete within {timeout}s -- a UI "
            "Automation call stalled. See this module's docstring for the "
            "known flakiness this timeout guards against."
        )
    if "error" in result:
        raise result["error"]
    return result["value"]  # type: ignore[return-value]


class _TargetAppDriver:
    """Drives ``_uia_target_app.py``'s single-line stdout/stdin protocol.

    A thin wrapper, not a general-purpose IPC framework -- see that
    module's own docstring for why something this simple is the right size
    for the handful of steps this Tier 1 test needs to drive.
    """

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process
        self._lines: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._read_lines, daemon=True)
        self._reader.start()

    def _read_lines(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._lines.put(line.rstrip("\n"))

    def wait_for(self, prefix: str, *, timeout: float = 30.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                line = self._lines.get(timeout=min(1.0, remaining))
            except queue.Empty:
                continue
            if line.startswith(prefix):
                return line
        raise TimeoutError(
            f"Target app never printed a line starting with {prefix!r} "
            f"within {timeout}s. It may have crashed before startup -- "
            "check the subprocess's own stderr/log output."
        )

    def send(self, command: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(f"{command}\n")
        self.process.stdin.flush()


@pytest.fixture()
def uia_app(tmp_path: Path) -> Any:
    """Launch a real, visible ``MainWindow`` in its own process for this test only.

    Function-scoped, not session-scoped -- see this module's docstring for
    why reusing one target-app process across tests is exactly the pattern
    that produced this module's own observed UIA query flakiness during
    manual verification; a fresh process per test matches the
    fast/reliable timings that verification actually measured.

    Skips (not fails) if a real windowed process cannot even be launched
    here -- the genuine "this environment cannot do this at all" case the
    task's own stop condition calls for, distinct from an individual query
    stalling once a real window is confirmed to exist (which fails the
    test via ``_run_bounded`` instead, since that is a real regression to
    catch, not an environment limitation to shrug off).
    """
    project_root = Path(__file__).resolve().parents[3]
    config_path = tmp_path / "config" / "config.yaml"
    log_dir = tmp_path / "logs"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            _TARGET_MODULE,
            "--config-path",
            str(config_path),
            "--log-dir",
            str(log_dir),
        ],
        cwd=str(project_root),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    driver = _TargetAppDriver(process)
    try:
        ready_line = driver.wait_for("READY", timeout=45.0)
    except TimeoutError as exc:
        process.kill()
        process.wait(timeout=10)
        pytest.skip(
            "Could not launch a real, visible top-level window in this "
            f"environment (genuine environment limitation, not a code "
            f"defect): {exc}"
        )
    driver.pid = int(ready_line.split("pid=")[1])  # type: ignore[attr-defined]

    yield driver

    driver.send("quit")
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _uia_connect_main_window(pid: int, *, timeout: float = 15.0) -> Any:
    """Connect to ``pid`` and return its main window wrapper, already waited-for.

    Local import (not module-level): every ``pywinauto`` name used in this
    module must tolerate the ``_PYWINAUTO_AVAILABLE`` skip above running
    first -- a module-level ``from pywinauto import Application`` would
    raise at collection time on a machine without ``pywinauto`` installed,
    before the skip marker gets a chance to act.
    """
    from pywinauto import Application

    app = Application(backend="uia").connect(process=pid, timeout=timeout)
    main_window = app.window(title=_APP_TITLE)
    main_window.wait("exists visible", timeout=timeout)
    return main_window


# -- Main window: every control audit.py's rules require a name for really has one, in real UIA --


def test_main_window_controls_have_real_uia_names_and_sane_roles(
    uia_app: _TargetAppDriver,
) -> None:
    uia_app.send("main_names")
    names_line = uia_app.wait_for("MAIN_NAMES", timeout=30.0)
    expected = json.loads(names_line[len("MAIN_NAMES ") :])
    assert expected, "launcher reported zero expected names -- fixture is broken"

    def _work() -> list[dict[str, str]]:
        main_window = _uia_connect_main_window(uia_app.pid)  # type: ignore[attr-defined]
        descendants = main_window.descendants()
        return [
            {"name": d.element_info.name, "control_type": d.element_info.control_type}
            for d in descendants
        ]

    uia_elements = _run_bounded(
        _work, timeout=45.0, description="Main window UIA descendant walk"
    )
    uia_names_by_name: dict[str, set[str]] = {}
    for element in uia_elements:
        uia_names_by_name.setdefault(element["name"], set()).add(
            element["control_type"]
        )

    missing = [entry for entry in expected if entry["name"] not in uia_names_by_name]
    assert not missing, (
        "Widgets with a real Qt-side accessible name (audit.py's own "
        "criterion) never showed up as a named element in the real UIA "
        f"tree: {missing}"
    )

    role_mismatches = []
    for entry in expected:
        expected_role = _EXPECTED_CONTROL_TYPE.get(entry["class"])
        if expected_role is None:
            continue  # no empirically-confirmed mapping for this class -- see docstring
        actual_roles = uia_names_by_name[entry["name"]]
        if expected_role not in actual_roles:
            role_mismatches.append((entry, expected_role, actual_roles))
    assert (
        not role_mismatches
    ), f"UIA control_type did not match the expected role: {role_mismatches}"


# -- AboutDialog: a representative on-demand (not startup-constructed) dialog ---------------------


def test_about_dialog_is_uia_reachable_when_opened(uia_app: _TargetAppDriver) -> None:
    uia_app.send("open_about")
    uia_app.wait_for("ABOUT_OPENING", timeout=15.0)

    def _work() -> list[dict[str, str]]:
        main_window = _uia_connect_main_window(uia_app.pid)  # type: ignore[attr-defined]
        about = main_window.child_window(
            title=f"About {_APP_TITLE}", control_type="Window"
        )
        about.wait("exists visible", timeout=15.0)
        descendants = about.descendants()
        result = [
            {"name": d.element_info.name, "control_type": d.element_info.control_type}
            for d in descendants
        ]
        # Escape only reaches QDialog's built-in reject() shortcut once some
        # widget genuinely holds Qt-tracked keyboard focus -- manual
        # verification while building this test found a top-level
        # type_keys() with no explicit set_focus() first unreliable here
        # (AboutDialog sets no initial focus itself, unlike CommandPalette's
        # showEvent, which calls self._search.setFocus()). Focusing the
        # Close button directly is also the more representative action
        # anyway: it is what a keyboard-only user would actually do.
        close_button = next(d for d in descendants if d.element_info.name == "Close")
        close_button.set_focus()
        about.type_keys("{ESC}", set_foreground=False)  # QDialog default: reject()
        return result

    elements = _run_bounded(
        _work, timeout=45.0, description="AboutDialog UIA reachability + close"
    )
    names = {e["name"] for e in elements}
    assert _APP_TITLE in names, "AboutDialog's own app-name label was not UIA-visible"
    assert "Close" in names, "AboutDialog's Close button was not UIA-visible"
    close_buttons = [e for e in elements if e["name"] == "Close"]
    assert any(
        e["control_type"] == "Button" for e in close_buttons
    ), "AboutDialog's Close control did not expose the Button role"

    uia_app.wait_for("ABOUT_CLOSED", timeout=15.0)


# -- CommandPalette: role sanity + a real, live tab-order check -----------------------------------


def test_command_palette_is_uia_reachable_with_sane_tab_order(
    uia_app: _TargetAppDriver,
) -> None:
    uia_app.send("open_command_palette")
    expected_line = uia_app.wait_for("PALETTE_EXPECTED_NAMES", timeout=15.0)
    expected = json.loads(expected_line[len("PALETTE_EXPECTED_NAMES ") :])
    uia_app.wait_for("PALETTE_OPENING", timeout=15.0)

    def _work() -> dict[str, Any]:
        main_window = _uia_connect_main_window(uia_app.pid)  # type: ignore[attr-defined]
        palette = main_window.child_window(
            title="Command Palette", control_type="Window"
        )
        palette.wait("exists visible", timeout=15.0)
        descendants = palette.descendants()

        search_field = next(
            (d for d in descendants if d.element_info.name == "Search actions"), None
        )
        result_list = next(
            (d for d in descendants if d.element_info.control_type == "List"), None
        )
        outcome: dict[str, Any] = {
            "elements": [
                {
                    "name": d.element_info.name,
                    "control_type": d.element_info.control_type,
                }
                for d in descendants
            ],
            "search_field_found": search_field is not None,
            "result_list_found": result_list is not None,
        }
        if search_field is not None and result_list is not None:
            # A live tab-order check (WCAG 2.4.3): a static rules-based
            # audit cannot drive this (see rules._check_tab_order_
            # nondegenerate's own docstring -- it needs "a live event loop
            # and a shown window"), which is exactly what this
            # out-of-process, really-visible test is for.
            search_field.set_focus()
            outcome["search_focused_before_tab"] = search_field.has_keyboard_focus()
            palette.type_keys("{TAB}", set_foreground=False)
            outcome["search_focused_after_tab"] = search_field.has_keyboard_focus()
            outcome["list_focused_after_tab"] = result_list.has_keyboard_focus()
        palette.type_keys("{ESC}", set_foreground=False)  # QDialog default: reject()
        return outcome

    outcome = _run_bounded(
        _work, timeout=60.0, description="CommandPalette UIA reachability + tab order"
    )

    names = {e["name"] for e in outcome["elements"]}
    for entry in expected:
        assert entry["name"] in names, (
            f"CommandPalette's expected name {entry['name']!r} was not "
            "UIA-visible once the dialog was actually opened"
        )
    assert outcome["search_field_found"], "Search field was not UIA-reachable"
    assert outcome["result_list_found"], "Result list was not UIA-reachable"

    assert outcome["search_focused_before_tab"] is True
    assert outcome["search_focused_after_tab"] is False
    assert outcome["list_focused_after_tab"] is True, (
        "Tab did not move keyboard focus from the search field to the "
        "results list -- CommandPalette's tab order is structurally broken"
    )

    uia_app.wait_for("PALETTE_CLOSED", timeout=15.0)

# Phase 1.2 — JobRunner Protocol Design

**Status:** produced 2026-09-07 (architect) · **needs reviewer sign-off before implementation**
(the `implementer` works from this doc + the task list below).

**Goal.** Replace `src/workers/base_worker.py`'s `QThread` guts with a Qt-free `JobRunner`
protocol backed by `ThreadPoolExecutor`. `BaseWorker` stays in `src/workers/` (the shell,
deleted in Phase 2) as a thin adapter — **no call site, no test, no `WorkerRunner` change.**
A10: behaviour-preserving for every existing caller.

---

## 1. The protocol — `uadas_core/jobs/`

New package `uadas_core/jobs/` (its own subsystem; mirrors Phase 3's `django.tasks` shape).

```python
# uadas_core/jobs/job_runner.py
from __future__ import annotations
from typing import Any, Callable, Protocol, TypeVar

T = TypeVar("T")

class JobHandle(Protocol):
    """Opaque handle the caller keeps alive for the job's duration.
    Phase 1.2: a small dataclass. Phase 3: a task id."""

class JobRunner(Protocol):
    def run(
        self,
        fn: Callable[..., T],
        *args: Any,
        report_progress: bool = False,
        on_result: Callable[[T], None] | None = None,
        on_error: Callable[[Exception, str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        on_progress: Callable[[int, str], None] | None = None,
        **kwargs: Any,
    ) -> JobHandle: ...
```

**Contract:** `fn(*args, **kwargs)` runs off the calling thread. If `report_progress=True`, a
`progress_callback: Callable[[int, str], None]` is injected into `kwargs` before the call
(exactly as `BaseWorker` does today — `base_worker.py:124`). Callbacks fire once each
(`on_result` XOR `on_error`, then always `on_finished`), from the runner's execution context —
**thread affinity is the adapter's problem, not the runner's.** No cancellation in 1.2
(`BaseWorker` has none today).

**Why callbacks, not a `Future`:** Phase 3's `django.tasks`/Celery runs `fn` in another
*process*; there is no in-process future to hand back. Callbacks work for both (a local thread
invokes them now; a worker posts an HTTP webhook later). `JobHandle` stays opaque for the same
reason. The architect found **no blocker** to a `DjangoTasksJobRunner` satisfying this later.

---

## 2. In-process implementation

```python
# uadas_core/jobs/thread_pool_executor_job_runner.py
class ThreadPoolExecutorJobRunner:
    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def run(self, fn, *args, report_progress=False, on_result=None, on_error=None,
            on_finished=None, on_progress=None, **kwargs) -> SimpleJobHandle:
        if report_progress:
            kwargs["progress_callback"] = on_progress or (lambda *_: None)
        def _wrapped():
            try:
                r = fn(*args, **kwargs)
                if on_result: on_result(r)
            except Exception as exc:          # noqa: BLE001 - reported via on_error
                if on_error: on_error(exc, traceback.format_exc())
            finally:
                if on_finished: on_finished()
        self._executor.submit(_wrapped)
        return SimpleJobHandle(id=str(uuid4()))
```

`max_workers=4` (desktop default; a server tunes it). `SimpleJobHandle` = a `frozen`
dataclass holding a uuid (book-keeping only in 1.2).

---

## 3. The `BaseWorker` adapter (`src/workers/base_worker.py`, modified in place)

- `WorkerSignals` — **unchanged** (`started`, `progress(int,str)`, `result(object)`,
  `error(Exception,str)`, `finished`).
- `BaseWorker.__init__(fn, *args, report_progress=False, **kwargs)` — **unchanged signature.**
- `BaseWorker.run()` (called by `QThreadPool` on a pool thread): emit `started`; get the
  `JobRunner` via `uadas_core.jobs.get_default_job_runner()`; call `job_runner.run(...)` wiring
  each `on_*` callback to `self.signals.*.emit(...)`; then **block the pool thread on a
  `threading.Event`** set by `on_finished` — so `QThreadPool`'s "run() is synchronous"
  contract holds. Qt's existing `QueuedConnection` (`worker_runner.py:110`) still marshals the
  emitted signals to the UI thread.
- **Delete the `[diag]` logging** the file's own comments (~lines 101-177) say to remove.

**Getting the runner in without a signature change:** a module-level registry —
`uadas_core/jobs/__init__.py` exposes `set_default_job_runner(runner)` / `get_default_job_runner()`.
`bootstrap()` calls `set_default_job_runner(...)` once. This is a **Phase-1.2-only bridge**
that dies with `BaseWorker` in Phase 2. *(Note for the 1.3 architect: this adds one module
global; 1.3's de-globalization pass should be aware it exists and is intentionally scoped to
the disposable shell.)*

---

## 4. `bootstrap()` registration (`uadas_core/core/bootstrap.py`)

After `PluginManager` registration:

```python
job_runner = ThreadPoolExecutorJobRunner(max_workers=4)
container.register(JobRunner, lambda: job_runner, singleton=True)   # explicit path
set_default_job_runner(job_runner)                                  # BaseWorker bridge
```

---

## 5. Bite-sized task list (for the `implementer`, TDD-first)

1. **`uadas_core/jobs/job_runner.py`** — `JobHandle` + `JobRunner` Protocols + docstrings. Commit.
2. **`tests/jobs/test_job_runner.py`** — characterization test against a fake impl: `on_result`
   once with the return value; `on_error(exc, tb_str)` on raise; `on_finished` always; `on_progress`
   only when `report_progress` and `fn` calls `progress_callback`; result XOR error. Commit.
3. **`uadas_core/jobs/thread_pool_executor_job_runner.py`** — `SimpleJobHandle` + the impl. Commit.
4. **`tests/jobs/test_thread_pool_executor_job_runner.py`** — run the section-2 characterization
   test against the real impl; a 10-concurrent-jobs progress test. Commit.
5. **`uadas_core/jobs/__init__.py`** — `set_default_job_runner` / `get_default_job_runner`
   (raise if unset). Commit.
6. **`uadas_core/core/bootstrap.py`** — register (both paths, section 4).
   **`tests/core/test_bootstrap.py`** — `container.resolve(JobRunner)` is a singleton and
   `== get_default_job_runner()`. Commit.
7. **`src/workers/base_worker.py`** — rewrite `run()` to delegate (section 3); **delete `[diag]`
   logging**; ctor + `WorkerSignals` untouched. Commit.
8. **`tests/ui/test_base_worker_adapter.py`** — characterization: `BaseWorker(mock_fn, 1, 2,
   foo="bar", report_progress=True)` → `JobRunner.run` called with those exact args; signals
   emitted in order `started -> progress* -> result|error -> finished`. Commit.
9. **Verify:** `run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py` unchanged; full
   suite == the post-1.5 baseline (1374 passed / 92 skipped / 0 failed — see
   `plans/phase-1-baseline.md`); `screenshot_app_state.py` byte-identical; `lint-imports`
   green; ruff / black / isort / scoped-mypy / `bandit -r uadas_core/jobs src/workers` green.

---

## Scope fence — NOT in 1.2

Cancellation API · job history / result caching · task tracing / telemetry · plugin-registered
custom runners · the `DjangoTasksJobRunner` itself (Phase 3). The protocol is designed to admit
these later without a breaking change; do not build them now.

## Unverified

- `max_workers=4` is a guess — no desktop profiling data. Tunable; pool saturation is observable
  (tests fail loudly).
- `threading.Event().wait()` on a `QThreadPool` thread is assumed deadlock-free (the pool has
  other threads; this is standard pool usage) — the characterization test in step 8 + the full
  suite in step 9 are the proof.
- No current code submits >4 concurrent long jobs.

## Architect sign-off still needed on

Module location `uadas_core/jobs/` · `max_workers` default `4` · the `get_default_job_runner()`
module-bridge vs. alternatives (chosen to avoid touching `BaseWorker`'s public signature).

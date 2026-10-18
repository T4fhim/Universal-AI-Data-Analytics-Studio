# File: apps/api/tests/jobs_support.py
"""Helpers for the opt-in real-worker integration test: the gate, the worker process, the queue.

Why a module (mirroring ``storage_support.py``): the gate predicates are unit-tested without a
broker (``test_jobs_ci_guard.py``), and the worker harness is used by more than one test.

The integration test needs three real services at once -- PostgreSQL (the worker is another
process, so an in-memory SQLite test database is invisible to it), Redis (the broker) and MinIO
(the object store the worker and the test share) -- plus a real ``celery worker`` process.
It runs only when ``JOBS_INTEGRATION=1`` *and* every variable it needs is exported; nothing is
ever guessed, so the hermetic suite cannot reach a broker by accident. In CI the ``api-test`` job
sets all of it and ``test_jobs_ci_guard`` fails the build if any is lost.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from storage_support import integration_enabled as storage_integration_enabled


def integration_enabled(env: Mapping[str, str] | None = None) -> bool:
    """True when the real-worker test was asked for and every service it needs is configured."""
    source = os.environ if env is None else env
    broker = source.get("CELERY_BROKER_URL") or source.get("REDIS_URL")
    database = source.get("DATABASE_URL", "")
    return bool(
        source.get("JOBS_INTEGRATION") == "1"
        and broker
        and database.startswith(("postgres://", "postgresql://"))
        and storage_integration_enabled(source)
    )


def integration_required_but_missing(env: Mapping[str, str] | None = None) -> bool:
    """True when CI demands the real-worker test but it would silently skip."""
    source = os.environ if env is None else env
    return source.get("CI", "").lower() == "true" and not integration_enabled(source)


def database_url(settings_dict: Mapping[str, Any]) -> str:
    """A ``postgres://`` URL for the connection the test is using (the *test* database)."""
    user, password = settings_dict["USER"], settings_dict["PASSWORD"]
    host, port = settings_dict["HOST"] or "localhost", settings_dict["PORT"] or 5432
    return f"postgres://{user}:{password}@{host}:{port}/{settings_dict['NAME']}"


class Worker:
    """A real ``celery worker`` process bound to one private queue, with its output captured."""

    def __init__(self, env: Mapping[str, str], queue: str) -> None:
        self.queue = queue
        self.lines: list[str] = []
        command = [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "uadas_api.jobs.celery_app",
            "worker",
            "--pool=solo",  # the only pool that exists on Windows; fine for one job at a time
            "--queues",
            queue,
            "--loglevel=INFO",
            "--without-gossip",
            "--without-mingle",
            "--without-heartbeat",
            "--hostname",
            f"it-{uuid.uuid4().hex[:6]}@%h",
        ]
        self._process = subprocess.Popen(  # nosec B603
            command,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=os.name == "posix",
        )
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self._process.stdout is not None  # nosec B101
        for line in self._process.stdout:
            self.lines.append(line.rstrip())

    def output(self, tail: int = 60) -> str:
        return "\n".join(self.lines[-tail:])

    def wait_until_ready(self, timeout: float = 90.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(" ready." in line for line in self.lines):
                return
            if self._process.poll() is not None:
                raise AssertionError(f"the worker exited early:\n{self.output()}")
            time.sleep(0.25)
        raise AssertionError(f"the worker did not become ready:\n{self.output()}")

    def count(self, needle: str) -> int:
        return sum(1 for line in self.lines if needle in line)

    def wait_for_count(self, needle: str, at_least: int, timeout: float = 30.0) -> int:
        """Wait until the worker's output holds ``needle`` at least ``at_least`` times.

        The task-finished log line is written *after* the job's database commit, so a test that
        saw the row succeed can still be a moment ahead of the log.
        """
        deadline = time.monotonic() + timeout
        while self.count(needle) < at_least and time.monotonic() < deadline:
            time.sleep(0.25)
        return self.count(needle)

    def stop(self) -> None:
        if self._process.poll() is None:
            if os.name == "nt":
                subprocess.run(  # nosec B603
                    [
                        "taskkill",
                        "/F",
                        "/T",
                        "/PID",
                        str(self._process.pid),
                    ],  # nosec B607
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self._process.pid, signal.SIGTERM)
        try:
            self._process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._process.kill()
        self._reader.join(timeout=5)


@contextmanager
def running_worker(env: Mapping[str, str], queue: str) -> Iterator[Worker]:
    """Start a worker, wait until it is consuming, and always stop it."""
    worker = Worker(env, queue)
    try:
        worker.wait_until_ready()
        yield worker
    finally:
        worker.stop()

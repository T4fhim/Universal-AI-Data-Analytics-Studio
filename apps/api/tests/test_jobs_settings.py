# File: apps/api/tests/test_jobs_settings.py
"""Settings for the job queue and the parser sandbox (3.5): strict parsing, safe defaults.

Why: the queue and the sandbox are configured from the environment like everything else, and
the same rule applies -- a typo must stop start-up, never fall back to something weaker. The
properties pinned here are the ones whose silent loss would be a security or data-loss bug:
JSON-only serialization (a pickle broker message is code execution), late acknowledgement with
bounded redelivery, a visibility timeout longer than any task can run (or Redis redelivers a
task that is still running), no eager mode and no unenforceable sandbox in production.

Each refusal is paired with the nearest accepted value, so a settings parser that rejected
everything could not pass.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured

from uadas_api.sandbox import limits as sandbox_limits
from uadas_api.settings import _jobs

Loader = Callable[..., ModuleType]

# The production environment of test_settings.PROD_ENV, repeated so this module stands alone.
PROD_ENV = {
    "DJANGO_SECRET_KEY": "k" * 60,
    "DJANGO_ALLOWED_HOSTS": "api.example.com",
    "DATABASE_URL": "postgres://uadas:pw@db.internal:5432/uadas",
    "REDIS_URL": "redis://cache.internal:6379/0",
    "DEFAULT_FROM_EMAIL": "UADAS <no-reply@example.com>",
    "EMAIL_HOST": "smtp.example.com",
    "FRONTEND_BASE_URL": "https://app.example.com",
    "STORAGE_BUCKET": "uadas-tenant-data",
    "STORAGE_ENDPOINT_URL": "https://objects.example.com",
    "STORAGE_ACCESS_KEY_ID": "ci-key-4f7q2m9xj3kd8tlp",
    "STORAGE_SECRET_ACCESS_KEY": "wJ9r3Kd8Zx2PqL7mV5nB1cT6yH4sG0aE9uRf",
    "STORAGE_REGION": "us-east-1",
    "STORAGE_SSE": "aes256",
    "SANDBOX_ISOLATION_ACKNOWLEDGED": "container",
    "SANDBOX_NETWORK_ISOLATION": "container",
    "QUOTA_UNLIMITED_ACKNOWLEDGED": "true",  # 3.8: production states its quotas or says unlimited is intended
}
# What production must state about isolation (see ``validate_for_production``).
ISOLATED = {
    "SANDBOX_ISOLATION_ACKNOWLEDGED": "container",
    "SANDBOX_NETWORK_ISOLATION": "container",
}


@pytest.fixture
def enforceable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the platform can enforce rlimits (so prod can be loaded on a Windows laptop)."""
    monkeypatch.setattr(sandbox_limits, "limits_enforceable", lambda *a, **k: True)


# ------------------------------------------------------------------ parse_jobs


def test_defaults_are_safe() -> None:
    jobs = _jobs.parse_jobs({"REDIS_URL": "redis://localhost:6379/0"})
    assert (
        jobs["broker_url"] == "redis://localhost:6379/1"
    )  # never the cache's database
    assert jobs["eager"] is False
    assert jobs["max_attempts"] == 3
    assert jobs["soft_time_limit"] < jobs["time_limit"]
    assert jobs["visibility_timeout"] > jobs["time_limit"] + jobs["retry_backoff_max"]
    _jobs.validate_consistency(jobs, _jobs.parse_sandbox({}))  # the defaults nest


def test_the_broker_defaults_to_redis_url_on_another_database_and_an_explicit_broker_wins() -> (
    None
):
    assert _jobs.parse_jobs({"REDIS_URL": "redis://a:6379/0"})["broker_url"] == (
        "redis://a:6379/1"
    )
    # no database in the URL means database 0: the queue still moves away from it
    assert _jobs.parse_jobs({"REDIS_URL": "redis://a:6379"})["broker_url"] == (
        "redis://a:6379/1"
    )
    # a cache already on 1 sends the queue to 2; credentials, host, port and scheme are kept
    moved = _jobs.parse_jobs({"REDIS_URL": "rediss://:pw@a.internal:6380/1"})
    assert moved["broker_url"] == "rediss://:pw@a.internal:6380/2"
    both = {"REDIS_URL": "redis://a:6379/0", "CELERY_BROKER_URL": "redis://b:6379/5"}
    assert _jobs.parse_jobs(both)["broker_url"] == "redis://b:6379/5"


def test_a_cache_clear_would_not_reach_the_queue_and_the_collision_test_is_exact() -> (
    None
):
    cache = "redis://cache:6379/0"
    assert not _jobs.redis_namespaces_collide(cache, _jobs.distinct_broker_url(cache))
    assert _jobs.redis_namespaces_collide(cache, "redis://cache:6379/0")
    assert _jobs.redis_namespaces_collide(
        cache, "redis://CACHE:6379"
    )  # case, default db
    assert not _jobs.redis_namespaces_collide(cache, "redis://cache:6379/3")
    assert not _jobs.redis_namespaces_collide(cache, "redis://other:6379/0")
    assert not _jobs.redis_namespaces_collide(cache, "redis://cache:6380/0")
    assert not _jobs.redis_namespaces_collide("locmem://", "redis://cache:6379/0")


def test_timeouts_must_nest_around_the_sandbox_wall_clock() -> None:
    sandbox = _jobs.parse_sandbox({"SANDBOX_WALL_SECONDS": "120"})
    # the heartbeat window must outlast the parse, with margin
    too_short = _jobs.parse_jobs({"JOBS_STALE_AFTER_SECONDS": "170"})
    with pytest.raises(ImproperlyConfigured, match="JOBS_STALE_AFTER_SECONDS"):
        _jobs.validate_consistency(too_short, sandbox)
    _jobs.validate_consistency(
        _jobs.parse_jobs({"JOBS_STALE_AFTER_SECONDS": "181"}), sandbox
    )
    # and so must the Celery hard limit
    short_hard = _jobs.parse_jobs(
        {
            "JOBS_SOFT_TIME_LIMIT_SECONDS": "100",
            "JOBS_TIME_LIMIT_SECONDS": "150",
            "JOBS_STALE_AFTER_SECONDS": "600",
        }
    )
    with pytest.raises(ImproperlyConfigured, match="JOBS_TIME_LIMIT_SECONDS"):
        _jobs.validate_consistency(short_hard, sandbox)
    ok = _jobs.parse_jobs(
        {
            "JOBS_SOFT_TIME_LIMIT_SECONDS": "100",
            "JOBS_TIME_LIMIT_SECONDS": "190",
            "JOBS_STALE_AFTER_SECONDS": "600",
        }
    )
    _jobs.validate_consistency(ok, sandbox)


def test_no_broker_at_all_is_allowed_only_as_an_empty_string() -> None:
    assert _jobs.parse_jobs({})["broker_url"] == ""


@pytest.mark.parametrize(
    ("name", "bad", "good"),
    [
        ("JOBS_MAX_ATTEMPTS", "0", "1"),
        ("JOBS_MAX_ATTEMPTS", "99", "10"),
        ("JOBS_MAX_ATTEMPTS", "many", "3"),
        ("JOBS_STALE_AFTER_SECONDS", "5", "30"),
        ("JOBS_RETRY_BACKOFF_MAX_SECONDS", "0", "1"),
        ("JOBS_PROGRESS_INTERVAL_MS", "-1", "0"),
    ],
)
def test_numeric_settings_are_bounded_and_a_typo_stops_start_up(
    name: str, bad: str, good: str
) -> None:
    with pytest.raises(ImproperlyConfigured, match=name):
        _jobs.parse_jobs({name: bad})
    _jobs.parse_jobs({name: good})


def test_time_limits_must_be_ordered_and_fit_inside_the_visibility_timeout() -> None:
    base = {"JOBS_SOFT_TIME_LIMIT_SECONDS": "100", "JOBS_TIME_LIMIT_SECONDS": "130"}
    with pytest.raises(ImproperlyConfigured, match="TIME_LIMIT"):
        _jobs.parse_jobs({**base, "JOBS_SOFT_TIME_LIMIT_SECONDS": "130"})
    with pytest.raises(ImproperlyConfigured, match="VISIBILITY"):
        _jobs.parse_jobs({**base, "JOBS_VISIBILITY_TIMEOUT_SECONDS": "200"})
    # the nearest accepted value: just past time limit + backoff cap
    ok = _jobs.parse_jobs(
        {
            **base,
            "JOBS_RETRY_BACKOFF_MAX_SECONDS": "60",
            "JOBS_VISIBILITY_TIMEOUT_SECONDS": "191",
        }
    )
    assert ok["visibility_timeout"] == 191


def test_the_queue_name_is_a_plain_identifier() -> None:
    assert _jobs.parse_jobs({"JOBS_QUEUE": "uadas-jobs"})["queue"] == "uadas-jobs"
    for bad in ("two words", "a/b", "x" * 80, "queue;drop"):
        with pytest.raises(ImproperlyConfigured, match="JOBS_QUEUE"):
            _jobs.parse_jobs({"JOBS_QUEUE": bad})


# --------------------------------------------------------------------- celery


def test_celery_settings_are_json_only_late_acked_and_bounded() -> None:
    jobs = _jobs.parse_jobs({"REDIS_URL": "redis://localhost:6379/0"})
    celery = _jobs.celery_settings(jobs)
    assert celery["CELERY_ACCEPT_CONTENT"] == ["json"]
    assert celery["CELERY_TASK_SERIALIZER"] == "json"
    assert celery["CELERY_RESULT_SERIALIZER"] == "json"
    assert celery["CELERY_EVENT_SERIALIZER"] == "json"
    assert celery["CELERY_TASK_ACKS_LATE"] is True
    assert celery["CELERY_TASK_REJECT_ON_WORKER_LOST"] is True
    assert celery["CELERY_WORKER_PREFETCH_MULTIPLIER"] == 1
    assert celery["CELERY_TASK_IGNORE_RESULT"] is True  # job state is the database row
    assert celery["CELERY_RESULT_BACKEND"] is None
    assert celery["CELERY_TASK_SOFT_TIME_LIMIT"] == jobs["soft_time_limit"]
    assert celery["CELERY_TASK_TIME_LIMIT"] == jobs["time_limit"]
    transport = celery["CELERY_BROKER_TRANSPORT_OPTIONS"]
    assert transport["visibility_timeout"] == jobs["visibility_timeout"]
    assert celery["CELERY_BROKER_URL"] == "redis://localhost:6379/1"
    assert celery["CELERY_TASK_DEFAULT_QUEUE"] == jobs["queue"]
    assert "pickle" not in str(celery).lower()


def test_the_beat_schedule_runs_the_stale_job_sweeper() -> None:
    celery = _jobs.celery_settings(_jobs.parse_jobs({}))
    entries = celery["CELERY_BEAT_SCHEDULE"]
    assert [e["task"] for e in entries.values()] == ["uadas.jobs.sweep"]


# ------------------------------------------------------------------- sandbox


def test_sandbox_defaults_build_valid_limits() -> None:
    sandbox = _jobs.parse_sandbox({})
    limits = sandbox_limits.SandboxLimits.from_mapping(sandbox)
    assert limits.memory_bytes >= 256 * 1024 * 1024
    assert (
        limits.wall_seconds <= limits.cpu_seconds + 60
    )  # the wall clock is the outer bound
    assert limits.max_input_bytes <= limits.max_decompressed_bytes


@pytest.mark.parametrize(
    ("name", "bad", "good"),
    [
        ("SANDBOX_MEMORY_MB", "64", "256"),
        ("SANDBOX_WALL_SECONDS", "0", "1"),
        ("SANDBOX_MAX_INPUT_MB", "0", "1"),
        ("SANDBOX_MAX_ROWS", "-5", "5"),
        ("SANDBOX_PROCESS_HEADROOM", "-1", "0"),
        ("SANDBOX_MAX_COMPRESSION_RATIO", "1", "2"),
    ],
)
def test_sandbox_numbers_are_bounded(name: str, bad: str, good: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=name):
        _jobs.parse_sandbox({name: bad})
    _jobs.parse_sandbox({name: good})


def test_sandbox_tmp_root_is_an_absolute_path_or_empty() -> None:
    assert _jobs.parse_sandbox({})["tmp_root"] == ""
    assert _jobs.parse_sandbox({"SANDBOX_TMP_ROOT": "/var/lib/uadas/sandbox"})[
        "tmp_root"
    ]
    with pytest.raises(ImproperlyConfigured, match="SANDBOX_TMP_ROOT"):
        _jobs.parse_sandbox({"SANDBOX_TMP_ROOT": "relative/dir"})


# ------------------------------------------------------------------ production


def test_the_isolation_settings_are_strict_and_default_to_nothing_claimed() -> None:
    sandbox = _jobs.parse_sandbox({})
    assert (sandbox["child_uid"], sandbox["child_gid"]) == (None, None)
    assert (sandbox["network_isolation"], sandbox["isolation_acknowledged"]) == ("", "")
    chosen = _jobs.parse_sandbox(
        {
            "SANDBOX_CHILD_UID": "61234",
            "SANDBOX_CHILD_GID": "61235",
            "SANDBOX_NETWORK_ISOLATION": "unshare",
            "SANDBOX_ISOLATION_ACKNOWLEDGED": "container",
        }
    )
    assert (chosen["child_uid"], chosen["child_gid"]) == (61234, 61235)
    limits = sandbox_limits.SandboxLimits.from_mapping(chosen)
    assert limits.network_isolation == "unshare"


@pytest.mark.parametrize(
    ("env", "name"),
    [
        ({"SANDBOX_CHILD_UID": "61234"}, "SANDBOX_CHILD_UID"),  # a uid without a gid
        ({"SANDBOX_CHILD_GID": "61234"}, "SANDBOX_CHILD_UID"),
        ({"SANDBOX_CHILD_UID": "0", "SANDBOX_CHILD_GID": "0"}, "SANDBOX_CHILD_UID"),
        ({"SANDBOX_CHILD_UID": "x", "SANDBOX_CHILD_GID": "1"}, "SANDBOX_CHILD_UID"),
        ({"SANDBOX_NETWORK_ISOLATION": "yes"}, "SANDBOX_NETWORK_ISOLATION"),
        ({"SANDBOX_ISOLATION_ACKNOWLEDGED": "host"}, "SANDBOX_ISOLATION_ACKNOWLEDGED"),
    ],
)
def test_nonsense_isolation_settings_stop_start_up(
    env: dict[str, str], name: str
) -> None:
    with pytest.raises(ImproperlyConfigured, match=name):
        _jobs.parse_sandbox(env)
    _jobs.parse_sandbox({"SANDBOX_CHILD_UID": "5", "SANDBOX_CHILD_GID": "5"})


def validate(
    jobs_env: dict[str, str] | None = None,
    sandbox_env: dict[str, str] | None = None,
    *,
    enforceable: bool = True,
    cache_url: str = "",
) -> None:
    """``validate_for_production`` on a sane base (override what the test is about)."""
    jobs = _jobs.parse_jobs({"REDIS_URL": "redis://cache:6379/0", **(jobs_env or {})})
    sandbox = _jobs.parse_sandbox({**ISOLATED, **(sandbox_env or {})})
    _jobs.validate_for_production(
        jobs, sandbox, enforceable=enforceable, cache_url=cache_url
    )


def test_production_requires_a_broker() -> None:
    with pytest.raises(ImproperlyConfigured, match="CELERY_BROKER_URL"):
        _jobs.validate_for_production(
            _jobs.parse_jobs({}), _jobs.parse_sandbox(ISOLATED), enforceable=True
        )
    validate()


def test_production_refuses_eager_mode() -> None:
    with pytest.raises(ImproperlyConfigured, match="JOBS_EAGER"):
        validate({"JOBS_EAGER": "1"})


def test_production_refuses_a_platform_that_cannot_enforce_limits() -> None:
    with pytest.raises(ImproperlyConfigured, match="memory and CPU limits"):
        validate(enforceable=False)
    validate(enforceable=True)


def test_production_refuses_a_plain_memory_broker() -> None:
    with pytest.raises(ImproperlyConfigured, match="CELERY_BROKER_URL"):
        validate({"CELERY_BROKER_URL": "memory://"})


def test_production_requires_something_to_separate_the_child_from_the_worker() -> None:
    nothing = {"SANDBOX_ISOLATION_ACKNOWLEDGED": ""}
    with pytest.raises(ImproperlyConfigured, match="SANDBOX_CHILD_UID"):
        validate(sandbox_env=nothing)
    # either answer is accepted: a dedicated uid ...
    validate(
        sandbox_env={
            **nothing,
            "SANDBOX_CHILD_UID": "61234",
            "SANDBOX_CHILD_GID": "61234",
        }
    )
    # ... or the operator's statement that a container does it
    validate(sandbox_env={"SANDBOX_ISOLATION_ACKNOWLEDGED": "container"})


def test_production_requires_an_explicit_network_isolation_answer() -> None:
    with pytest.raises(ImproperlyConfigured, match="SANDBOX_NETWORK_ISOLATION"):
        validate(sandbox_env={"SANDBOX_NETWORK_ISOLATION": ""})
    for answer in ("unshare", "container", "none-acknowledged"):
        validate(sandbox_env={"SANDBOX_NETWORK_ISOLATION": answer})


def test_production_refuses_a_queue_that_shares_the_caches_redis_database() -> None:
    cache = "redis://cache:6379/0"
    with pytest.raises(ImproperlyConfigured, match="different Redis databases"):
        validate({"CELERY_BROKER_URL": "redis://cache:6379/0"}, cache_url=cache)
    validate({"CELERY_BROKER_URL": "redis://cache:6379/4"}, cache_url=cache)
    validate(
        cache_url=cache
    )  # REDIS_URL alone is moved to another database automatically


# ---------------------------------------------------- the real settings modules


def test_prod_loads_with_the_full_environment_and_is_not_eager(
    load_settings: Loader, enforceable: None
) -> None:
    prod = load_settings("prod", **PROD_ENV)
    assert prod.UADAS_JOBS["eager"] is False
    assert (
        prod.CELERY_BROKER_URL == "redis://cache.internal:6379/1"
    )  # not the cache's /0
    assert prod.CACHES["default"]["LOCATION"] == PROD_ENV["REDIS_URL"]
    assert prod.CELERY_TASK_ALWAYS_EAGER is False
    assert prod.CELERY_ACCEPT_CONTENT == ["json"]


def test_prod_refuses_to_start_where_limits_cannot_be_enforced(
    load_settings: Loader, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox_limits, "limits_enforceable", lambda *a, **k: False)
    with pytest.raises(ImproperlyConfigured, match="memory and CPU limits"):
        load_settings("prod", **PROD_ENV)


def test_prod_refuses_eager_mode_from_the_environment(
    load_settings: Loader, enforceable: None
) -> None:
    with pytest.raises(ImproperlyConfigured, match="JOBS_EAGER"):
        load_settings("prod", JOBS_EAGER="true", **PROD_ENV)


def test_prod_refuses_to_start_without_the_isolation_statements(
    load_settings: Loader, enforceable: None
) -> None:
    env = {k: v for k, v in PROD_ENV.items() if k != "SANDBOX_NETWORK_ISOLATION"}
    with pytest.raises(ImproperlyConfigured, match="SANDBOX_NETWORK_ISOLATION"):
        load_settings("prod", **env)
    env = {k: v for k, v in PROD_ENV.items() if k != "SANDBOX_ISOLATION_ACKNOWLEDGED"}
    with pytest.raises(ImproperlyConfigured, match="SANDBOX_CHILD_UID"):
        load_settings("prod", **env)


def test_prod_refuses_a_queue_on_the_caches_database(
    load_settings: Loader, enforceable: None
) -> None:
    with pytest.raises(ImproperlyConfigured, match="different Redis databases"):
        load_settings(
            "prod",
            CELERY_BROKER_URL=PROD_ENV["REDIS_URL"],
            **{k: v for k, v in PROD_ENV.items()},
        )


def test_prod_uses_an_explicit_broker_when_given(
    load_settings: Loader, enforceable: None
) -> None:
    prod = load_settings(
        "prod", CELERY_BROKER_URL="redis://queue.internal:6379/2", **PROD_ENV
    )
    assert prod.CELERY_BROKER_URL == "redis://queue.internal:6379/2"
    assert prod.CACHES["default"]["LOCATION"] == PROD_ENV["REDIS_URL"]  # unchanged


def test_test_settings_are_hermetic_and_eager(load_settings: Loader) -> None:
    test = load_settings(
        "test", CELERY_BROKER_URL="redis://real:6379/0", JOBS_EAGER="0"
    )
    assert test.CELERY_TASK_ALWAYS_EAGER is True
    assert test.CELERY_BROKER_URL.startswith(
        "memory://"
    )  # never the developer's broker
    assert test.UADAS_SANDBOX["tmp_root"] == ""


def test_dev_defaults_to_the_compose_redis_and_is_not_eager(
    load_settings: Loader,
) -> None:
    dev = load_settings("dev")
    assert dev.CELERY_BROKER_URL == "redis://localhost:6379/0"
    assert dev.CELERY_TASK_ALWAYS_EAGER is False
    assert load_settings("dev", REDIS_URL="redis://x:6379/3").CELERY_BROKER_URL == (
        "redis://x:6379/1"
    )  # moved off the cache's database


def test_base_has_no_broker_unless_the_environment_names_one(
    load_settings: Loader,
) -> None:
    assert load_settings("base").CELERY_BROKER_URL == ""

# File: apps/api/tests/test_web_idempotency.py
"""Client idempotency for the two create-with-a-job routes: upload and report request.

A client that times out cannot know whether its request arrived; with an ``Idempotency-Key`` header it
can simply send it again. The rules, each with a twin: the same key (in the same organization and
project) returns the *same* job and dataset/report and creates nothing new; a different key is a new
request; the same key with a different body, or in another project, is a ``409`` (never a silent
reuse); another organization's identical key is independent; a malformed key is a ``422``; and
without a header every request is its own (the old behaviour).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from web_support import World, error_code, make_world

from uadas_api.exports.models import Report
from uadas_api.jobs.models import Job
from uadas_api.storage.store import get_store
from uadas_api.workspaces.models import Project

pytestmark = pytest.mark.django_db

CSV = b"name,qty\nwidget,3\ngadget,5\n"


@pytest.fixture
def world() -> World:
    return make_world()


@pytest.fixture(autouse=True)
def _private_sandbox_root(settings: Any, tmp_path: Path) -> None:
    root = tmp_path / "sandbox-root"
    root.mkdir()
    settings.UADAS_SANDBOX = {**settings.UADAS_SANDBOX, "tmp_root": str(root)}


def _upload(
    world: World, who: str = "editor", key: str | None = None, base: str | None = None
) -> Any:
    api = world.api(who)
    headers = {"X-CSRFToken": api.token}
    if key is not None:
        headers["Idempotency-Key"] = key
    return api.client.post(
        f"{base or world.base()}/datasets/upload",
        {"file": SimpleUploadedFile("sales.csv", CSV, content_type="text/csv")},
        headers=headers,
    )


def _report(
    world: World,
    key: str | None,
    who: str = "editor",
    base: str | None = None,
    **over: Any,
) -> Any:
    body = {
        "title": "Quarterly",
        "format": "html",
        "dataset_id": str(world.dataset.pk),
        **over,
    }
    api = world.api(who)
    headers = {"X-CSRFToken": api.token}
    if key is not None:
        headers["Idempotency-Key"] = key
    import json

    return api.client.generic(
        "POST",
        f"{base or world.base()}/reports",
        json.dumps(body),
        content_type="application/json",
        headers=headers,
    )


def _objects(world: World) -> int:
    return len(list(get_store(world.org).list_prefix(f"{world.org.pk}/datasets/")))


def test_a_retried_upload_with_the_same_key_returns_the_same_job_and_dataset(
    world: World,
) -> None:
    first = _upload(world, key="retry-1")
    again = _upload(world, key="retry-1")
    assert first.status_code == again.status_code == 202
    assert first.json()["job_id"] == again.json()["job_id"]
    assert first.json()["dataset_id"] == again.json()["dataset_id"]
    assert Job.objects.filter(kind="ingest_dataset").count() == 1
    stored_after_retry = _objects(world)
    other = _upload(world, key="retry-2")  # the twin: another key is another request
    assert other.json()["job_id"] != first.json()["job_id"]
    assert other.json()["dataset_id"] != first.json()["dataset_id"]
    assert Job.objects.filter(kind="ingest_dataset").count() == 2
    assert _objects(world) > stored_after_retry
    # without a header every request is its own
    a, b = _upload(world), _upload(world)
    assert a.json()["job_id"] != b.json()["job_id"]


def test_an_upload_key_is_scoped_to_the_organization_and_the_project(
    world: World,
) -> None:
    first = _upload(world, key="shared")
    foreign = _upload(world, "other", key="shared", base=world.other_base)
    assert foreign.status_code == 202
    assert (
        foreign.json()["job_id"] != first.json()["job_id"]
    )  # another organization: independent
    second = Project.objects.create(organization=world.org, name="Second")
    reused = _upload(world, key="shared", base=world.base(project=second))
    assert (
        reused.status_code == 409 and error_code(reused) == "conflict"
    )  # same org, other project


def test_a_malformed_idempotency_key_is_refused(world: World) -> None:
    for bad in ("has space", "x" * 80, "semi;colon"):
        assert _upload(world, key=bad).status_code == 422, bad
        assert _report(world, bad).status_code == 422, bad
    assert not Job.objects.exists()


def test_a_retried_report_request_returns_the_same_report_and_job(world: World) -> None:
    first = _report(world, "r-1")
    again = _report(world, "r-1")
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json()
    assert Report.objects.filter(project=world.project).count() == 1
    assert Job.objects.filter(kind="build_report").count() == 1
    other = _report(world, "r-2")  # the twin
    assert other.json()["report"]["id"] != first.json()["report"]["id"]
    assert Report.objects.filter(project=world.project).count() == 2
    assert (
        _report(world, None).json()["job_id"] != _report(world, None).json()["job_id"]
    )


def test_a_report_key_with_a_different_body_or_project_is_a_conflict(
    world: World,
) -> None:
    assert _report(world, "r-3").status_code == 202
    changed = _report(world, "r-3", title="Something else")
    assert changed.status_code == 409 and error_code(changed) == "conflict"
    assert Report.objects.filter(project=world.project).count() == 1
    foreign = _report(
        world,
        "r-3",
        who="other",
        base=world.other_base,
        dataset_id=str(world.dataset.pk),
    )
    assert (
        foreign.status_code == 404
    )  # A's dataset is not B's: scoping still decides first
    second = Project.objects.create(organization=world.org, name="Second")
    assert _report(world, "r-3", base=world.base(project=second)).status_code in {
        404,
        409,
    }

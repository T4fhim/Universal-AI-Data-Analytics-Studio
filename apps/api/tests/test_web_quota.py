# File: apps/api/tests/test_web_quota.py
"""The quotas as the API shows them: ``429 quota_exceeded`` from the upload route and job creation.

Why: the service is proven in ``test_quotas_service.py``; this proves it is *wired* -- that an
organization at its limit is refused before the file is spooled or stored, that a failed or replayed
upload gives its reservation back (the leak that would slowly lock a tenant out), that the rows and
bytes of a dataset are held while it exists and returned when it is deleted, and that the refusal
is the closed envelope code, not a 500 and not the throttle's ``rate_limited``. Each refusal has
its positive twin (the same request with room is accepted).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.uploadhandler import TemporaryFileUploadHandler
from web_support import World, error_code, make_world

from uadas_api.jobs.execution import execute_job
from uadas_api.jobs.models import Job
from uadas_api.quotas import service as quotas
from uadas_api.quotas.choices import UsageKind
from uadas_api.quotas.models import UsageLedger
from uadas_api.storage.store import get_store
from uadas_api.web.uploads import UploadHold
from uadas_api.workspaces.models import DatasetRecord

pytestmark = pytest.mark.django_db

CSV = b"name,qty\nwidget,3\ngadget,5\n"
BYTES = UsageKind.STORAGE_BYTES.value
ROWS = UsageKind.ROWS.value
SECONDS = UsageKind.JOB_SECONDS.value


@pytest.fixture
def world() -> World:
    return make_world()


@pytest.fixture(autouse=True)
def _private_sandbox_root(settings: Any, tmp_path: Path) -> None:
    root = tmp_path / "sandbox-root"
    root.mkdir()
    settings.UADAS_SANDBOX = {**settings.UADAS_SANDBOX, "tmp_root": str(root)}


def limit(settings: Any, **by_kind: int | None) -> None:
    settings.UADAS_QUOTA = {
        **settings.UADAS_QUOTA,
        **{f"max_{kind}": value for kind, value in by_kind.items()},
    }


def upload(
    world: World,
    who: str = "editor",
    name: str = "sales.csv",
    content: bytes = CSV,
    *,
    csrf: bool = True,
    key: str | None = None,
) -> Any:
    api = world.api(who)
    headers = {"X-CSRFToken": api.token} if csrf else {}
    if key is not None:
        headers["Idempotency-Key"] = key
    return api.client.post(
        f"{world.base()}/datasets/upload",
        {"file": SimpleUploadedFile(name, content, content_type="text/csv")},
        headers=headers,
    )


def stored(world: World) -> list[str]:
    return [o.key for o in get_store(world.org).list_prefix(f"{world.org.pk}/")]


def held(world: World) -> int:
    return quotas.usage_for(world.org, BYTES)


# ------------------------------------------------------------- stored bytes at upload


def test_an_upload_over_the_byte_quota_is_refused_before_anything_is_stored(
    world: World, settings: Any
) -> None:
    limit(settings, storage_bytes=len(CSV) // 2)
    before = stored(world)
    refused = upload(world)
    assert refused.status_code == 429 and error_code(refused) == "quota_exceeded"
    assert refused.json()["error"]["message"] == (
        "Your organization has reached its storage quota."
    )
    assert stored(world) == before and not Job.objects.exists()
    assert held(world) == 0 and not UsageLedger.objects.exists()


def test_an_upload_under_the_byte_quota_is_accepted_and_holds_its_bytes(
    world: World, settings: Any
) -> None:
    limit(settings, storage_bytes=10_000)
    response = upload(world)
    assert response.status_code == 202
    # The hold is the declared body length: at least the file, plus a little multipart framing.
    assert len(CSV) <= held(world) < 10_000
    # ... and it is kept under the dataset's own ledger key, not the request's hold key.
    keys = set(
        UsageLedger.objects.for_organization(world.org)
        .filter(kind=BYTES)
        .values_list("source_key", flat=True)
    )
    assert keys == {quotas.upload_key(response.json()["dataset_id"])}


def test_the_quota_refusal_is_not_the_throttles_rate_limited(
    world: World, settings: Any
) -> None:
    limit(settings, storage_bytes=1)
    assert error_code(upload(world)) == "quota_exceeded"
    settings.UADAS_API = {"throttles": {"upload": "1/60"}}
    limit(settings, storage_bytes=None)
    # The twin: the *other* 429 keeps its own code. (A different user: the refused request above
    # already counted against the editor's upload budget.)
    assert upload(world, "admin", name="a.csv").status_code == 202
    assert error_code(upload(world, "admin", name="b.csv")) == "rate_limited"


def test_the_second_upload_is_refused_when_the_first_filled_the_organization(
    world: World, settings: Any
) -> None:
    assert (
        upload(world, name="a.csv").status_code == 202
    )  # unlimited: learn what one costs
    one = held(world)
    limit(settings, storage_bytes=2 * one)  # room for exactly one more
    assert upload(world, name="b.csv").status_code == 202
    second = upload(world, name="c.csv")
    assert second.status_code == 429 and error_code(second) == "quota_exceeded"
    other = make_world()  # another organization has its own allowance
    assert upload(other, name="a.csv").status_code == 202


# ---------------------------------------------------- a failed upload releases its hold


@pytest.mark.parametrize(
    ("name", "content", "kwargs", "status"),
    [
        ("run.exe", b"MZ\x90\x00", {}, 415),  # admission: wrong type
        ("fake.pdf", CSV, {}, 415),  # admission: bytes disagree with the name
        ("ok.csv", CSV, {"csrf": False}, 403),  # CSRF refused after the body was parsed
    ],
)
def test_a_refused_upload_releases_its_reservation(
    world: World,
    settings: Any,
    name: str,
    content: bytes,
    kwargs: dict[str, Any],
    status: int,
) -> None:
    limit(settings, storage_bytes=10_000)
    refused = upload(world, name=name, content=content, **kwargs)
    assert refused.status_code == status
    assert held(world) == 0  # the hold was given back when the request closed
    ledger = UsageLedger.objects.for_organization(world.org).filter(kind=BYTES)
    assert ledger.exists() and not ledger.filter(released=False).exists()
    assert upload(world).status_code == 202  # the twin: the same org can still upload


def test_a_failing_view_releases_the_reservation(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uadas_api.web import datasets

    limit(settings, storage_bytes=10_000)

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("storage exploded")

    monkeypatch.setattr(datasets, "request_ingest", boom)
    api = world.api("editor")
    api.client.raise_request_exception = False
    failed = api.client.post(
        f"{world.base()}/datasets/upload",
        {"file": SimpleUploadedFile("a.csv", CSV, content_type="text/csv")},
        headers={"X-CSRFToken": api.token},
    )
    assert failed.status_code == 500
    assert held(world) == 0
    assert not Job.objects.exists()


def test_a_chunked_cap_breach_after_the_hold_releases_it(
    world: World, settings: Any
) -> None:
    # The declared length fits the cap, the real bytes do not: the parse raises mid-stream.
    settings.UADAS_SANDBOX = {**settings.UADAS_SANDBOX, "max_input_bytes": 2048}
    limit(settings, storage_bytes=10**7)
    refused = upload(world, content=b"a,b\n" + b"1,2\n" * 3000)
    assert refused.status_code == 413
    assert held(world) == 0
    assert upload(world).status_code == 202  # the twin, under the cap


def test_a_retried_upload_with_the_same_key_is_charged_once(
    world: World, settings: Any
) -> None:
    limit(settings, storage_bytes=10_000)
    first = upload(world, key="retry-1")
    after_first = held(world)
    second = upload(world, key="retry-1")
    assert (first.status_code, second.status_code) == (202, 202)
    assert first.json()["dataset_id"] == second.json()["dataset_id"]
    assert held(world) == after_first > 0
    third = upload(
        world, name="other.csv", key="retry-2"
    )  # a different key is new work
    assert third.status_code == 202 and held(world) > after_first


def test_the_hold_commit_and_release_are_idempotent_and_exclusive(world: World) -> None:
    quotas.reserve(world.org, BYTES, 50, "hold:a")
    hold = UploadHold(world.org.pk, "hold:a")
    hold.release()
    hold.release()
    hold.commit(__import__("uuid").uuid4())  # settled already: does nothing
    assert held(world) == 0
    quotas.reserve(world.org, BYTES, 50, "hold:b")
    keeper = UploadHold(world.org.pk, "hold:b")
    dataset_id = __import__("uuid").uuid4()
    keeper.commit(dataset_id)
    keeper.release()  # committed: not given back
    assert held(world) == 50
    assert quotas.release(world.org, BYTES, quotas.upload_key(dataset_id)) is True


def test_the_handler_does_not_hold_bytes_for_a_route_that_takes_no_file(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    limit(settings, storage_bytes=10_000)
    spooled: list[str] = []
    original = TemporaryFileUploadHandler.new_file

    def spy(self: Any, *args: Any, **kwargs: Any) -> None:
        spooled.append(args[1])
        original(self, *args, **kwargs)

    monkeypatch.setattr(TemporaryFileUploadHandler, "new_file", spy)
    assert (
        world.api("editor").post("/api/organizations", {"name": "Fine"}).status_code
        == 201
    )
    assert held(world) == 0 and not UsageLedger.objects.exists() and not spooled


# ----------------------------------------------- rows, and giving everything back


def test_ingest_charges_the_rows_and_deleting_the_dataset_returns_rows_and_bytes(
    world: World, settings: Any
) -> None:
    limit(settings, rows=100, storage_bytes=10_000)
    response = upload(world)
    assert response.status_code == 202
    body = response.json()
    assert (
        quotas.usage_for(world.org, ROWS) == 0
    )  # not known until the job has parsed it
    execute_job(body["job_id"])
    assert quotas.usage_for(world.org, ROWS) == 2
    assert held(world) > 0
    deleted = world.api("editor").delete(
        f"{world.base()}/datasets/{body['dataset_id']}"
    )
    assert deleted.status_code == 204
    assert (quotas.usage_for(world.org, ROWS), held(world)) == (0, 0)
    assert not DatasetRecord.objects.filter(pk=body["dataset_id"]).exists()


def test_a_new_upload_is_refused_once_the_rows_are_used_up(
    world: World, settings: Any
) -> None:
    limit(settings, rows=2)
    first = upload(world, name="a.csv")
    execute_job(first.json()["job_id"])  # two rows: exactly at the limit
    assert quotas.usage_for(world.org, ROWS) == 2
    refused = upload(world, name="b.csv")
    assert refused.status_code == 429 and error_code(refused) == "quota_exceeded"
    assert (
        refused.json()["error"]["message"]
        == "Your organization has reached its row quota."
    )
    assert (
        held(world) > 0 and Job.objects.count() == 1
    )  # only the first upload's hold remains
    limit(settings, rows=3)  # the twin: one row of room is enough to start another
    assert upload(world, name="c.csv").status_code == 202


def test_an_ingest_that_fails_gives_its_bytes_back(world: World, settings: Any) -> None:
    from uadas_api.ingest.service import abandon_ingest

    limit(settings, storage_bytes=10_000)
    first = upload(world, name="a.csv")
    second = upload(world, name="b.csv")
    assert first.status_code == second.status_code == 202
    both = held(world)
    # The job of the first upload ends for good without a dataset (what the worker and the
    # sweeper both call): only that upload's bytes come back.
    abandon_ingest(Job.objects.get(pk=first.json()["job_id"]))
    assert 0 < held(world) < both
    abandon_ingest(Job.objects.get(pk=first.json()["job_id"]))  # idempotent
    assert 0 < held(world) < both
    # The twin: when a dataset with that id exists, its bytes are not touched.
    execute_job(second.json()["job_id"])
    abandon_ingest(Job.objects.get(pk=second.json()["job_id"]))
    assert DatasetRecord.objects.filter(pk=second.json()["dataset_id"]).exists()
    assert held(world) > 0


# --------------------------------------------------------------- job time at creation


def test_an_upload_is_refused_when_the_months_job_time_is_used_up(
    world: World, settings: Any
) -> None:
    limit(settings, job_seconds=60, storage_bytes=10_000)
    quotas.charge(world.org, SECONDS, 60, "earlier-month-work")
    refused = upload(world)
    assert refused.status_code == 429 and error_code(refused) == "quota_exceeded"
    assert not Job.objects.exists()
    assert held(world) == 0  # the byte hold taken first was released with the request
    limit(settings, job_seconds=61)  # the twin: one second of room
    assert upload(world).status_code == 202

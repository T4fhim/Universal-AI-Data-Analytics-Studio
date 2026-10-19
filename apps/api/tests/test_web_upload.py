# File: apps/api/tests/test_web_upload.py
"""``POST .../datasets/upload``: streamed, capped, admitted, stored, then ingested by a job.

The properties that matter, each with a positive twin: the size cap is enforced *while the bytes
stream in* (the handler is unit-tested chunk by chunk, and the HTTP test shows nothing is stored or
queued for an oversized file), a file is admitted only if both its extension and its own bytes say
it is a supported type, the route is authenticated and CSRF-protected like every other, and a good
CSV travels the whole way (original in the tenant's namespace -> 202 + job -> the real sandbox child
-> a ``DatasetRecord`` with rows).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from apihelpers import Api
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest
from factories import make_user
from ninja.errors import HttpError
from web_support import World, error_code, make_world

from uadas_api.jobs.execution import execute_job
from uadas_api.jobs.models import Job
from uadas_api.storage.store import get_store
from uadas_api.web.errors import ApiError
from uadas_api.web.uploads import (
    CappedTemporaryFileUploadHandler,
    UploadTooLarge,
    max_upload_bytes,
)
from uadas_api.workspaces.models import DatasetRecord

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
    world: World,
    who: str = "editor",
    name: str = "sales.csv",
    content: bytes = CSV,
    *,
    csrf: bool = True,
    content_type: str = "text/csv",
) -> Any:
    api = world.api(who)
    headers = {"X-CSRFToken": api.token} if csrf else {}
    return api.client.post(
        f"{world.base()}/datasets/upload",
        {"file": SimpleUploadedFile(name, content, content_type=content_type)},
        headers=headers,
    )


def _stored_objects(world: World) -> list[str]:
    return [o.key for o in get_store(world.org).list_prefix(f"{world.org.pk}/")]


def test_a_csv_upload_becomes_a_dataset_through_an_ingest_job(world: World) -> None:
    before = set(_stored_objects(world))
    response = _upload(world)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    job = Job.objects.get(pk=body["job_id"])
    assert job.kind == "ingest_dataset" and job.organization_id == world.org.pk
    (original,) = set(_stored_objects(world)) - before
    assert original.startswith(
        f"{world.org.pk}/datasets/{body['dataset_id']}/original/"
    )
    head = get_store(world.org).head(original)
    assert head is not None and head.original_filename == "sales.csv"
    assert (
        head.content_type == "application/octet-stream"
    )  # never the client's declared type

    execute_job(job.pk)  # the real sandbox child parses it
    record = DatasetRecord.objects.get(pk=body["dataset_id"])
    assert (record.row_count, record.column_count, record.project_id) == (
        2,
        2,
        world.project.pk,
    )
    polled = world.api("viewer").get(f"{world.base()}/jobs/{job.pk}").json()
    assert (
        polled["status"] == "succeeded" and polled["dataset_id"] == body["dataset_id"]
    )
    preview = (
        world.api("viewer").get(f"{world.base()}/datasets/{record.pk}/preview").json()
    )
    assert preview["rows"] == [["widget", "3"], ["gadget", "5"]]


def test_the_upload_route_is_authenticated_csrf_protected_and_role_gated(
    world: World,
) -> None:
    before = _stored_objects(world)
    assert (
        _upload(world, csrf=False).status_code == 403
    )  # CSRF, like every unsafe route
    assert _upload(world, "viewer").status_code == 403
    assert _upload(world, "outsider").status_code == 404
    assert _stored_objects(world) == before and not Job.objects.exists()
    assert (
        _upload(world, "editor").status_code == 202
    )  # the twin: same request, allowed role


def test_a_file_must_be_admitted_by_extension_and_by_its_own_bytes(
    world: World,
) -> None:
    before = _stored_objects(world)
    assert _upload(world, name="run.exe", content=b"MZ\x90\x00").status_code == 415
    assert _upload(world, name="fake.pdf", content=CSV).status_code == 415
    assert _upload(world, name="empty.csv", content=b"").status_code == 422
    refused = _upload(world, name="run.exe", content=b"MZ")
    assert error_code(refused) == "unsupported_media_type"
    assert _stored_objects(world) == before and not Job.objects.exists()
    assert _upload(world, name="ok.csv").status_code == 202


def test_an_oversized_file_is_refused_and_nothing_is_stored(
    world: World, settings: Any
) -> None:
    settings.UADAS_SANDBOX = {**settings.UADAS_SANDBOX, "max_input_bytes": 2048}
    before = _stored_objects(world)
    big = b"a,b\n" + b"1,2\n" * 3000
    refused = _upload(world, content=big)
    assert refused.status_code == 413 and error_code(refused) == "payload_too_large"
    assert _stored_objects(world) == before and not Job.objects.exists()
    assert _upload(world, content=CSV).status_code == 202  # the twin, under the cap


def test_the_handler_stops_the_parse_when_the_running_total_crosses_the_cap(
    settings: Any,
) -> None:
    settings.UADAS_SANDBOX = {**settings.UADAS_SANDBOX, "max_input_bytes": 1000}
    assert max_upload_bytes() == 1000
    request = HttpRequest()
    request.user = (
        make_user()
    )  # a signed-in user: the handler parses nothing for anyone else
    handler = CappedTemporaryFileUploadHandler(request)
    handler.new_file("file", "x.csv", "text/csv", 0)
    assert handler.receive_data_chunk(b"x" * 600, 0) is None  # under the cap: accepted
    with pytest.raises(UploadTooLarge):
        handler.receive_data_chunk(
            b"x" * 600, 600
        )  # 1200 > 1000: stopped at this chunk
    handler.file.close()
    # an honest Content-Length far above the cap is refused before a byte is read
    with pytest.raises(UploadTooLarge):
        handler.handle_raw_input(None, {}, 1000 + 2 * 1024 * 1024, "b")
    handler.handle_raw_input(None, {}, 1500, "b")  # a small declared length passes


def test_an_anonymous_multipart_body_is_refused_before_any_of_it_is_parsed(
    world: World,
) -> None:
    anonymous = Api()
    refused = anonymous.client.post(
        f"{world.base()}/datasets/upload",
        {"file": SimpleUploadedFile("a.csv", CSV, content_type="text/csv")},
        headers={"X-CSRFToken": anonymous.token},
    )
    assert refused.status_code == 401 and error_code(refused) == "unauthenticated"
    request = (
        HttpRequest()
    )  # no user at all: the handler itself refuses (no temp file is opened)
    request.path_info = f"{world.base()}/datasets/upload"
    with pytest.raises(ApiError):
        CappedTemporaryFileUploadHandler(request).handle_raw_input(None, {}, 100, "b")
    assert _upload(world).status_code == 202  # the twin: a signed-in editor, same body


def test_a_stranger_to_the_organization_is_refused_before_the_body_is_parsed(
    world: World,
) -> None:
    request = HttpRequest()
    request.user = world.outsider  # signed in, but a member of nothing here
    request.path_info = f"{world.base()}/datasets/upload"
    handler = CappedTemporaryFileUploadHandler(request)
    with pytest.raises(HttpError) as refused:
        handler.handle_raw_input(None, {}, 100, "b")
    assert refused.value.status_code == 404  # the same answer as a missing organization
    request.user = world.viewer.user  # a member, but below editor
    with pytest.raises(HttpError) as too_low:
        handler.handle_raw_input(None, {}, 100, "b")
    assert too_low.value.status_code == 403
    request.user = world.editor.user  # the twin: an editor passes the gate
    handler.handle_raw_input(None, {}, 100, "b")
    request.path_info = (
        "/api/auth/browser/v1/auth/login"  # any other multipart post: only the cap
    )
    request.user = world.outsider
    handler.handle_raw_input(None, {}, 100, "b")


def test_uploads_are_throttled_per_user_and_organization(
    world: World, settings: Any
) -> None:
    settings.UADAS_API = {"throttles": {"upload": "2/60"}}
    assert _upload(world, name="a.csv").status_code == 202
    assert _upload(world, name="b.csv").status_code == 202
    limited = _upload(world, name="c.csv")
    assert limited.status_code == 429 and error_code(limited) == "rate_limited"
    assert (
        _upload(world, "admin", name="d.csv").status_code == 202
    )  # another user's budget


def test_a_json_body_is_not_an_upload(world: World) -> None:
    refused = world.api("editor").post(f"{world.base()}/datasets/upload", {"file": "x"})
    assert refused.status_code == 422

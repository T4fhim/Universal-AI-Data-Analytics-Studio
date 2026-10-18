# File: apps/api/tests/test_ingest.py
"""The ``ingest_dataset`` job: stored original in, ``DatasetRecord`` + Parquet frame out.

Why so much failure injection: the property that matters is not "a good file becomes a dataset"
but "**nothing else ever becomes one**": whichever step fails -- admission, fetch, parse, store,
commit, the job's own state change -- there is no ``DatasetRecord``, the job ends in the right
state with a fixed sentence, and what was staged (the Parquet frame, the original upload) is
deleted or queued for deletion through the 3.4 outbox. Each injection test proves it fired *at
the step it claims* (the fault's hit counter, and the sequence of backend calls) and has a
positive twin (the same job without the fault succeeds).

Two kinds of child: the **real** sandbox child (real readers, real Parquet) for the end-to-end
cases, and a **fake** child (a few lines of Python started through the runner's internal
``child_command`` seam) where the test is about the pipeline around the parse, not the parse.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import textwrap
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from factories import make_organization, make_user
from storage_support import FaultyBackend

from uadas_api.accounts.models import Membership, Role
from uadas_api.ingest import service
from uadas_api.jobs import services as job_services
from uadas_api.jobs.execution import OutcomeKind, execute_job
from uadas_api.jobs.models import Job
from uadas_api.sandbox.limits import SandboxLimits
from uadas_api.sandbox.runner import SandboxWorkspace
from uadas_api.storage import keys
from uadas_api.storage.memory import InMemoryBackend
from uadas_api.storage.models import OrphanedObject
from uadas_api.storage.store import get_store, override_backend
from uadas_api.workspaces.models import DatasetRecord, Project

pytestmark = pytest.mark.django_db

CSV = b"name,qty\nwidget,3\ngadget,5\n"
PARQUET = b"PAR1" + b"\x01" * 80 + b"PAR1"
OK_REPLY = {
    "ok": True,
    "source_format": "csv",
    "row_count": 2,
    "column_count": 2,
    "columns": [["name", "object"], ["qty", "int64"]],
    "warning_count": 0,
    "enforcement": {"memory": True, "cpu": True, "network_guard": True},
}
ALLOWED = ["text/csv", "application/pdf", "application/octet-stream"]


# ------------------------------------------------------------------------- fixtures


@pytest.fixture
def faulty() -> Iterator[FaultyBackend]:
    backend = FaultyBackend(InMemoryBackend())
    with override_backend(backend):
        yield backend


@pytest.fixture(autouse=True)
def _private_sandbox_root(settings: Any, tmp_path: Path) -> Path:
    root = tmp_path / "sandbox-root"
    root.mkdir()
    settings.UADAS_SANDBOX = {**settings.UADAS_SANDBOX, "tmp_root": str(root)}
    return root


class World:
    """An organization with an editor, a project, and helpers to upload and run ingests."""

    def __init__(self) -> None:
        self.org = make_organization()
        self.user = make_user()
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.EDITOR
        )
        self.project = Project.objects.create(organization=self.org, name="p")
        self.store = get_store(self.org.pk)

    def upload(
        self,
        data: bytes = CSV,
        *,
        filename: str = "sales.csv",
        dataset_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        dataset_id = dataset_id or uuid.uuid4()
        key = keys.dataset_original_key(self.org.pk, dataset_id)
        self.store.put(
            key,
            data,
            content_type="application/octet-stream",
            allowed_content_types=ALLOWED,
            original_filename=filename,
        )
        return {"dataset_id": dataset_id, "original_key": key, "filename": filename}

    def request(self, upload: dict[str, Any], **kw: Any) -> Job:
        return service.request_ingest(
            project=self.project,
            actor=self.user,
            content_type=kw.pop("content_type", "text/csv"),
            **upload,
            **kw,
        ).job

    def run(self, job: Job) -> OutcomeKind:
        return execute_job(job.pk).kind

    def ingest(
        self, upload: dict[str, Any] | None = None, **kw: Any
    ) -> tuple[Job, OutcomeKind]:
        upload = upload or self.upload()
        job = self.request(upload, **kw)
        outcome = self.run(job)
        job.refresh_from_db()
        return job, outcome

    def cancel_on_frame_put(self, job: Job) -> Callable[[str], None]:
        """A fault-injection hook: cancel ``job`` the moment a frame has been uploaded."""

        def hook(key: str) -> None:
            if "/frames/" in key:
                job_services.request_cancel(
                    organization=self.org, job_id=job.pk, actor=self.user
                )

        return hook

    def datasets(self) -> list[DatasetRecord]:
        return list(DatasetRecord.objects.for_organization(self.org))

    def frame_keys(self, dataset_id: Any) -> list[str]:
        prefix = keys.dataset_prefix(self.org.pk, dataset_id) + "frames/"
        return [obj.key for obj in self.store.list_prefix(prefix)]

    def queued_deletions(self) -> list[tuple[str, bool]]:
        return sorted(
            OrphanedObject.objects.for_organization(self.org).values_list(
                "storage_key", "is_prefix"
            )
        )


@pytest.fixture
def world(faulty: FaultyBackend) -> World:
    # Depends on `faulty` so the store handle the World keeps and the one the handler gets are
    # backed by the same (fault-injectable) object store.
    return World()


def fake_child(
    tmp_path: Path, reply: dict[str, Any], *, write_output: bool = True
) -> list[str]:
    script = tmp_path / f"fake_child_{uuid.uuid4().hex[:6]}.py"
    script.write_text(
        textwrap.dedent(f"""
            import sys
            sys.stdin.buffer.read()
            if {write_output!r}:
                open("out.parquet", "wb").write({PARQUET!r})
            print({json.dumps(reply)!r})
            """),
        encoding="utf-8",
    )
    return [sys.executable, "-I", str(script)]


def use_child(monkeypatch: pytest.MonkeyPatch, command: list[str]) -> None:
    real = SandboxWorkspace

    def factory(limits: SandboxLimits | None = None) -> SandboxWorkspace:
        return real(limits, child_command=command, require_enforcement=False)

    monkeypatch.setattr(service, "SandboxWorkspace", factory)


def forbid_parse(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make any attempt to start the sandbox a test failure; returns the list it would append to."""
    started: list[str] = []

    def parse(self: SandboxWorkspace, extension: str) -> Any:
        started.append(extension)
        raise AssertionError("the sandbox must not be started for this job")

    monkeypatch.setattr(SandboxWorkspace, "parse", parse)
    return started


def sandbox_dirs(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


# ==================================================================== parameters


def test_valid_parameters_are_normalised(world: World) -> None:
    upload = world.upload()
    params = service.validate_params(
        world.org.pk,
        {
            **upload,
            "dataset_id": str(upload["dataset_id"]).upper(),
            "content_type": "Text/CSV; charset=utf-8",
        },
    )
    assert params == {
        "dataset_id": str(upload["dataset_id"]),
        "original_key": upload["original_key"],
        "filename": "sales.csv",
        "content_type": "text/csv",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p, w: {**p, "dataset_id": "not-a-uuid"},
        lambda p, w: {
            **p,
            "original_key": f"{uuid.uuid4()}/datasets/{p['dataset_id']}/original/abc",
        },
        lambda p, w: {
            **p,
            "original_key": keys.dataset_original_key(w.org.pk, uuid.uuid4()),
        },
        lambda p, w: {
            **p,
            "original_key": f"{w.org.pk}/datasets/{p['dataset_id']}/frames/x.parquet",
        },
        lambda p, w: {
            **p,
            "original_key": f"{w.org.pk}/datasets/{p['dataset_id']}/original/../../x",
        },
        lambda p, w: {**p, "original_key": ""},
        lambda p, w: {**p, "filename": "malware.exe"},
        lambda p, w: {**p, "filename": "noextension"},
        lambda p, w: {**p, "filename": "a" * 300 + ".csv"},
        lambda p, w: {**p, "filename": "bad\x00name.csv"},
        lambda p, w: {**p, "content_type": "not a media type"},
        lambda p, w: {**p, "content_type": ""},
        lambda p, w: {**p, "extra": "field"},
        lambda p, w: {k: v for k, v in p.items() if k != "filename"},
    ],
    ids=[
        "bad-id",
        "other-org-key",
        "other-dataset-key",
        "frames-key",
        "traversal",
        "empty-key",
        "exe",
        "no-extension",
        "long-name",
        "nul-in-name",
        "bad-content-type",
        "empty-content-type",
        "unknown-field",
        "missing-field",
    ],
)
def test_bad_parameters_are_refused_before_a_job_exists(
    world: World, mutate: Callable[[dict[str, Any], World], dict[str, Any]]
) -> None:
    upload = {**world.upload(), "content_type": "text/csv"}
    with pytest.raises(ValidationError):
        service.validate_params(world.org.pk, mutate(upload, world))
    # the positive twin: the unmutated parameters pass
    service.validate_params(world.org.pk, upload)


def test_requesting_an_ingest_twice_for_one_dataset_is_one_job(world: World) -> None:
    upload = world.upload()
    first = world.request(upload)
    second = world.request(upload)
    assert first.pk == second.pk
    assert Job.objects.for_organization(world.org).count() == 1


def test_an_explicit_idempotency_key_is_respected(world: World) -> None:
    one, two = world.upload(), world.upload()
    a = world.request(one, idempotency_key="k1")
    b = world.request(two, idempotency_key="k2")
    assert a.pk != b.pk


def test_a_viewer_cannot_request_an_ingest(world: World) -> None:
    from uadas_api.jobs.errors import JobPermissionError

    Membership.objects.filter(user=world.user).update(role=Role.VIEWER)
    with pytest.raises(JobPermissionError):
        world.request(world.upload())


# ================================================================== the happy path


def test_a_csv_becomes_a_dataset_a_frame_and_a_succeeded_job(
    world: World, tmp_path: Path, _private_sandbox_root: Path
) -> None:
    upload = world.upload()
    job, outcome = world.ingest(upload)
    assert outcome is OutcomeKind.DONE
    assert (job.status, job.progress, job.error_code) == ("succeeded", 100, "")

    (record,) = world.datasets()
    assert record.pk == upload["dataset_id"]
    assert (record.name, record.source_format) == ("sales.csv", "csv")
    assert (record.row_count, record.column_count) == (2, 2)
    assert record.project_id == world.project.pk and record.parent_dataset_id is None
    assert record.storage_key.startswith(
        f"{world.org.pk}/datasets/{upload['dataset_id']}/frames/j001-"
    )

    stored = world.store.get(record.storage_key)
    assert hashlib.sha256(stored).hexdigest() == record.sha256
    assert world.store.head(record.storage_key).content_type == "application/vnd.apache.parquet"  # type: ignore[union-attr]
    import pandas as pd  # type: ignore[import-untyped]

    frame = pd.read_parquet(io.BytesIO(stored))
    assert frame.to_dict("list") == {"name": ["widget", "gadget"], "qty": [3, 5]}

    # What the job row holds: ids, a key, a hash and counts -- nothing from the data.
    assert job.result == {
        "dataset_id": str(upload["dataset_id"]),
        "storage_key": record.storage_key,
        "sha256": record.sha256,
        "row_count": 2,
        "column_count": 2,
        "source_format": "csv",
        "size_bytes": len(stored),
    }
    assert "widget" not in json.dumps(job.result) and "qty" not in json.dumps(
        job.result
    )

    assert world.store.exists(upload["original_key"])  # the original upload is kept
    assert world.queued_deletions() == []
    assert sandbox_dirs(_private_sandbox_root) == []


def test_the_sandbox_is_where_the_parsing_happens(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = SandboxWorkspace.parse

    def spy(self: SandboxWorkspace, extension: str) -> Any:
        seen.append(extension)
        return real(self, extension)

    monkeypatch.setattr(SandboxWorkspace, "parse", spy)
    job, _ = world.ingest()
    assert job.status == "succeeded" and seen == [".csv"]


# ============================================================== redelivery / idempotency


def test_a_redelivered_message_after_success_creates_nothing_more(world: World) -> None:
    job, _ = world.ingest()
    assert world.run(job) is OutcomeKind.SKIPPED
    assert world.run(job) is OutcomeKind.SKIPPED
    assert len(world.datasets()) == 1
    assert len(world.frame_keys(job.params["dataset_id"])) == 1


def test_a_second_ingest_for_an_existing_dataset_fails_without_touching_it(
    world: World,
) -> None:
    upload = world.upload()
    first, _ = world.ingest(upload)
    existing = world.datasets()[0]
    second, _ = world.ingest(upload, idempotency_key="a-different-request")
    assert (second.status, second.error_code) == ("failed", "conflict")
    assert world.datasets() == [existing] or [d.pk for d in world.datasets()] == [
        existing.pk
    ]
    # abandoning the failed second job must NOT delete the first one's objects
    assert world.queued_deletions() == []
    assert world.store.exists(existing.storage_key)
    assert world.store.exists(upload["original_key"])
    assert first.status == "succeeded"


# ============================================================ (a) admission before parse


def test_an_unsupported_extension_never_touches_storage_or_the_sandbox(
    world: World, faulty: FaultyBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = forbid_parse(monkeypatch)
    upload = world.upload(b"MZ\x90\x00" + b"\x00" * 64, filename="payload.exe")
    faulty.calls.clear()
    # `exe` is refused at creation, so build the row the way a hand-edited database would hold it.
    job = Job.objects.create(
        organization=world.org,
        project=world.project,
        created_by=world.user,
        kind="ingest_dataset",
        idempotency_key="direct",
        params={
            "dataset_id": str(upload["dataset_id"]),
            "original_key": upload["original_key"],
            "filename": "payload.exe",
            "content_type": "application/octet-stream",
        },
    )
    assert world.run(job) is OutcomeKind.DONE
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "unsupported_type")
    assert started == []
    assert not [
        c for c in faulty.calls if c[0] in {"download", "put"}
    ]  # nothing fetched or stored
    assert world.datasets() == []


def test_a_pdf_named_csv_is_refused_after_the_fetch_and_before_the_parse(
    world: World, faulty: FaultyBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = forbid_parse(monkeypatch)
    upload = world.upload(b"%PDF-1.4\n1 0 obj\n", filename="report.csv")
    faulty.calls.clear()
    job, _ = world.ingest(upload)
    assert (job.status, job.error_code) == ("failed", "unsupported_type")
    ops = [op for op, _key in faulty.calls]
    assert "download" in ops and "put" not in ops  # fetched, inspected, stopped
    assert started == []
    assert world.datasets() == []


def test_a_zip_bomb_xlsx_is_stopped_by_admission_with_no_parse(
    world: World, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    import zipfile

    settings.UADAS_SANDBOX = {
        **settings.UADAS_SANDBOX,
        "max_decompressed_bytes": 10 * 1024 * 1024,
    }
    started = forbid_parse(monkeypatch)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<x/>")
        archive.writestr("xl/workbook.xml", "<x/>")
        archive.writestr("xl/worksheets/sheet1.xml", "0" * (40 * 1024 * 1024))
    upload = world.upload(buffer.getvalue(), filename="bomb.xlsx")
    job, _ = world.ingest(upload)
    assert (job.status, job.error_code) == ("failed", "decompression_bomb")
    assert started == []
    assert world.datasets() == []


def test_an_oversized_original_is_refused_without_downloading_it(
    world: World, faulty: FaultyBackend, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.UADAS_SANDBOX = {**settings.UADAS_SANDBOX, "max_input_bytes": 16}
    forbid_parse(monkeypatch)
    upload = world.upload(CSV)  # 26 bytes
    faulty.calls.clear()
    job, _ = world.ingest(upload)
    assert (job.status, job.error_code) == ("failed", "input_too_large")
    assert "download" not in [op for op, _key in faulty.calls]


# ==================================================================== (b) the fetch


def test_a_storage_outage_during_the_fetch_is_retried_and_then_succeeds(
    world: World, faulty: FaultyBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_child(monkeypatch, fake_child(tmp_path, OK_REPLY))
    upload = world.upload()
    faulty.fail("download", when=lambda key: key == upload["original_key"], times=1)
    job = world.request(upload)
    faulty.calls.clear()  # forget the upload of the original; only the job's own calls count
    assert world.run(job) is OutcomeKind.RETRY
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("queued", 1)
    assert faulty.rules[0].hits == 1  # the fault fired, on the download
    assert "put" not in [
        op for op, _key in faulty.calls
    ]  # ... before anything was stored
    assert world.datasets() == [] and world.queued_deletions() == []
    # the positive twin: the next attempt (fault spent) succeeds, with a *new* frame key
    assert world.run(job) is OutcomeKind.DONE
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("succeeded", 2)
    (record,) = world.datasets()
    assert "/frames/j002-" in record.storage_key


def test_a_permanent_storage_outage_ends_failed_and_the_upload_is_queued_for_deletion(
    world: World, faulty: FaultyBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_child(monkeypatch, fake_child(tmp_path, OK_REPLY))
    upload = world.upload()
    faulty.fail("download", when=lambda key: key == upload["original_key"])
    job = world.request(upload)
    outcomes = [world.run(job) for _ in range(5)]
    assert OutcomeKind.DONE in outcomes
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "storage_unavailable")
    assert world.datasets() == []
    prefix = f"{world.org.pk}/datasets/{upload['dataset_id']}"
    assert world.queued_deletions() == [
        (prefix, True)
    ]  # the outbox owes this dataset's objects


def test_a_missing_original_fails_not_found(world: World) -> None:
    upload = world.upload()
    world.store.delete(upload["original_key"])
    job, _ = world.ingest(upload)
    assert (job.status, job.error_code) == ("failed", "not_found")


# ================================================================== (c) the sandbox


def test_a_parse_error_from_the_sandbox_fails_the_job_with_nothing_stored(
    world: World, faulty: FaultyBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_child(monkeypatch, fake_child(tmp_path, {"ok": False, "code": "parse_error"}))
    upload = world.upload()
    faulty.calls.clear()
    job, _ = world.ingest(upload)
    assert (job.status, job.error_code) == ("failed", "parse_error")
    ops = [op for op, _key in faulty.calls]
    assert (
        "download" in ops and "put" not in ops
    )  # the parse ran, the store was never written
    assert world.datasets() == [] and world.frame_keys(upload["dataset_id"]) == []
    assert world.queued_deletions() == [
        (f"{world.org.pk}/datasets/{upload['dataset_id']}", True)
    ]


def test_an_unavailable_sandbox_is_retried(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_child(monkeypatch, [str(tmp_path / "no-such-python"), "-I", "x.py"])
    job = world.request(world.upload())
    assert world.run(job) is OutcomeKind.RETRY
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("queued", "")


def test_a_malformed_pdf_through_the_real_child_fails_safe_end_to_end(
    world: World, _private_sandbox_root: Path
) -> None:
    upload = world.upload(
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Typ",
        filename="broken.pdf",
    )
    job, _ = world.ingest(upload)
    assert (job.status, job.error_code) == ("failed", "parse_error")
    assert job.error_message == "The file could not be read as a table."
    assert world.datasets() == [] and world.frame_keys(upload["dataset_id"]) == []
    assert sandbox_dirs(_private_sandbox_root) == []
    # ... and a good file ingested straight afterwards works (the worker is unharmed)
    good, _ = world.ingest()
    assert good.status == "succeeded" and len(world.datasets()) == 1


# =============================================================== (d) the frame store


def test_a_failed_frame_upload_is_retried_and_leaves_no_object_or_record(
    world: World, faulty: FaultyBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_child(monkeypatch, fake_child(tmp_path, OK_REPLY))
    upload = world.upload()
    faulty.fail("put", when=lambda key: "/frames/" in key, times=1)
    job = world.request(upload)
    faulty.calls.clear()  # forget the upload of the original; only the job's own calls count
    assert world.run(job) is OutcomeKind.RETRY
    assert faulty.rules[0].hits == 1
    ops = [op for op, _key in faulty.calls]
    assert ops.index("download") < ops.index(
        "put"
    )  # the fault is at the upload, after the fetch
    assert world.frame_keys(upload["dataset_id"]) == [] and world.datasets() == []
    assert world.run(job) is OutcomeKind.DONE  # positive twin
    assert len(world.datasets()) == 1


def test_a_cancel_after_the_upload_deletes_the_frame_and_creates_no_dataset(
    world: World, faulty: FaultyBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_child(monkeypatch, fake_child(tmp_path, OK_REPLY))
    upload = world.upload()
    job = world.request(upload)
    faulty.after("put", world.cancel_on_frame_put(job))
    assert world.run(job) is OutcomeKind.DONE
    job.refresh_from_db()
    assert job.status == "cancelled"
    assert any(
        op == "put" and "/frames/" in k for op, k in faulty.calls
    )  # the frame was uploaded
    assert world.frame_keys(upload["dataset_id"]) == []  # ... and removed again
    assert world.datasets() == []


def test_a_frame_that_cannot_be_deleted_is_queued_for_deletion(
    world: World, faulty: FaultyBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_child(monkeypatch, fake_child(tmp_path, OK_REPLY))
    upload = world.upload()
    job = world.request(upload)
    faulty.fail(
        "delete", when=lambda key: "/frames/" in key
    )  # the store refuses the cleanup
    faulty.after("put", world.cancel_on_frame_put(job))
    world.run(job)
    job.refresh_from_db()
    assert job.status == "cancelled"
    frame_key = next(k for op, k in faulty.calls if op == "put" and "/frames/" in k)
    assert (frame_key, False) in world.queued_deletions()  # the outbox owes it
    assert world.datasets() == []


# ======================================================================= (e) the commit


def test_a_dataset_created_concurrently_wins_and_the_job_cleans_up_after_itself(
    world: World, faulty: FaultyBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_child(monkeypatch, fake_child(tmp_path, OK_REPLY))
    upload = world.upload()
    job = world.request(upload)
    rival_key = f"{world.org.pk}/datasets/{upload['dataset_id']}/frames/rival.parquet"

    def create_rival(key: str) -> None:
        if "/frames/" in key and "rival" not in key:
            DatasetRecord.objects.create(
                id=upload["dataset_id"],
                organization=world.org,
                project=world.project,
                name="rival",
                source_format="csv",
                storage_key=rival_key,
                row_count=1,
                column_count=1,
            )

    faulty.after("put", create_rival)
    assert world.run(job) is OutcomeKind.DONE
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "conflict")
    (record,) = world.datasets()
    assert (record.name, record.storage_key) == (
        "rival",
        rival_key,
    )  # the rival is untouched
    assert world.frame_keys(upload["dataset_id"]) == []  # our frame was removed
    assert (
        world.queued_deletions() == []
    )  # and the rival's dataset prefix is NOT condemned


def test_a_job_that_lost_its_claim_during_the_work_leaves_no_record_and_no_frame(
    world: World, faulty: FaultyBackend, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.utils import timezone

    from uadas_api.jobs.models import allow_status_write

    use_child(monkeypatch, fake_child(tmp_path, OK_REPLY))
    upload = world.upload()
    job = world.request(upload)

    def sweeper_gives_up(key: str) -> None:
        if "/frames/" in key:
            with allow_status_write():
                Job.objects.filter(pk=job.pk).update(
                    status="failed",
                    finished_at=timezone.now(),
                    error_code="worker_lost",
                )

    faulty.after("put", sweeper_gives_up)
    assert world.run(job) is OutcomeKind.SKIPPED
    job.refresh_from_db()
    assert (job.status, job.error_code) == (
        "failed",
        "worker_lost",
    )  # the sweeper's verdict stands
    assert world.datasets() == []
    assert world.frame_keys(upload["dataset_id"]) == []


def test_an_ingest_whose_creator_lost_their_role_creates_nothing_and_condemns_the_upload(
    world: World, faulty: FaultyBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = forbid_parse(monkeypatch)
    upload = world.upload()
    job = world.request(upload)
    Membership.objects.filter(user=world.user).update(role=Role.VIEWER)
    faulty.calls.clear()
    assert world.run(job) is OutcomeKind.DONE
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "forbidden")
    assert started == [] and faulty.calls == []  # not even a read
    assert world.queued_deletions() == [
        (f"{world.org.pk}/datasets/{upload['dataset_id']}", True)
    ]


# ================================================================ tenant isolation


def test_a_key_of_another_organization_in_a_stored_job_is_refused_at_run_time(
    world: World, faulty: FaultyBackend
) -> None:
    other = World()
    foreign = other.upload()
    job = Job.objects.create(
        organization=world.org,
        project=world.project,
        created_by=world.user,
        kind="ingest_dataset",
        idempotency_key="forged",
        params={
            "dataset_id": str(foreign["dataset_id"]),
            "original_key": foreign[
                "original_key"
            ],  # belongs to the other organization
            "filename": "x.csv",
            "content_type": "text/csv",
        },
    )
    faulty.calls.clear()
    assert world.run(job) is OutcomeKind.DONE
    job.refresh_from_db()
    assert job.status == "failed"
    assert world.datasets() == [] and other.datasets() == []
    assert not [
        c for c in faulty.calls if c[1] == foreign["original_key"]
    ]  # never even read
    assert other.store.exists(foreign["original_key"])  # and never condemned


# ============================ (f) the commit step itself, and workers that never come back


def _commit_faults(
    world: World,
    faulty: FaultyBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Job, dict[str, Any]]:
    use_child(monkeypatch, fake_child(tmp_path, OK_REPLY))
    upload = world.upload()
    return world.request(upload), upload


def test_a_job_that_loses_its_claim_at_the_commit_rolls_back_the_record_and_queues_the_frame(
    world: World,
    faulty: FaultyBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fault is *at* the commit: every earlier checkpoint passed, the record is created inside
    # the transaction, and only then does the conditional success update find nothing to update.
    job, upload = _commit_faults(world, faulty, tmp_path, monkeypatch)
    faulty.fail(
        "delete", when=lambda key: "/frames/" in key
    )  # the cleanup cannot delete it
    real = job_services.finish_succeeded
    reached: list[bool] = []

    def lost(*args: Any, **kwargs: Any) -> bool:
        reached.append(DatasetRecord.objects.filter(pk=upload["dataset_id"]).exists())
        return False

    monkeypatch.setattr(job_services, "finish_succeeded", lost)
    assert world.run(job) is OutcomeKind.SKIPPED
    assert reached == [
        True
    ]  # the record existed inside the transaction when it was lost ...
    assert world.datasets() == []  # ... and is gone with the rollback
    frame_key = next(k for op, k in faulty.calls if op == "put" and "/frames/" in k)
    assert (frame_key, False) in world.queued_deletions()  # the outbox owes the frame
    job.refresh_from_db()
    assert job.status == "running"  # not this worker's verdict to give
    # twin: the very same job, unfaulted, commits (a retry after the fault is gone)
    monkeypatch.setattr(job_services, "finish_succeeded", real)
    Job.objects.filter(pk=job.pk).update(heartbeat_at=None)
    assert world.run(job) is OutcomeKind.DONE
    assert len(world.datasets()) == 1


def test_a_database_error_inside_the_commit_leaves_no_record_and_condemns_the_dataset(
    world: World,
    faulty: FaultyBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from django.db import DatabaseError

    job, upload = _commit_faults(world, faulty, tmp_path, monkeypatch)

    def broken(*args: Any, **kwargs: Any) -> bool:
        raise DatabaseError("the database went away mid-transaction")

    monkeypatch.setattr(job_services, "finish_succeeded", broken)
    assert world.run(job) is OutcomeKind.DONE
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "internal_error")
    assert "database went away" not in json.dumps([job.error_message, job.message])
    assert world.datasets() == []  # rolled back
    assert world.frame_keys(upload["dataset_id"]) == []  # the frame was removed
    assert world.queued_deletions() == [
        (f"{world.org.pk}/datasets/{upload['dataset_id']}", True)
    ]


def test_a_dead_workers_job_failed_by_the_sweeper_queues_its_objects(
    world: World, faulty: FaultyBackend
) -> None:
    from dataclasses import replace
    from datetime import timedelta

    from django.utils import timezone

    from uadas_api.jobs.config import get_config

    upload = world.upload()
    job = world.request(upload)
    started = timezone.now() - timedelta(hours=1)
    claimed = job_services.claim(job.pk, now=started, stale_after=120)
    assert claimed is not None
    # the worker had staged a frame and then was killed (OOM, a hard time limit)
    staged = keys.dataset_frame_key(
        world.org.pk, upload["dataset_id"], f"j001-{job.pk.hex}"
    )
    world.store.put(
        staged,
        b"PAR1" + b"\x00" * 16 + b"PAR1",
        content_type="application/vnd.apache.parquet",
        allowed_content_types=["application/vnd.apache.parquet"],
    )
    Job.objects.filter(pk=job.pk).update(attempts=3, heartbeat_at=started)
    report = job_services.sweep_stale(config=replace(get_config(), max_attempts=3))
    assert report.failed == 1
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "worker_lost")
    # the whole dataset directory (the original upload and the staged frame) is owed deletion
    assert world.queued_deletions() == [
        (f"{world.org.pk}/datasets/{upload['dataset_id']}", True)
    ]
    assert world.datasets() == []


def test_a_job_cancelled_while_queued_queues_the_upload(world: World) -> None:
    upload = world.upload()
    job = world.request(upload)
    outcome = job_services.request_cancel(
        organization=world.org, job_id=job.pk, actor=world.user
    )
    assert outcome is job_services.CancelOutcome.CANCELLED
    assert world.queued_deletions() == [
        (f"{world.org.pk}/datasets/{upload['dataset_id']}", True)
    ]


def test_a_requeued_job_after_a_sweeper_pass_is_not_condemned(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Twin: a stale job with attempts left is requeued, and its objects are NOT queued.
    from datetime import timedelta

    from django.utils import timezone

    from uadas_api.jobs import queue as job_queue

    monkeypatch.setattr(
        job_queue, "enqueue", lambda job_id: None
    )  # do not run it eagerly

    upload = world.upload()
    job = world.request(upload)
    started = timezone.now() - timedelta(hours=1)
    assert job_services.claim(job.pk, now=started, stale_after=120) is not None
    Job.objects.filter(pk=job.pk).update(heartbeat_at=started)
    assert job_services.sweep_stale().requeued == 1
    assert world.queued_deletions() == []


def test_the_frames_of_a_crashed_earlier_attempt_are_queued_when_a_later_attempt_commits(
    world: World,
    faulty: FaultyBackend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import timedelta

    from django.utils import timezone

    use_child(monkeypatch, fake_child(tmp_path, OK_REPLY))
    upload = world.upload()
    job = world.request(upload)
    long_ago = timezone.now() - timedelta(hours=2)
    assert (
        job_services.claim(job.pk, now=long_ago, stale_after=120) is not None
    )  # attempt 1
    crashed = keys.dataset_frame_key(
        world.org.pk, upload["dataset_id"], f"j001-{job.pk.hex}"
    )
    world.store.put(
        crashed,
        b"PAR1" + b"\x00" * 16 + b"PAR1",
        content_type="application/vnd.apache.parquet",
        allowed_content_types=["application/vnd.apache.parquet"],
    )
    Job.objects.filter(pk=job.pk).update(
        heartbeat_at=long_ago
    )  # the worker is long gone
    assert world.run(job) is OutcomeKind.DONE  # attempt 2 takes over and succeeds
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("succeeded", 2)
    (record,) = world.datasets()
    assert "/frames/j002-" in record.storage_key
    assert (
        crashed,
        False,
    ) in world.queued_deletions()  # attempt 1's frame is owed deletion
    assert (
        record.storage_key,
        False,
    ) not in world.queued_deletions()  # attempt 2's is kept
    assert world.store.exists(record.storage_key)

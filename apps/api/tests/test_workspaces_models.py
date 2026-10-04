# File: apps/api/tests/test_workspaces_models.py
"""Workspace models: projects, dataset records, chart specs, dashboards.

Why: the tenant harness proves the isolation properties every tenant model shares; this
file pins what is specific to the workspace models and mirrors the core's rules. The two
that matter most: ``parent_dataset_id`` is a *plain UUID, not a foreign key* (the core's
non-cascade lineage rule -- deleting a dataset leaves its children's pointer dangling by
design), and ``storage_key`` must live under the organization's own prefix (the only thing
separating tenants' files in a shared bucket).
"""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import ProtectedError
from factories import factory_for, make_organization, make_user

from uadas_api.accounts.models import Organization
from uadas_api.tenancy import validate_storage_key
from uadas_api.workspaces.choices import ChartType, SourceFormat
from uadas_api.workspaces.models import ChartSpec, Dashboard, DatasetRecord, Project

pytestmark = pytest.mark.django_db


def _dataset(org: Organization, **kw: object) -> DatasetRecord:
    return factory_for(DatasetRecord).create(org, **kw)


# --------------------------------------------------------------------- Project


def test_project_name_is_unique_per_organization_only() -> None:
    org_a, org_b = make_organization(), make_organization()
    Project.objects.create(organization=org_a, name="Sales")
    Project.objects.create(organization=org_b, name="Sales")  # other tenant: fine
    with pytest.raises(IntegrityError), transaction.atomic():
        Project.objects.create(organization=org_a, name="Sales")


def test_project_records_its_creator_and_survives_the_creators_deletion() -> None:
    org, user = make_organization(), make_user()
    project = Project.objects.create(organization=org, name="p", created_by=user)
    user.delete()
    project.refresh_from_db()
    assert project.created_by is None


# ---------------------------------------------------------------- DatasetRecord


def test_dataset_record_id_can_be_the_core_dataset_id() -> None:
    org = make_organization()
    core_dataset_id = str(
        uuid.uuid4()
    )  # what uadas_core's Dataset.dataset_id looks like
    record = _dataset(org, id=core_dataset_id)
    assert str(DatasetRecord.objects.get(pk=core_dataset_id).pk) == core_dataset_id
    assert record.pk == uuid.UUID(core_dataset_id) or str(record.pk) == core_dataset_id


def test_parent_dataset_id_is_a_plain_uuid_not_a_foreign_key() -> None:
    field = DatasetRecord._meta.get_field("parent_dataset_id")
    assert isinstance(field, models.UUIDField)
    assert not field.is_relation
    assert field.null is True


def test_deleting_a_dataset_leaves_a_childs_parent_pointer_intact() -> None:
    """The core's non-cascade rule: an orphaned parent_dataset_id is normal, not corruption."""
    org = make_organization()
    parent = _dataset(org)
    child = _dataset(
        org,
        project=parent.project,
        parent_dataset_id=parent.pk,
        derivation_description="dropped rows with nulls",
    )
    parent_pk = parent.pk

    parent.delete()

    child.refresh_from_db()
    assert child.parent_dataset_id == parent_pk  # not nulled, not cascaded
    assert DatasetRecord.objects.filter(pk=child.pk).exists()
    assert not DatasetRecord.objects.filter(pk=parent_pk).exists()


def test_a_parent_that_was_never_saved_is_also_fine() -> None:
    org = make_organization()
    child = _dataset(org, parent_dataset_id=uuid.uuid4())
    assert DatasetRecord.objects.get(pk=child.pk).parent_dataset_id is not None


def test_a_dataset_cannot_be_its_own_parent() -> None:
    org = make_organization()
    record = _dataset(org)
    record.parent_dataset_id = record.pk
    with pytest.raises(IntegrityError), transaction.atomic():
        record.save()


def test_deleting_a_dataset_detaches_chart_specs_without_deleting_them() -> None:
    org = make_organization()
    dataset = _dataset(org)
    chart = factory_for(ChartSpec).create(org, project=dataset.project, dataset=dataset)
    dataset.delete()
    chart.refresh_from_db()
    assert chart.dataset is None
    assert chart.spec  # the chart description survived


@pytest.mark.parametrize("field", ["row_count", "column_count"])
def test_counts_cannot_be_negative(field: str) -> None:
    org = make_organization()
    record = factory_for(DatasetRecord).build(org, **{field: -1})
    with pytest.raises(IntegrityError), transaction.atomic():
        record.save()


def test_counts_are_big_integers_and_zero_is_allowed() -> None:
    assert isinstance(
        DatasetRecord._meta.get_field("row_count"), models.PositiveBigIntegerField
    )
    assert isinstance(
        DatasetRecord._meta.get_field("column_count"), models.PositiveBigIntegerField
    )
    org = make_organization()
    record = _dataset(
        org, row_count=0, column_count=0, source_format=SourceFormat.PARQUET
    )
    assert (record.row_count, record.column_count) == (0, 0)


def test_a_project_that_still_owns_datasets_cannot_be_deleted() -> None:
    org = make_organization()
    dataset = _dataset(org)
    with pytest.raises(ProtectedError):
        dataset.project.delete()
    assert Project.objects.filter(pk=dataset.project.pk).exists()


# ---------------------------------------------------------------- storage keys


def test_storage_key_must_start_with_the_organization_prefix() -> None:
    org = make_organization()
    good = factory_for(DatasetRecord).build(
        org, storage_key=f"{org.pk}/datasets/a.parquet"
    )
    good.save()

    bad = factory_for(DatasetRecord).build(org, storage_key="datasets/a.parquet")
    with pytest.raises(ValidationError) as excinfo:
        bad.save()
    assert "storage_key" in excinfo.value.error_dict
    assert not DatasetRecord.objects.filter(pk=bad.pk).exists()


def test_storage_key_prefix_is_the_organization_id_with_a_slash() -> None:
    org = make_organization()
    # the bare id without the separator is a *different* prefix ("<id>x/..." would match it)
    sneaky = factory_for(DatasetRecord).build(
        org, storage_key=f"{org.pk}x/file.parquet"
    )
    with pytest.raises(ValidationError):
        sneaky.save()


def test_another_organizations_prefix_is_rejected() -> None:
    org_a, org_b = make_organization(), make_organization()
    row = factory_for(DatasetRecord).build(
        org_a, storage_key=f"{org_b.pk}/file.parquet"
    )
    with pytest.raises(ValidationError):
        row.save()


def test_full_clean_reports_a_bad_storage_key_against_the_field() -> None:
    org = make_organization()
    row = factory_for(DatasetRecord).build(org, storage_key="elsewhere/x.parquet")
    with pytest.raises(ValidationError) as excinfo:
        row.full_clean()
    assert "storage_key" in excinfo.value.error_dict


def test_blank_storage_key_is_rejected_for_a_dataset_record() -> None:
    org = make_organization()
    row = factory_for(DatasetRecord).build(org, storage_key="")
    with pytest.raises(ValidationError):
        row.save()


@pytest.mark.parametrize(
    "tail",
    ["../other/x.parquet", "a/../../x", "a/./b", "a//b", "a/b/", "a\\b", "a\x00b", ""],
)
def test_validate_storage_key_rejects_traversal_and_malformed_keys(tail: str) -> None:
    org_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        validate_storage_key(org_id, f"{org_id}/{tail}")


@pytest.mark.parametrize("tail", ["x.parquet", "datasets/2026/a-b_c.parquet", "a.b.c"])
def test_validate_storage_key_accepts_plain_keys(tail: str) -> None:
    org_id = uuid.uuid4()
    validate_storage_key(org_id, f"{org_id}/{tail}")


def test_validate_storage_key_accepts_the_id_in_any_uuid_spelling() -> None:
    org_id = uuid.uuid4()
    validate_storage_key(str(org_id), f"{org_id}/x")
    validate_storage_key(org_id.hex, f"{org_id}/x")


def test_blank_is_only_allowed_when_asked_for() -> None:
    org_id = uuid.uuid4()
    validate_storage_key(org_id, "", allow_blank=True)  # the "no object yet" case
    with pytest.raises(ValidationError):
        validate_storage_key(org_id, "")


@pytest.mark.parametrize(
    "tail",
    [
        "%2e%2e/x",  # percent-encoded traversal
        "%2E%2E",
        ".. /x",  # ".." followed by a space: some stores/filesystems trim it
        "a/.. /b",
        "a /b",  # segment ending in a space
        "trailing./b",  # segment ending in a dot (Windows strips it)
        "a./b",
        "...",
        "․․/x",  # ONE DOT LEADER lookalikes
        "．．/x",  # FULLWIDTH FULL STOP lookalikes
        "café.parquet",  # non-ASCII
        "a\tb",
        "a\nb",
        "a:b",
        "a*b",
        "a?b",
        "a b",
        "a;b",
        "~root",
    ],
)
def test_validate_storage_key_rejects_tricky_segments(tail: str) -> None:
    org_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        validate_storage_key(org_id, f"{org_id}/{tail}")


@pytest.mark.parametrize(
    "tail",
    ["a_b-c.d", "A1/b2/C3.csv", ".hidden", "x" * 200, "2026-10-04/file.v2.parquet"],
)
def test_validate_storage_key_accepts_ordinary_segments(tail: str) -> None:
    org_id = uuid.uuid4()
    validate_storage_key(org_id, f"{org_id}/{tail}")


def test_a_key_cannot_hide_a_trailing_newline_from_the_character_check() -> None:
    org_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        validate_storage_key(org_id, f"{org_id}/file.parquet\n")


# --------------------------------------------------------- ChartSpec, Dashboard


def test_chart_spec_stores_the_chart_name_and_parameters() -> None:
    org = make_organization()
    chart = factory_for(ChartSpec).create(
        org, chart_type=ChartType.SCATTER, spec={"x_column": "a", "y_column": "b"}
    )
    loaded = ChartSpec.objects.get(pk=chart.pk)
    assert loaded.chart_type == "scatter"
    assert loaded.spec == {"x_column": "a", "y_column": "b"}


def test_chart_spec_dataset_is_optional() -> None:
    org = make_organization()
    chart = factory_for(ChartSpec).create(org)
    assert chart.dataset is None


def test_dashboard_layout_round_trips_a_tile_grid() -> None:
    org = make_organization()
    layout = {"tiles": [{"visualization_id": str(uuid.uuid4()), "row": 0, "column": 1}]}
    dash = factory_for(Dashboard).create(org, layout=layout)
    assert Dashboard.objects.get(pk=dash.pk).layout == layout


def test_deleting_a_project_removes_its_charts_and_dashboards() -> None:
    org = make_organization()
    project = factory_for(Project).create(org)
    factory_for(ChartSpec).create(org, project=project)
    factory_for(Dashboard).create(org, project=project)
    project.delete()
    assert not ChartSpec.objects.filter(project_id=project.pk).exists()
    assert not Dashboard.objects.filter(project_id=project.pk).exists()


# ------------------------------------------------------------------- tenancy


def test_a_dataset_cannot_hang_off_another_organizations_project() -> None:
    org_a, org_b = make_organization(), make_organization()
    foreign_project = factory_for(Project).create(org_b)
    with pytest.raises(ValidationError):
        factory_for(DatasetRecord).create(org_a, project=foreign_project)

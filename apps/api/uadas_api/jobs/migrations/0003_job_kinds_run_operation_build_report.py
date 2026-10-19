# File: apps/api/uadas_api/jobs/migrations/0003_job_kinds_run_operation_build_report.py
# Phase 3.6: two new job kinds (``run_operation``, ``build_report``). The kind set is a CHECK
# constraint as well as the field's choices, so the constraint is replaced with the wider one.

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("jobs", "0002_job_not_before"),
        ("workspaces", "0002_datasetrecord_sha256_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="job",
            name="ck_job_kind",
        ),
        migrations.AlterField(
            model_name="job",
            name="kind",
            field=models.CharField(
                choices=[
                    ("ingest_dataset", "Ingest dataset"),
                    ("run_operation", "Run a stage operation"),
                    ("build_report", "Build a report"),
                ],
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("kind__in", ["ingest_dataset", "run_operation", "build_report"])
                ),
                name="ck_job_kind",
            ),
        ),
    ]

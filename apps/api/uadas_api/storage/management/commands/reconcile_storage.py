# File: apps/api/uadas_api/storage/management/commands/reconcile_storage.py
"""``manage.py reconcile_storage <organization-id>``: a read-only rows-vs-objects report.

Why: no transaction spans PostgreSQL and the bucket, so a crash can leave a row without its
object or an object without its row. This prints the facts as JSON and exits non-zero if
there are any discrepancies, so it can run on a schedule. It never deletes or repairs
anything: what to do about a finding (restore, delete, re-upload) is a human or a
separate, explicit step. ``--min-age`` skips objects younger than that many seconds, because
an upload in flight looks like a leak until its row commits.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from uadas_api.storage.lifecycle import reconcile_tenant_storage


class Command(BaseCommand):
    help = "Report an organization's rows without objects and objects without rows (read-only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("organization", help="Organization id (UUID).")
        parser.add_argument(
            "--min-age",
            type=int,
            default=0,
            help="Ignore objects newer than this many seconds (default 0).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            organization = uuid.UUID(options["organization"])
        except ValueError:
            raise CommandError("organization must be a UUID") from None
        report = reconcile_tenant_storage(
            organization, min_age_seconds=options["min_age"]
        )
        self.stdout.write(json.dumps(asdict(report), indent=2, sort_keys=True))
        if report.rows_without_objects or report.objects_without_rows:
            raise CommandError("discrepancies found (see the report above)")

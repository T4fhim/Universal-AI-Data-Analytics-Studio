# File: apps/api/uadas_api/storage/management/commands/purge_orphaned_objects.py
"""``manage.py purge_orphaned_objects``: the sweeper for the orphan queue.

Why: objects are deleted after the commit that made them garbage, and that deletion can fail
(the store was down) or never run (the process died). The owed entries are durable
(``OrphanedObject``); this command retries them. Run it from cron or a worker every few
minutes. Idempotent and safe to run concurrently with itself and with live traffic.

Exit status: 0 when every selected entry was paid or deliberately deferred, non-zero when
any failed -- so a scheduler can alert on a store that stays unreachable.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from uadas_api.storage.lifecycle import purge_orphaned_objects


class Command(BaseCommand):
    help = "Delete the stored objects whose deletion is owed (see uadas_api.storage.lifecycle)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--organization", help="Only this organization's entries (UUID)."
        )
        parser.add_argument(
            "--limit", type=int, default=200, help="At most this many entries per run."
        )
        parser.add_argument(
            "--min-age",
            type=int,
            default=None,
            help=(
                "Grace period in seconds: an owed deletion waits until its debt is this old, "
                "and a directory purge skips objects younger than this (they may be an upload "
                "in flight). Default: STORAGE_GC_GRACE_SECONDS (one hour)."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        organization = options["organization"]
        if organization is not None:
            try:
                organization = uuid.UUID(organization)
            except ValueError:
                raise CommandError("--organization must be a UUID") from None
        if options["limit"] < 1:
            raise CommandError("--limit must be positive")
        if options["min_age"] is not None and options["min_age"] < 0:
            raise CommandError("--min-age must not be negative")
        report = purge_orphaned_objects(
            organization, limit=options["limit"], min_age_seconds=options["min_age"]
        )
        self.stdout.write(
            f"deleted={report.deleted} failed={report.failed} deferred={report.deferred}"
        )
        if report.failed:
            raise CommandError(
                f"{report.failed} owed deletion(s) failed; they stay queued"
            )

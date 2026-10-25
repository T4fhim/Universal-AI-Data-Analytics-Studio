# File: apps/api/uadas_api/jobs/management/commands/sweep_jobs.py
"""``manage.py sweep_jobs``: run the stale-job sweeper once.

Why a command beside the periodic task: the sweeper is the safety net for lost broker messages
and dead workers, so it must be runnable without a working Celery beat -- from cron, a
Kubernetes CronJob, or by hand after an incident. It is idempotent (see
:func:`uadas_api.jobs.services.sweep_stale`), so overlapping runs and a beat running alongside
are harmless. Prints one ``key=value`` line (what a log scraper wants) and exits 0; a broker
outage is counted (``send_failures``), not fatal -- the next run retries.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from uadas_api.jobs.services import sweep_stale


class Command(BaseCommand):
    """Repair stale ``running`` jobs and re-send lost ``queued`` ones."""

    help = "Requeue or fail jobs whose worker died, and re-send queued jobs whose message was lost."

    def handle(self, *args: Any, **options: Any) -> None:
        report = sweep_stale()
        self.stdout.write(
            f"requeued={report.requeued} failed={report.failed} "
            f"cancelled={report.cancelled} resent={report.resent} "
            f"send_failures={report.send_failures}"
        )

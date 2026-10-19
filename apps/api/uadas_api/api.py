# File: apps/api/uadas_api/api.py
"""The Django Ninja API object and its router wiring.

Why one module: every endpoint is mounted on this single :data:`api`, so the OpenAPI
contract (``/api/openapi.json``, later consumed by Schemathesis and the web client's
type generation) has exactly one source. Feature apps each contribute a router and are
attached in :func:`_wire_routers`: the liveness router (3.1) and the accounts router (3.3).

**Authentication is the default, not an opt-in.** The API is built with
``auth=session_auth`` (session cookie + CSRF), so a router added later is protected unless
it says otherwise; the one public route, the liveness probe, opts out with ``auth=None``.
This matters because Django Ninja exempts every view from Django's CSRF middleware and
leaves the check to the auth class: a route with no auth has neither authentication *nor*
CSRF protection. ``tests/test_api_auth_guard.py`` fails if any other operation is public.
Sign-in itself (signup, login, logout, password reset, OAuth) is allauth headless, mounted
at ``/api/auth/`` in ``urls.py``.

The interactive docs UI is a development convenience and is served only when
``DEBUG`` is on (``docs_url=None`` removes the route entirely in production).
"""

from __future__ import annotations

from typing import Literal

from django.conf import settings
from ninja import NinjaAPI, Router, Schema

from uadas_api.accounts.api import router as accounts_router
from uadas_api.accounts.security import session_auth
from uadas_api.web.assistant import router as assistant_router
from uadas_api.web.charts import router as charts_router
from uadas_api.web.dashboards import router as dashboards_router
from uadas_api.web.datasets import router as datasets_router
from uadas_api.web.datasets import upload_router
from uadas_api.web.errors import install_error_handlers
from uadas_api.web.job_events import router as job_events_router
from uadas_api.web.jobs import router as jobs_router
from uadas_api.web.pipeline import router as pipeline_router
from uadas_api.web.projects import router as projects_router
from uadas_api.web.reports import router as reports_router
from uadas_api.web.stages import STAGE_ROUTERS

health_router = Router(tags=["health"])


class HealthOut(Schema):
    """Body of ``GET /api/health``."""

    status: Literal["ok"]


@health_router.get(
    "/health",
    response=HealthOut,
    summary="Liveness probe",
    operation_id="health",
    auth=None,
)
def health(request: object) -> HealthOut:
    """Report that the process is up.

    Liveness only, by design: it must not touch the database (or any other
    dependency), so an outage of one never gets a healthy API process killed and
    restarted by the orchestrator. Readiness checks, if ever needed, are a separate
    endpoint.
    """
    return HealthOut(status="ok")


def _wire_routers(target: NinjaAPI) -> None:
    """Attach every router to ``target`` (one line per feature app, added as they land).

    Each router declares its full ``/organizations/{org_id}/...`` paths, so all mount at "".
    The per-stage routers come from the core's ``PipelineStage`` enum (``web.stages``).
    """
    target.add_router("", health_router)
    target.add_router("", accounts_router)
    for module_router in (
        projects_router,
        upload_router,  # before datasets_router: see web/datasets.py
        datasets_router,
        jobs_router,
        job_events_router,  # 3.7: SSE (async views)
        assistant_router,  # 3.7: SSE (async views)
        pipeline_router,
        charts_router,
        dashboards_router,
        reports_router,
        *STAGE_ROUTERS.values(),
    ):
        target.add_router("", module_router)


def build_api(*, debug: bool) -> NinjaAPI:
    """Build the API object; the schema and docs routes exist only when ``debug``.

    An unauthenticated ``/api/openapi.json`` in production hands an attacker the full
    endpoint map, so the route is removed rather than guarded. The contract itself is
    produced offline (``api.get_openapi_schema()``) for the committed schema and the
    web client's type generation.
    """
    built = NinjaAPI(
        title="UADAS API",
        version="0.0.0",
        auth=session_auth,
        docs_url="/docs" if debug else None,
        openapi_url="/openapi.json" if debug else None,
    )
    install_error_handlers(built)
    _wire_routers(built)
    return built


api = build_api(debug=settings.DEBUG)

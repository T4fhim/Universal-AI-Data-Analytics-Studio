# File: apps/api/uadas_api/api.py
"""The Django Ninja API object and its router wiring.

Why one module: every endpoint is mounted on this single :data:`api`, so the OpenAPI
contract (``/api/openapi.json``, later consumed by Schemathesis and the web client's
type generation) has exactly one source. Feature apps will each contribute a router
and be attached in :func:`_wire_routers`; 3.1 ships only the liveness router.

The interactive docs UI is a development convenience and is served only when
``DEBUG`` is on (``docs_url=None`` removes the route entirely in production).
"""

from __future__ import annotations

from typing import Literal

from django.conf import settings
from ninja import NinjaAPI, Router, Schema

health_router = Router(tags=["health"])


class HealthOut(Schema):
    """Body of ``GET /api/health``."""

    status: Literal["ok"]


@health_router.get(
    "/health",
    response=HealthOut,
    summary="Liveness probe",
    operation_id="health",
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
    """Attach every router to ``target`` (one line per feature app, added as they land)."""
    target.add_router("", health_router)


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
        docs_url="/docs" if debug else None,
        openapi_url="/openapi.json" if debug else None,
    )
    _wire_routers(built)
    return built


api = build_api(debug=settings.DEBUG)

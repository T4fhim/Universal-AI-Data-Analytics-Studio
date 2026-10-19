# File: apps/api/tests/test_web_openapi.py
"""The committed OpenAPI 3.1 contract: complete, typed, deterministic, and drift-checked.

CI regenerates ``apps/api/openapi.json`` and fails on any difference; this file is the same check in
the test suite plus the structural promises the web client (Phase 4.1's generated TypeScript) relies
on: every operation has a unique ``operationId`` and a tag, every success response and request body is
typed, and every 4xx is the one error envelope. The drift test demonstrates it *fails* when the
schema and the committed copy disagree (the positive twin: an identical copy passes).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from uadas_api.api import api
from uadas_api.web import openapi as export
from uadas_api.web.errors import CODE_FOR_STATUS, ErrorCode
from uadas_core.services.analysis_orchestrator_service import PipelineStage

# Ninja keys responses by int status; a consumer of the committed file sees the JSON round trip.
SCHEMA = json.loads(export.schema_text(api.get_openapi_schema()))
OPERATIONS = [
    (method, path, op)
    for path, item in SCHEMA["paths"].items()
    for method, op in item.items()
]


def test_the_committed_schema_is_exactly_what_the_routes_generate() -> None:
    committed = export.COMMITTED_PATH.read_text(encoding="utf-8")
    assert committed == export.schema_text(
        SCHEMA
    ), "apps/api/openapi.json is stale: run `python -m uadas_api.web.openapi` from apps/api"


def test_the_export_is_deterministic_and_canonical() -> None:
    text = export.schema_text(api.get_openapi_schema())
    assert text == export.schema_text(api.get_openapi_schema())
    assert text.endswith("}\n") and not text.endswith("\n\n") and "\r" not in text
    assert json.loads(text) == SCHEMA
    assert (
        text == json.dumps(SCHEMA, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def test_drift_is_detected_and_an_identical_copy_passes(tmp_path: Path) -> None:
    same = tmp_path / "same.json"
    same.write_text(export.COMMITTED_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    assert export.main(["--check", "--committed", str(same)]) == 0

    drifted = copy.deepcopy(SCHEMA)
    drifted["paths"]["/api/organizations/{org_id}/projects"]["get"][
        "operationId"
    ] = "renamed"
    stale = tmp_path / "stale.json"
    stale.write_text(export.schema_text(drifted), encoding="utf-8")
    assert (
        export.main(["--check", "--committed", str(stale)]) == 1
    )  # a changed route fails
    missing = tmp_path / "missing.json"
    assert (
        export.main(["--check", "--committed", str(missing)]) == 1
    )  # no committed file fails


def test_it_is_openapi_3_1_and_every_operation_is_identified_and_tagged() -> None:
    assert SCHEMA["openapi"].startswith("3.1")
    ids = [op["operationId"] for _, _, op in OPERATIONS]
    assert len(ids) == len(set(ids)) and all(ids)
    for method, path, op in OPERATIONS:
        assert op["tags"], (method, path)
        assert op["summary"], (method, path)


def test_stage_routes_are_tagged_with_their_stage() -> None:
    for stage in PipelineStage:
        tagged = [op for _, path, op in OPERATIONS if f"/stages/{stage.value}/" in path]
        assert tagged, stage
        assert all(op["tags"] == [stage.value] for op in tagged), stage


def test_every_error_response_is_the_envelope_and_every_protected_route_documents_401() -> (
    None
):
    envelope = {"$ref": "#/components/schemas/ErrorOut"}
    for method, path, op in OPERATIONS:
        if op["operationId"] == "health":
            continue
        responses = op["responses"]
        assert "401" in responses, (method, path)
        for status, response in responses.items():
            if int(status) >= 400:
                assert response["content"]["application/json"]["schema"] == envelope, (
                    method,
                    path,
                    status,
                )
        if "/organizations/{org_id}/projects" in path:
            assert {"401", "403", "404", "422"} <= set(responses), (method, path)


def test_the_error_code_set_in_the_schema_is_the_closed_set() -> None:
    codes = SCHEMA["components"]["schemas"]["ErrorBody"]["properties"]["code"]["enum"]
    assert set(codes) == {c.value for c in ErrorCode}
    assert {c.value for c in CODE_FOR_STATUS.values()} <= set(codes)


def _is_typed(schema: Any) -> bool:
    return isinstance(schema, dict) and bool(schema) and schema != {"type": "object"}


def test_request_bodies_and_success_responses_are_typed() -> None:
    for method, path, op in OPERATIONS:
        body = op.get("requestBody")
        if body:
            content = next(iter(body["content"].values()))
            assert _is_typed(content["schema"]), (method, path)
        for status, response in op["responses"].items():
            if status.startswith("2") and status != "204":
                content = response["content"]["application/json"]
                assert _is_typed(content["schema"]), (method, path, status)


@pytest.mark.parametrize(
    "name",
    [
        "PageParams",
        "Page_ProjectOut_",
        "StageResultOut",
        "ErrorOut",
        "RunIn",
        "UploadAcceptedOut",
    ],
)
def test_the_shared_schemas_exist(name: str) -> None:
    assert name in SCHEMA["components"]["schemas"]


def test_list_endpoints_declare_the_capped_page_parameters() -> None:
    params = SCHEMA["components"]["schemas"]["PageParams"]["properties"]
    assert params["limit"]["maximum"] == 200 and params["limit"]["minimum"] == 1
    assert params["offset"]["minimum"] == 0

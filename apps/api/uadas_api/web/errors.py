# File: apps/api/uadas_api/web/errors.py
"""The one error envelope every 4xx of the API uses, with a closed set of codes.

Why: the web client branches on ``error.code`` (never on prose), and a free-text error is a leak
waiting to happen -- an exception message can carry a path, a fragment of a tenant's data or the
id of a row in another organization. So every error body is
``{"error": {"code": <ErrorCode>, "message": <fixed sentence>, "details": [...]}}`` where

* ``code`` is one of :class:`ErrorCode` (closed; pinned by ``tests/test_web_errors.py``),
* ``message`` is a sentence written by this codebase (a handler never forwards ``str(exception)``
  of a library or the core), and
* ``details`` exists only for ``422`` and holds the *location* and pydantic's error *type* of each
  invalid field -- never the offending value (``input``) nor pydantic's message, which echoes it.

An unhandled exception is not turned into a body here: Django answers 500 and the log has the
traceback, as before. A non-member and a missing organization share one ``404`` body
(``require_membership``), and so do a missing and a foreign project/dataset/chart/...
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from django.core.exceptions import RequestDataTooBig, ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.errors import ValidationError as NinjaValidationError
from pydantic import Field

from uadas_api.quotas.choices import REFUSAL
from uadas_api.quotas.errors import QuotaExceededError


class ErrorCode(StrEnum):
    """Why a request was refused. Stable: part of the committed OpenAPI contract."""

    INVALID_REQUEST = "invalid_request"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    # 3.8: the organization has used up what its quota allows. Shares status 429 with RATE_LIMITED
    # (see :data:`CODE_FOR_STATUS`): the *code* tells a client "wait a moment" from "ask for more".
    QUOTA_EXCEEDED = "quota_exceeded"


ErrorCodeName = Literal[
    "invalid_request",
    "unauthenticated",
    "forbidden",
    "not_found",
    "conflict",
    "payload_too_large",
    "unsupported_media_type",
    "rate_limited",
    "unavailable",
    "quota_exceeded",
]  # pinned to ErrorCode by a test

# Status -> code. A status outside this table is a programming error, not a client mistake. One
# status can carry more than one code: 429 is ``rate_limited`` unless the refusal names
# ``quota_exceeded`` (:class:`ApiError` ``code=``; :data:`CODES_FOR_STATUS` lists the allowed pairs).
CODE_FOR_STATUS: dict[int, ErrorCode] = {
    400: ErrorCode.INVALID_REQUEST,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    422: ErrorCode.INVALID_REQUEST,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.UNAVAILABLE,  # object storage (or the queue) is down: retry later
}


# The codes a status may carry besides its default in CODE_FOR_STATUS.
EXTRA_CODES_FOR_STATUS: dict[int, frozenset[ErrorCode]] = {
    429: frozenset({ErrorCode.QUOTA_EXCEEDED}),
}


class ErrorDetail(Schema):
    """Where a request was invalid (``loc``) and why, as pydantic's error type -- no values."""

    loc: list[str | int]
    type: str


class ErrorBody(Schema):
    code: ErrorCodeName
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorOut(Schema):
    """Body of every 4xx response."""

    error: ErrorBody


# The 4xx statuses every operation may answer; merged into each route's ``response=`` map so the
# OpenAPI document (and Schemathesis) knows the envelope is the answer to all of them.
ERROR_RESPONSES: dict[int, Any] = {status: ErrorOut for status in CODE_FOR_STATUS}


def responses(success: dict[int, Any]) -> dict[int, Any]:
    """``success`` plus the standard error envelope for every refusal status."""
    return {**ERROR_RESPONSES, **success}


def error_body(
    status: int,
    message: str,
    details: list[dict[str, Any]] | None = None,
    code: ErrorCode | None = None,
) -> dict[str, Any]:
    """The JSON body for ``status`` (a status with no mapped code is refused loudly).

    ``code`` picks one of the extra codes a status may carry (``quota_exceeded`` on 429); anything
    else is a programming error.
    """
    default = CODE_FOR_STATUS[status]
    if code is None:
        code = default
    elif code is not default and code not in EXTRA_CODES_FOR_STATUS.get(status, ()):
        raise ValueError(f"{code.value} is not a code of status {status}")
    return {"error": {"code": code.value, "message": message, "details": details or []}}


class ApiError(HttpError):
    """Raise this from a handler for a refusal: a status in :data:`CODE_FOR_STATUS` and a fixed sentence."""

    def __init__(
        self, status: int, message: str, *, code: ErrorCode | None = None
    ) -> None:
        if status not in CODE_FOR_STATUS:
            raise ValueError(f"{status} is not a status of the error envelope")
        error_body(
            status, message, code=code
        )  # refuses a code the status may not carry
        super().__init__(status, message)
        self.envelope_code = code or CODE_FOR_STATUS[status]


def quota_exceeded(kind: str) -> ApiError:
    """``429 quota_exceeded`` with the fixed sentence for ``kind`` (a :class:`UsageKind` value)."""
    return ApiError(429, REFUSAL[kind], code=ErrorCode.QUOTA_EXCEEDED)


def not_found() -> ApiError:
    """The single body for a missing resource *and* for one that belongs to someone else."""
    return ApiError(404, "Not found.")


def _safe_loc(raw: Any) -> list[str | int]:
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    return [item if isinstance(item, (str, int)) else str(item) for item in items]


def _http_error(request: HttpRequest, exc: HttpError, api: NinjaAPI) -> HttpResponse:
    status = exc.status_code
    if status not in CODE_FOR_STATUS:  # a status the envelope does not name: fold it in
        status = 400 if status < 500 else 503
    # The message of an HttpError is always a sentence this codebase wrote (accounts / web).
    # An ApiError may name a second code of its status (quota_exceeded on 429); a bare HttpError
    # carries none and gets its status's default.
    code = getattr(exc, "envelope_code", None) if status == exc.status_code else None
    return api.create_response(
        request, error_body(status, str(exc), code=code), status=status
    )


def _validation_error(
    request: HttpRequest, exc: NinjaValidationError, api: NinjaAPI
) -> HttpResponse:
    details = [
        {"loc": _safe_loc(err.get("loc", [])), "type": str(err.get("type", "invalid"))}
        for err in exc.errors
    ]
    return api.create_response(
        request, error_body(422, "The request was not valid.", details), status=422
    )


def _not_found(request: HttpRequest, exc: Http404, api: NinjaAPI) -> HttpResponse:
    return api.create_response(request, error_body(404, "Not found."), status=404)


def _too_big(
    request: HttpRequest, exc: RequestDataTooBig, api: NinjaAPI
) -> HttpResponse:
    return api.create_response(
        request, error_body(413, "The request is too large."), status=413
    )


def _django_validation(
    request: HttpRequest, exc: ValidationError, api: NinjaAPI
) -> HttpResponse:
    # Model-level guards (tenancy, unique names, job state) raise Django ValidationError; their
    # text names fields, never foreign ids, but the client gets only the fixed sentence.
    return api.create_response(
        request, error_body(422, "The request was not valid."), status=422
    )


def install_error_handlers(api: NinjaAPI) -> None:
    """Replace Ninja's ``{"detail": ...}`` bodies with the envelope (call once per API object)."""

    # ``exc`` is typed ``Any``: Ninja's registration signature allows the class *or* an instance,
    # and each handler is registered for exactly one exception class, which it can rely on.
    def http_error(request: HttpRequest, exc: Any) -> HttpResponse:
        return _http_error(request, exc, api)

    def validation(request: HttpRequest, exc: Any) -> HttpResponse:
        return _validation_error(request, exc, api)

    def missing(request: HttpRequest, exc: Any) -> HttpResponse:
        return _not_found(request, exc, api)

    def too_big(request: HttpRequest, exc: Any) -> HttpResponse:
        return _too_big(request, exc, api)

    def django_validation(request: HttpRequest, exc: Any) -> HttpResponse:
        return _django_validation(request, exc, api)

    def not_a_file_route(request: HttpRequest, exc: Any) -> HttpResponse:
        return api.create_response(
            request,
            error_body(415, "This route does not accept a file upload."),
            status=415,
        )

    def over_quota(request: HttpRequest, exc: Any) -> HttpResponse:
        # Raised by a service (a job creation, an assistant turn) rather than a route, so one
        # handler answers every route: 429 with the closed code and the kind's fixed sentence.
        return api.create_response(
            request,
            error_body(429, REFUSAL[exc.kind], code=ErrorCode.QUOTA_EXCEEDED),
            status=429,
        )

    from uadas_api.web.uploads import UploadNotAllowed  # uploads imports this module

    api.add_exception_handler(UploadNotAllowed, not_a_file_route)
    api.add_exception_handler(QuotaExceededError, over_quota)
    api.add_exception_handler(HttpError, http_error)
    api.add_exception_handler(NinjaValidationError, validation)
    api.add_exception_handler(Http404, missing)
    api.add_exception_handler(RequestDataTooBig, too_big)
    api.add_exception_handler(ValidationError, django_validation)

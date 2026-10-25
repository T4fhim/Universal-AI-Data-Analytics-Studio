# File: apps/api/uadas_api/web/uploads.py
"""The size cap on an uploaded file, enforced *while the bytes stream in*.

Why a Django upload handler and not a check in the view: Django (and Ninja's CSRF check, which
reads ``request.POST``) parses a whole multipart body before any view code runs, writing the file
part to a temporary file as it arrives. A cap checked afterwards has already let a 50 GB upload
fill the disk. A handler sees every chunk, so :class:`CappedTemporaryFileUploadHandler` stops
the parse the moment the running total crosses the cap, and an honest ``Content-Length`` above
the cap is refused before the first byte is read. Raising :class:`UploadTooLarge` (a
``RequestDataTooBig``) is deliberate: it is *not* ``StopUpload``, which would make Django read
and discard the rest of the body; any other exception makes the parser close and delete the
temporary files immediately and propagate, and the API's error handler turns it into ``413``.

``settings.FILE_UPLOAD_HANDLERS`` lists this class and only this class, so there is no memory
upload handler that could keep a small file in RAM and no path around the cap.

**Quota (3.8).** After the route, role and throttle gates and the declared-size check -- and *before*
the first body byte is spooled -- the handler reserves the declared body length against the
organization's stored-bytes quota (:class:`UploadHold`), so an organization at its limit costs the
server no disk. The declared length (the file plus a few hundred bytes of multipart framing) is an
upper bound on the file, and it is what a successful upload keeps charged; the view renames it to
the dataset's ledger key (:meth:`UploadHold.commit`), and **whatever is not committed is released
when the request closes** -- a parse that raised, a CSRF refusal, an admission failure, a conflict, a
crash in the view all end the same way, through one mechanism rather than a ``try`` per exit. What
it cannot cover: a *process* killed mid-upload never reaches the close, so that hold stays charged
until released by hand (the ledger row shows which; a reconcile job is later work).

The cap is the sandbox's input limit (``UADAS_SANDBOX["max_input_bytes"]``, 100 MiB by default):
one number for "the biggest file the product will ingest", enforced here, in the object store
(``max_bytes`` on ``put``) and in the worker (``HEAD`` before download).
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import RequestDataTooBig, SuspiciousOperation
from django.core.files.uploadhandler import TemporaryFileUploadHandler

from uadas_api.accounts.models import Role
from uadas_api.accounts.security import require_membership
from uadas_api.quotas import service as quotas
from uadas_api.quotas.choices import UsageKind
from uadas_api.quotas.errors import QuotaExceededError
from uadas_api.sandbox.limits import SandboxLimits
from uadas_api.web import throttle
from uadas_api.web.errors import ApiError, quota_exceeded

_logger = logging.getLogger(__name__)

# The attribute of the request that carries its stored-bytes hold from the handler to the view.
_HOLD_ATTRIBUTE = "uadas_upload_hold"

# The multipart envelope (boundaries, part headers, the small form fields) rides on top of the
# file; a declared length this much above the cap cannot hold a cap-sized file plus its framing.
_ENVELOPE_SLACK = 1024 * 1024
_UPLOAD_PATH = re.compile(
    r"/api/organizations/(?P<org>[0-9A-Fa-f-]{36})/projects/[0-9A-Fa-f-]{36}/datasets/upload/?"
)


class UploadTooLarge(RequestDataTooBig):
    """A body or file part exceeded its cap (answered ``413``)."""


class UploadHold:
    """Stored bytes reserved for one upload request, released at request end unless committed.

    Created by the upload handler (before the body is spooled), committed by the view when the
    upload became a dataset, and released by the request's own ``close`` otherwise (see the module
    docstring). Every method is idempotent and none raises: this runs on failure paths, where a
    second error must not replace the first.
    """

    def __init__(self, organization_id: uuid.UUID, key: str) -> None:
        self.organization_id = organization_id
        self.key = key
        self._settled = False

    def commit(self, dataset_id: uuid.UUID) -> None:
        """Keep the reservation under the dataset's ledger key (deleting the dataset gives it back)."""
        if self._settled:
            return
        self._settled = True
        try:
            renamed = quotas.rekey(
                self.organization_id,
                UsageKind.STORAGE_BYTES,
                self.key,
                quotas.upload_key(dataset_id),
            )
            if not renamed:
                # That dataset's bytes are already charged (a concurrent identical upload won):
                # this request's own hold is surplus.
                quotas.release(self.organization_id, UsageKind.STORAGE_BYTES, self.key)
        except Exception as error:  # noqa: BLE001 - never replace the response
            _logger.error("an upload quota commit failed (%s)", type(error).__name__)

    def release(self) -> None:
        """Give the reservation back (a no-op once committed or already released)."""
        if self._settled:
            return
        self._settled = True
        try:
            quotas.release(self.organization_id, UsageKind.STORAGE_BYTES, self.key)
        except Exception as error:  # noqa: BLE001
            _logger.error("an upload quota release failed (%s)", type(error).__name__)


def take_hold(request: Any) -> UploadHold | None:
    """The stored-bytes hold the upload handler placed on ``request`` (``None`` if it placed none)."""
    hold = getattr(request, _HOLD_ATTRIBUTE, None)
    return hold if isinstance(hold, UploadHold) else None


class UploadNotAllowed(SuspiciousOperation):
    """A file part was sent to a route that takes none (``415`` from the API, ``400`` from a view)."""


def max_upload_bytes() -> int:
    """The largest file an upload may carry."""
    return SandboxLimits.from_settings().max_input_bytes


class CappedTemporaryFileUploadHandler(TemporaryFileUploadHandler):
    """Writes the file to a temporary file and refuses to take more than the cap."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cap = max_upload_bytes()
        # Decided once per request in ``handle_raw_input``; until then nothing may be spooled.
        self._is_upload = False
        self._organization_id: uuid.UUID | None = None

    def _gate_upload_route(self) -> bool:
        """Whether this is the upload route -- and, if so, signed in, an editor of the path's
        organization and not throttled (else the matching 401 / 404 / 403 / 429 envelope).

        Django parses a multipart body *before* any view's authentication runs (Ninja's CSRF check
        reads ``request.POST`` on **every** route), so without this an anonymous client -- or any
        signed-in stranger to the organization in the URL -- could make the server write up to the
        cap to disk per request, to this route or to any other POST route with a forged CSRF cookie.
        The decision is taken from the request line and the session alone, before the first body
        byte is read. The throttle is counted here, not again in the view. Every *other* route takes
        no file at all and only a JSON-sized body (:meth:`handle_raw_input`, :meth:`new_file`).
        """
        request = self.request
        if request is None:  # a handler built without a request cannot know the route
            return False
        match = _UPLOAD_PATH.fullmatch(request.path_info)
        if match is None:
            return False
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise ApiError(401, "Authentication required.")
        try:
            org_id = uuid.UUID(match["org"])
        except ValueError:
            raise ApiError(404, "Not found.") from None
        membership = require_membership(request, org_id, Role.EDITOR)
        throttle.enforce("upload", membership.user_id, membership.organization_id)
        self._organization_id = membership.organization_id
        return True

    def _hold_bytes(self, organization_id: uuid.UUID, declared: int) -> None:
        """Reserve the stored bytes (and refuse if the rows are already used up) before spooling.

        ``declared`` is the Content-Length; an absent one (``0``) is treated as the cap, the most
        the body could be. The reservation is released when the request closes unless the view
        commits it (:class:`UploadHold`). Rows are not known until the file is parsed, so they are
        only *checked* here (a read: a new upload is refused once the rows are used up) and charged
        by the ingest job, which can overshoot by one file.
        """
        request = self.request
        if (
            request is None
        ):  # the gate returned True, so a request exists; fail closed regardless
            raise ApiError(404, "Not found.")
        hold = UploadHold(organization_id, f"hold:{uuid.uuid4()}")
        try:
            quotas.assert_available(organization_id, UsageKind.ROWS)
            quotas.reserve(
                organization_id,
                UsageKind.STORAGE_BYTES,
                declared or self._cap,
                hold.key,
            )
        except QuotaExceededError as refusal:
            raise quota_exceeded(refusal.kind) from None
        setattr(request, _HOLD_ATTRIBUTE, hold)
        # Whatever happens next, the request's close settles the hold: WSGI and ASGI register
        # ``request.close`` on the response (looked up on the instance) once the view has answered.
        original_close = request.close

        def close_and_settle() -> None:
            try:
                original_close()
            finally:
                hold.release()  # a no-op if the view committed it

        setattr(request, "close", close_and_settle)

    def new_file(self, *args: Any, **kwargs: Any) -> None:
        # Before the parent opens a temporary file: no other route spools anything to disk.
        if not self._is_upload:
            raise UploadNotAllowed("this route does not accept a file")
        super().new_file(*args, **kwargs)

    def handle_raw_input(
        self,
        input_data: Any,
        META: Any,
        content_length: int,
        boundary: str,
        encoding: str | None = None,
    ) -> None:
        self._is_upload = self._gate_upload_route()
        if self._is_upload:
            if content_length > self._cap + _ENVELOPE_SLACK:
                raise UploadTooLarge("the declared request size exceeds the upload cap")
            if self._organization_id is not None:
                self._hold_bytes(self._organization_id, content_length)
        elif content_length > settings.DATA_UPLOAD_MAX_MEMORY_SIZE:
            # Any other route: the body limit of a JSON request (the one number for "a request
            # that is not an upload"), refused on the declared length before a byte is read.
            raise UploadTooLarge("the declared request size exceeds the body limit")

    def receive_data_chunk(self, raw_data: bytes, start: int) -> bytes | None:
        if start + len(raw_data) > self._cap:
            raise UploadTooLarge("the file exceeds the upload cap")
        return super().receive_data_chunk(raw_data, start)

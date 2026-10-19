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

The cap is the sandbox's input limit (``UADAS_SANDBOX["max_input_bytes"]``, 100 MiB by default):
one number for "the biggest file the product will ingest", enforced here, in the object store
(``max_bytes`` on ``put``) and in the worker (``HEAD`` before download).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import TemporaryFileUploadHandler

from uadas_api.accounts.models import Role
from uadas_api.accounts.security import require_membership
from uadas_api.sandbox.limits import SandboxLimits
from uadas_api.web import throttle
from uadas_api.web.errors import ApiError

# The multipart envelope (boundaries, part headers, the small form fields) rides on top of the
# file; a declared length this much above the cap cannot hold a cap-sized file plus its framing.
_ENVELOPE_SLACK = 1024 * 1024
_UPLOAD_PATH = re.compile(
    r"/api/organizations/(?P<org>[0-9A-Fa-f-]{36})/projects/[0-9A-Fa-f-]{36}/datasets/upload/?"
)


class UploadTooLarge(RequestDataTooBig):
    """A file part exceeded the upload cap (answered ``413``)."""


def max_upload_bytes() -> int:
    """The largest file an upload may carry."""
    return SandboxLimits.from_settings().max_input_bytes


class CappedTemporaryFileUploadHandler(TemporaryFileUploadHandler):
    """Writes the file to a temporary file and refuses to take more than the cap."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cap = max_upload_bytes()

    def _gate_upload_route(self) -> None:
        """For the upload route only: signed in, an editor of the path's organization, and not throttled.

        Django parses a multipart body *before* the view's authentication runs (Ninja's CSRF check
        reads ``request.POST``), so without this gate any anonymous client -- or any signed-in
        stranger to the organization in the URL -- could make the server write up to the cap to disk
        per request. Here the decision (401 / 404 / 403 / 429, the same envelope as the view's) is
        taken from the request line and the session alone, before the first body byte is read. The
        throttle is counted here, not again in the view. Other multipart posts (none exist in the API
        today) keep only the size cap.
        """
        request = self.request
        if request is None:  # a handler built without a request cannot know the route
            return
        match = _UPLOAD_PATH.fullmatch(request.path_info)
        if match is None:
            return
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise ApiError(401, "Authentication required.")
        try:
            org_id = uuid.UUID(match["org"])
        except ValueError:
            raise ApiError(404, "Not found.") from None
        membership = require_membership(request, org_id, Role.EDITOR)
        throttle.enforce("upload", membership.user_id, membership.organization_id)

    def handle_raw_input(
        self,
        input_data: Any,
        META: Any,
        content_length: int,
        boundary: str,
        encoding: str | None = None,
    ) -> None:
        self._gate_upload_route()
        if content_length > self._cap + _ENVELOPE_SLACK:
            raise UploadTooLarge("the declared request size exceeds the upload cap")

    def receive_data_chunk(self, raw_data: bytes, start: int) -> bytes | None:
        if start + len(raw_data) > self._cap:
            raise UploadTooLarge("the file exceeds the upload cap")
        return super().receive_data_chunk(raw_data, start)

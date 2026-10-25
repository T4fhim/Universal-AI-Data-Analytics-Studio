# File: scripts/compose_smoke.py
"""End-to-end smoke of the running compose stack: the Phase 3 "verification line".

Why this exists: the plan's Phase 3 exit criterion is "``docker compose up`` gives a working
stack", and a stack that merely *starts* proves nothing about the parts that fail in
deployment -- the migration job, the worker reaching Redis/PostgreSQL/the object store, the
sandboxed parser child, the cookie + CSRF flow. This script drives the real HTTP API of a
running stack through exactly the journey the plan names, and exits non-zero on the first
thing that does not hold:

1. the API answers ``/api/health``;
2. sign up a throwaway user through allauth's headless browser API (CSRF cookie flow);
3. read the personal organization the signup created;
4. create a project;
5. upload a small CSV and poll its ingest job to ``succeeded``;
6. fetch the dataset preview and assert the rows;
7. upload a deliberately malformed PDF and assert the job ends ``failed`` with a code from
   the closed job-error vocabulary (``uadas_api/jobs/errors.py``) -- *fail safe*;
8. throughout: no response is a 5xx, and no body carries a traceback or a server path.

Standard library only (urllib + http.cookiejar): it runs from any Python 3, on the host that
runs ``docker compose`` and in CI, with nothing installed. It is deliberately NOT part of the
pytest suites -- it needs a running stack -- and is not imported by anything.

Usage::

    docker compose -f docker-compose.yml -f docker-compose.local.yml up --build -d
    python scripts/compose_smoke.py                       # http://localhost:8000
    python scripts/compose_smoke.py --base-url http://127.0.0.1:8000 --job-timeout 180

Against a production-settings stack the sign-up step stops with an explicit message: prod
requires email verification, which a script cannot complete without the mailbox.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, NoReturn

# The closed vocabulary a failed job may carry (JobErrorCode in uadas_api/jobs/errors.py).
# Duplicated on purpose: this script must not import the project (stdlib only, runs anywhere),
# and a code outside this set is itself a finding -- the API's contract is that it never
# reports free text. The malformed PDF is expected to land on parse_error / unsupported_type.
CLOSED_JOB_ERROR_CODES = frozenset(
    {
        "unsupported_type",
        "input_too_large",
        "decompression_bomb",
        "timeout",
        "memory_limit",
        "cpu_limit",
        "output_too_large",
        "too_many_rows",
        "too_many_columns",
        "multiple_tables",
        "parse_error",
        "blocked_operation",
        "resource_limit",
        "sandbox_crashed",
        "protocol_error",
        "sandbox_unavailable",
        "forbidden",
        "not_found",
        "conflict",
        "invalid_request",
        "operation_failed",
        "storage_unavailable",
        "storage_error",
        "too_many_attempts",
        "worker_lost",
        "internal_error",
    }
)
# Failures that say "the stack is broken", not "this file is bad": a malformed PDF landing on
# one of these means the sandbox or storage did not work, so the smoke must not call it a pass.
INFRASTRUCTURE_ERROR_CODES = frozenset(
    {
        "sandbox_unavailable",
        "sandbox_crashed",
        "protocol_error",
        "storage_unavailable",
        "storage_error",
        "worker_lost",
        "too_many_attempts",
        "internal_error",
    }
)

# Text that must never appear in any response body: a traceback frame, a server-side path
# (the image's venv, the app directory, a sandbox job directory) or a Python source file.
LEAK_MARKERS = (
    "Traceback (most recent call last)",
    'File "',
    "site-packages",
    "/opt/venv",
    "/app/",
    "uadas-sbx",
    ".py:",
    '.py"',
    "C:\\",
)

CSV_BYTES = b"region,units,price\nnorth,10,2.5\nsouth,7,3.0\neast,12,1.75\nwest,5,4.2\ncentral,9,2.0\n"
CSV_ROWS = 5
CSV_COLUMNS = ["region", "units", "price"]
# A PDF header followed by noise: it passes admission (the signature is right) and must be
# refused by the parser, inside the sandbox child, without anything leaking.
MALFORMED_PDF = b"%PDF-1.4\n" + bytes(range(256)) * 8 + b"\n%%EOF-not-really\n"

TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


class SmokeFailure(Exception):
    """A step did not hold. The message is printed and the process exits 1."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface a redirect (typically an HTTP -> HTTPS one) instead of following it silently."""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class Client:
    """A cookie-carrying JSON client that applies the leak and 5xx rules to every response."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies), _NoRedirect()
        )

    def csrf_token(self) -> str:
        for cookie in self.cookies:
            if cookie.name == "csrftoken":
                return cookie.value or ""
        return ""

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, Any]:
        headers = {"Accept": "application/json"}
        body = data
        if json_body is not None:
            body = json.dumps(json_body).encode()
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        if method != "GET":
            # Django's CSRF check: the cookie is set by GET /config, the header echoes it. Login
            # rotates the token, so it is re-read from the jar on every write, not cached.
            headers["X-CSRFToken"] = self.csrf_token()
        request = urllib.request.Request(
            self.base + path, data=body, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=60) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except urllib.error.URLError as error:
            raise SmokeFailure(
                f"{method} {path}: cannot reach the stack ({error.reason})"
            ) from None
        text = raw.decode("utf-8", "replace")
        if status >= 500:
            raise SmokeFailure(f"{method} {path}: server error {status}")
        for marker in LEAK_MARKERS:
            if marker in text:
                raise SmokeFailure(
                    f"{method} {path}: response leaks server detail ({marker!r})"
                )
        if not text:
            return status, None
        try:
            return status, json.loads(text)
        except json.JSONDecodeError:
            return status, text


def _multipart(
    field: str, filename: str, payload: bytes, content_type: str
) -> tuple[bytes, str]:
    boundary = "----smoke" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + payload + tail, f"multipart/form-data; boundary={boundary}"


def fail(message: str) -> NoReturn:
    raise SmokeFailure(message)


def step(name: str, detail: str = "") -> None:
    print(f"[ ok ] {name}" + (f" -- {detail}" if detail else ""), flush=True)


def wait_for_health(client: Client, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            status, body = client.request("GET", "/api/health")
        except SmokeFailure as error:
            last = str(error)
        else:
            if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
                step("health", "GET /api/health -> 200 {status: ok}")
                return
            last = f"status {status}"
        time.sleep(2)
    fail(f"health: the API did not become healthy within {seconds:.0f}s (last: {last})")


def sign_up(client: Client) -> str:
    status, _ = client.request("GET", "/api/auth/browser/v1/config")
    if status != 200 or not client.csrf_token():
        fail(
            f"csrf: GET /api/auth/browser/v1/config gave {status} and no csrftoken cookie"
        )
    step("csrf", "csrftoken cookie issued by GET /api/auth/browser/v1/config")
    email = f"smoke-{secrets.token_hex(6)}@example.com"
    password = secrets.token_urlsafe(
        18
    )  # >= 12 chars, random: passes every password validator
    status, body = client.request(
        "POST",
        "/api/auth/browser/v1/auth/signup",
        json_body={"email": email, "password": password},
    )
    if status == 401 and "verify_email" in json.dumps(body):
        fail(
            "signup: the stack requires email verification (production settings); this script "
            "cannot read the mailbox -- run it against the local override "
            "(docker-compose.local.yml), which verifies optionally"
        )
    if status != 200:
        fail(f"signup: expected 200, got {status}")
    session_status, session = client.request("GET", "/api/auth/browser/v1/auth/session")
    if session_status != 200 or not (session or {}).get("meta", {}).get(
        "is_authenticated"
    ):
        fail(
            f"signup: the account was created but there is no session ({session_status}); "
            "a Secure cookie over plain HTTP is the usual cause (production settings on http://)"
        )
    step("signup", f"{email} created and signed in (session cookie + CSRF)")
    return email


def personal_organization(client: Client, email: str) -> str:
    status, me = client.request("GET", "/api/me")
    if status != 200:
        fail(f"me: expected 200, got {status}")
    if me["user"]["email"].lower() != email.lower():
        fail("me: the session belongs to a different user")
    owned = [m for m in me["memberships"] if m["role"] == "owner"]
    if len(owned) != 1:
        fail(
            f"me: expected exactly one personal organization (owner), got {len(owned)}"
        )
    org_id = owned[0]["organization"]["id"]
    step("organization", f"personal organization {org_id} (role owner)")
    return str(org_id)


def create_project(client: Client, org_id: str) -> str:
    status, project = client.request(
        "POST",
        f"/api/organizations/{org_id}/projects",
        json_body={"name": "compose smoke"},
    )
    if status != 201:
        fail(f"project: expected 201, got {status}: {project}")
    step("project", f"created {project['id']}")
    return str(project["id"])


def upload(
    client: Client, base: str, filename: str, payload: bytes, content_type: str
) -> dict[str, Any]:
    body, header = _multipart("file", filename, payload, content_type)
    status, accepted = client.request(
        "POST", f"{base}/datasets/upload", data=body, content_type=header
    )
    if status != 202 or not isinstance(accepted, dict):
        fail(f"upload {filename}: expected 202, got {status}: {accepted}")
    return accepted


def wait_for_job(
    client: Client, base: str, job_id: str, seconds: float
) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    last = ""
    while time.monotonic() < deadline:
        status, job = client.request("GET", f"{base}/jobs/{job_id}")
        if status != 200:
            fail(f"job {job_id}: expected 200, got {status}")
        if job["status"] != last:
            last = job["status"]
            print(f"       job {job_id[:8]} {last} ({job['progress']}%)", flush=True)
        if job["status"] in TERMINAL:
            return dict(job)
        time.sleep(1)
    fail(f"job {job_id}: still {last!r} after {seconds:.0f}s -- is the worker running?")


def check_csv(client: Client, base: str, job_timeout: float) -> None:
    accepted = upload(client, base, "sales.csv", CSV_BYTES, "text/csv")
    step("upload csv", f"202 accepted, job {accepted['job_id']}")
    job = wait_for_job(client, base, accepted["job_id"], job_timeout)
    if job["status"] != "succeeded":
        fail(
            f"csv job ended {job['status']} ({job.get('error_code')}): the worker or sandbox is broken"
        )
    step("csv job", f"succeeded ({job['kind']})")
    status, preview = client.request(
        "GET", f"{base}/datasets/{accepted['dataset_id']}/preview?offset=0&limit=50"
    )
    if status != 200:
        fail(f"preview: expected 200, got {status}")
    columns = [c["name"] for c in preview["columns"]]
    if columns != CSV_COLUMNS:
        fail(f"preview: columns {columns} != {CSV_COLUMNS}")
    if preview["total_rows"] != CSV_ROWS or len(preview["rows"]) != CSV_ROWS:
        fail(
            f"preview: expected {CSV_ROWS} rows, got total_rows={preview['total_rows']} "
            f"with {len(preview['rows'])} returned"
        )
    if "north" not in preview["rows"][0]:
        fail(f"preview: first row {preview['rows'][0]} does not hold the uploaded data")
    step("preview", f"{preview['total_rows']} rows x {len(columns)} columns: {columns}")


def check_malformed_pdf(client: Client, base: str, job_timeout: float) -> None:
    accepted = upload(client, base, "broken.pdf", MALFORMED_PDF, "application/pdf")
    step("upload malformed pdf", f"202 accepted, job {accepted['job_id']}")
    job = wait_for_job(client, base, accepted["job_id"], job_timeout)
    if job["status"] != "failed":
        fail(f"malformed pdf: job ended {job['status']!r}, expected 'failed'")
    code = job["error_code"]
    if code not in CLOSED_JOB_ERROR_CODES:
        fail(f"malformed pdf: error_code {code!r} is outside the closed vocabulary")
    if code in INFRASTRUCTURE_ERROR_CODES:
        fail(
            f"malformed pdf: failed with {code!r}, which means the sandbox/worker is broken, "
            "not that the file was refused"
        )
    step(
        "malformed pdf job",
        f"failed safe with closed code {code!r}: {job['error_message']!r}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--health-timeout", type=float, default=120.0)
    parser.add_argument("--job-timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    client = Client(args.base_url)
    try:
        wait_for_health(client, args.health_timeout)
        email = sign_up(client)
        org_id = personal_organization(client, email)
        project_id = create_project(client, org_id)
        base = f"/api/organizations/{org_id}/projects/{project_id}"
        check_csv(client, base, args.job_timeout)
        check_malformed_pdf(client, base, args.job_timeout)
    except SmokeFailure as error:
        print(f"[FAIL] {error}", file=sys.stderr, flush=True)
        return 1
    print(
        "[ ok ] smoke passed: signup, csv ingest + preview, malformed pdf failed safe"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

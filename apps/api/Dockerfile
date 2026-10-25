# syntax=docker/dockerfile:1
#
# The server image for the Django API, its Celery worker/beat and the one-shot `migrate`
# job (docker-compose.yml runs all four from this one image with different commands).
#
# Build from the REPOSITORY ROOT (the context must contain uadas_core/ and apps/api/):
#
#   docker build -f apps/api/Dockerfile -t uadas-api .
#
# Design notes (each one is a decision, not an accident):
#
# * Two stages. `builder` has pip and the pip cache; `runtime` receives only the finished
#   virtualenv, so no pip cache, build metadata or source tree rides along.
# * Runtime requirements only (requirements.txt + the API's own dependencies + gunicorn):
#   no pytest/black/mypy/ruff/bandit/pre-commit in an image that parses hostile files.
# * `uadas_core` and `uadas_api` are installed NON-editable into the venv's site-packages.
#   The parser sandbox child is `python -I -m uadas_api.sandbox.child`; `-I` ignores
#   PYTHONPATH and user site, so a source checkout on a path would not be importable there
#   (apps/api/README.md, "Run a worker"; check --deploy fails with uadas_jobs.E004 otherwise).
# * The apt libraries below are derived, not guessed -- see the comment on the RUN line.
# * Runs as a dedicated unprivileged uid (10001), never root. Production settings accept a
#   root worker only with a dedicated child uid; this image takes the other branch
#   (SANDBOX_ISOLATION_ACKNOWLEDGED=container, set in docker-compose.yml).

ARG PYTHON_IMAGE=python:3.13-slim-bookworm

FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONDONTWRITEBYTECODE=0

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /src

# Layer 1 -- third-party dependencies. Only the two dependency declarations are copied, so
# this (slow) layer is rebuilt when a dependency changes and not when source code does. The
# API's dependency list is read out of its pyproject (minus the core, which is installed
# from this checkout below) so there is still exactly one place that declares it.
COPY requirements.txt ./requirements.txt
COPY apps/api/pyproject.toml ./apps/api/pyproject.toml
RUN python - > /tmp/api-requirements.txt <<'PY'
import tomllib

with open("apps/api/pyproject.toml", "rb") as handle:
    project = tomllib.load(handle)["project"]
deps = [d for d in project["dependencies"] if not d.startswith("universal-ai-data-analytics-studio")]
deps += project["optional-dependencies"]["server"]
print("\n".join(deps))
PY
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt -r /tmp/api-requirements.txt

# Layer 2 -- the project itself, without re-resolving anything (--no-deps: layer 1 did that).
COPY pyproject.toml README.md ./
COPY uadas_core ./uadas_core
COPY apps/api/uadas_api ./apps/api/uadas_api
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps . ./apps/api


FROM ${PYTHON_IMAGE} AS runtime

# Native libraries the readers need at import or run time (derived by installing the
# runtime requirements into a bare python:3.13-slim and scanning every shared object for
# unresolved dependencies, then importing every reader module -- not guessed):
#   libmagic1               python-magic (content-type sniffing in the upload path)
#   libgl1 libglib2.0-0 libxcb1
#                           OpenCV, which the readers import (a bare image fails every parse
#                           as `parse_error`: ImportError libxcb.so.1)
#   libodbc2                pyodbc, imported through uadas_core.database
# Result of that scan: the only unresolved libraries (libICE, libSM) belong to OpenCV's bundled
# Qt xcb plugin, which headless parsing never loads; every uadas_core.readers module imports.
# Ghostscript is not needed (camelot renders through pypdfium2). Tesseract is NOT installed:
# pytesseract needs the binary only to OCR an image, so scanned-image upload is the one reader
# capability this image lacks (add `tesseract-ocr` here to enable it, ~100 MB).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 libgl1 libglib2.0-0 libxcb1 libodbc2 \
    && rm -rf /var/lib/apt/lists/*

# A fixed, unprivileged uid/gid. Not root, no login shell, a real home (some libraries
# write a cache under $HOME) that is the only writable place besides /tmp.
RUN groupadd --system --gid 10001 uadas \
    && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/uadas \
       --shell /usr/sbin/nologin uadas

COPY --from=builder /opt/venv /opt/venv
COPY apps/api/manage.py /app/manage.py

ENV PATH="/opt/venv/bin:${PATH}" \
    HOME=/home/uadas \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=uadas_api.settings.prod

WORKDIR /app
USER 10001:10001
EXPOSE 8000

# Liveness only (GET /api/health touches no database). ALLOWED_HOSTS applies to the probe, so
# it sends the first listed host; X-Forwarded-Proto lets it pass the HTTPS redirect when the
# deployment trusts that header (TLS terminated at a proxy), which is the supported topology.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import http.client as h, os; c = h.HTTPConnection('127.0.0.1', 8000, timeout=4); c.request('GET', '/api/health', headers={'Host': (os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',')[0].strip() or 'localhost'), 'X-Forwarded-Proto': 'https'}); raise SystemExit(0 if c.getresponse().status == 200 else 1)"]

# WSGI on purpose (README, "Resource routes"): under ASGI Django spools a whole request body
# before any handler runs, so the JSON and upload size caps could not act first. gthread:
# a few processes, many threads, so a long-lived SSE stream pins a thread rather than a
# process. Put a TLS-terminating reverse proxy in front (and let it cap the body too).
CMD ["gunicorn", "uadas_api.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--worker-class", "gthread", "--threads", "8", \
     "--timeout", "120", "--graceful-timeout", "30", \
     "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-", "--error-logfile", "-"]

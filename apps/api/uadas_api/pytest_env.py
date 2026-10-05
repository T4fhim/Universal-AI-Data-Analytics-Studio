# File: apps/api/uadas_api/pytest_env.py
"""A pytest plugin that makes the API test run ignore the developer's OAuth credentials.

Why: ``settings/base.py`` reads ``GITHUB_CLIENT_ID`` / ``GOOGLE_CLIENT_ID`` (and the secrets)
from the environment when Django's settings are first loaded, and installs a provider -- or,
for a half-configured pair, raises -- accordingly. Someone with those variables exported for
local sign-in would get a different app registry in every test run, and one stray half pair
would crash every test at settings import. The in-process suite must be hermetic, so the
variables are removed before anything reads them.

Why a ``-p`` plugin and not a conftest: pytest-django loads the settings in
``pytest_load_initial_conftests``, which runs *before* conftest files are imported, so a
conftest (even one at the rootdir) is too late. Plugins named with ``-p`` are imported while
the command line is parsed, earlier still; ``apps/api/pyproject.toml`` lists this module in
``addopts``. ``tests/test_hermetic_env.py`` proves the ordering with a child pytest.

Importing this module is the whole effect. It does not touch the tests that start their own
interpreters with credentials on purpose (``test_oauth_runtime.py``): those pass an explicit
environment to the child process.
"""

from __future__ import annotations

import os

# Provider credentials only. DATABASE_URL is deliberately kept: CI points the suite at its
# Postgres service container with it.
SCRUBBED_VARIABLES = (
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
)

for _name in SCRUBBED_VARIABLES:
    os.environ.pop(_name, None)

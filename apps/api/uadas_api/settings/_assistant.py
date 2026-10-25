# File: apps/api/uadas_api/settings/_assistant.py
"""The AI assistant's provider settings: deployment environment only, strictly parsed (3.7).

Why only the environment: an LLM key is a secret that bills a person, so it comes from the
deployment (``ASSISTANT_PROVIDER`` / ``ASSISTANT_API_KEY`` / ``ASSISTANT_MODEL``) and from nowhere
else -- never a request body, never a database row, never a log line (per-user keys are a later
feature that needs encrypted storage). Unconfigured (no provider) is a valid state: the assistant
endpoint then answers ``503 unavailable`` and the rest of the API is unaffected.

* ``ASSISTANT_PROVIDER`` -- ``anthropic``, ``gemini``, ``groq`` or ``openrouter``. ``ollama`` (the desktop's local
  server) is deliberately not offered: on a server it would be a request-driven connection to
  whatever ``localhost`` is.
* a provider without a key, an unknown provider, or an odd-looking model name stops start-up
  (``ImproperlyConfigured`` naming the variable, never echoing the value: it may be the secret).

The key sits in a dict under ``api_key``, a name Django's debug-page cleanser redacts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

PROVIDERS = ("anthropic", "gemini", "groq", "openrouter")
_MODEL = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}\Z")


def parse_assistant(env: Mapping[str, str]) -> dict[str, Any]:
    """``{"provider", "api_key", "model"}`` from the environment (``provider == ""`` = off)."""
    provider = env.get("ASSISTANT_PROVIDER", "").strip().lower()
    api_key = env.get("ASSISTANT_API_KEY", "").strip()
    model = env.get("ASSISTANT_MODEL", "").strip()
    if not provider:
        if api_key or model:
            raise ImproperlyConfigured(
                "ASSISTANT_API_KEY / ASSISTANT_MODEL are set but ASSISTANT_PROVIDER is not."
            )
        return {"provider": "", "api_key": "", "model": ""}
    if provider not in PROVIDERS:
        raise ImproperlyConfigured(
            f"ASSISTANT_PROVIDER must be one of {', '.join(PROVIDERS)}."
        )
    if not api_key:
        raise ImproperlyConfigured(
            "ASSISTANT_API_KEY must be set when ASSISTANT_PROVIDER is."
        )
    if model and not _MODEL.fullmatch(model):
        raise ImproperlyConfigured("ASSISTANT_MODEL is not a valid model name.")
    return {"provider": provider, "api_key": api_key, "model": model}

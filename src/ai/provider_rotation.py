# File: src/ai/provider_rotation.py
"""Fail-over across several configured LLM provider profiles (milestone 7).

:class:`ProviderRotationService` is the "thin new service"
:mod:`src.ai.assistant_service` holds, per the milestone plan's own
wording — kept in its own module rather than folded directly into
:class:`~src.ai.assistant_service.AssistantService` because rotation
bookkeeping (which profile is active, lazily-constructed provider
instances per profile) is a distinct concern from running a
conversation, and this module has no dependency on
``WorkspaceService`` or tool dispatch at all.

This is what turns the multi-key Groq setup the user asked for into
actual behavior: several Groq API keys (each its own profile) are
tried in order, and a 429/rate-limit failure from the active one
advances to the next rather than failing the whole conversation turn.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.ai.llm_provider import BaseLLMProvider, create_provider
from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)


@dataclass(frozen=True)
class ResolvedProviderProfile:
    """One provider profile with its API key already resolved.

    Distinct from the raw ``ai.providers`` config dict shape (which
    stores an ``api_key_env_var`` *name*, not a key) — resolution
    happens once, in :meth:`ProviderRotationService.from_config_profiles`,
    so the rest of this module never touches ``os.environ`` again.
    """

    name: str
    provider_type: str
    api_key: str
    model: str | None = None


def _looks_like_rate_limit(exc: Exception) -> bool:
    """Heuristic: does this ``ServiceError`` describe a 429/rate-limit failure?

    Every provider in :mod:`src.ai.llm_provider` wraps its SDK's raw
    exception into ``ServiceError(f"... API call failed: {exc}")`` —
    none currently exposes a structured status code through this
    project's provider-neutral interface, so the only signal available
    here is the stringified message. Checked case-insensitively
    against both the literal HTTP status and the phrase every major
    provider (Anthropic, Groq/OpenAI-compatible) uses in its own
    rate-limit error text.
    """
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "rate_limit" in text


class ProviderRotationService:
    """Holds an ordered list of provider profiles and rotates through them on failure.

    Args:
        profiles: Ordered fail-over list. Index 0 is tried first.
            Must be non-empty.

    Raises:
        ServiceError: If ``profiles`` is empty.
    """

    def __init__(self, profiles: list[ResolvedProviderProfile]) -> None:
        if not profiles:
            raise ServiceError(
                "ProviderRotationService requires at least one provider profile."
            )
        self._profiles = profiles
        self._index = 0
        # Provider instances are constructed lazily and cached per
        # profile index, not eagerly for every profile up front — most
        # conversations never rotate at all, so building N SDK clients
        # when only one will ever be used would be wasted work (and,
        # for cloud providers, an unnecessary client-construction call
        # per configured key).
        self._providers: dict[int, BaseLLMProvider] = {}

    @property
    def active_profile(self) -> ResolvedProviderProfile:
        return self._profiles[self._index]

    def current_provider(self) -> BaseLLMProvider:
        """Return the active profile's provider, constructing it on first use."""
        if self._index not in self._providers:
            profile = self._profiles[self._index]
            self._providers[self._index] = create_provider(
                profile.provider_type, profile.api_key, model=profile.model
            )
        return self._providers[self._index]

    def advance(self) -> bool:
        """Move to the next profile.

        Returns:
            ``True`` if there was a next profile to move to. ``False``
            if already at the last configured profile — callers should
            treat this as "no more fail-over options" and let the
            original error propagate rather than looping forever.
        """
        if self._index + 1 >= len(self._profiles):
            return False
        self._index += 1
        _logger.info(
            "Provider rotation: switching to %r (%s).",
            self.active_profile.name,
            self.active_profile.provider_type,
        )
        return True

    def reset(self) -> None:
        """Return to the first configured profile (index 0)."""
        self._index = 0

    @classmethod
    def from_config_profiles(
        cls, config_profiles: list[dict[str, Any]]
    ) -> ProviderRotationService:
        """Build from the ``ai.providers`` config shape (see :mod:`src.core.config`).

        Resolves each profile's ``api_key_env_var`` through
        ``os.environ`` once, here — a profile with no configured
        environment variable (or one that names a variable that isn't
        set) resolves to an empty-string key, which is what
        :class:`~src.ai.llm_provider.OllamaProvider` expects anyway
        (it ignores its ``api_key`` argument entirely) and which any
        other provider will simply fail authentication on, surfacing a
        clear error rather than silently doing nothing.
        """
        resolved = [
            ResolvedProviderProfile(
                name=profile["name"],
                provider_type=profile["provider_type"],
                api_key=(
                    os.environ.get(profile["api_key_env_var"], "")
                    if profile.get("api_key_env_var")
                    else ""
                ),
                model=profile.get("model"),
            )
            for profile in config_profiles
        ]
        return cls(resolved)

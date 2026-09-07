# File: tests/ai/test_provider_rotation.py
"""Covers milestone 29's ``ai.active_provider_index`` wiring: previously stored, never read.

Before this milestone, :meth:`~uadas_core.ai.provider_rotation.ProviderRotationService.
from_config_profiles` always started at index 0 regardless of what ``ai.active_provider_index``
said -- confirmed directly against the pre-milestone-29 source before writing this test, not
assumed. These tests exercise :class:`~uadas_core.ai.provider_rotation.ProviderRotationService`
directly (not through a real :class:`~uadas_core.ai.llm_provider.BaseLLMProvider`) since
``active_profile``/``_index`` bookkeeping is independent of which provider type is configured --
:meth:`~uadas_core.ai.provider_rotation.ProviderRotationService.current_provider` (which does
construct a real provider client) is exercised by ``tests/ai/test_assistant_service.py`` instead.
"""

from __future__ import annotations

import os

import pytest

from uadas_core.ai.provider_rotation import (
    ProviderRotationService,
    ResolvedProviderProfile,
)
from uadas_core.core.exceptions import ServiceError

_PROFILES = [
    ResolvedProviderProfile(name="first", provider_type="anthropic", api_key="k1"),
    ResolvedProviderProfile(name="second", provider_type="groq", api_key="k2"),
    ResolvedProviderProfile(name="third", provider_type="groq", api_key="k3"),
]


def test_default_start_index_is_zero() -> None:
    service = ProviderRotationService(list(_PROFILES))
    assert service.active_profile.name == "first"


def test_start_index_selects_the_named_profile() -> None:
    service = ProviderRotationService(list(_PROFILES), start_index=2)
    assert service.active_profile.name == "third"


def test_out_of_range_start_index_falls_back_to_zero_with_a_warning(caplog) -> None:
    with caplog.at_level("WARNING"):
        service = ProviderRotationService(list(_PROFILES), start_index=99)
    assert service.active_profile.name == "first"
    assert "out of range" in caplog.text


def test_negative_start_index_falls_back_to_zero() -> None:
    service = ProviderRotationService(list(_PROFILES), start_index=-1)
    assert service.active_profile.name == "first"


def test_from_config_profiles_honors_active_index() -> None:
    config_profiles = [
        {
            "name": "a",
            "provider_type": "ollama",
            "api_key_env_var": None,
            "model": None,
        },
        {
            "name": "b",
            "provider_type": "ollama",
            "api_key_env_var": None,
            "model": None,
        },
    ]
    service = ProviderRotationService.from_config_profiles(
        config_profiles, active_index=1
    )
    assert service.active_profile.name == "b"


def test_empty_profiles_still_raises_regardless_of_start_index() -> None:
    with pytest.raises(ServiceError):
        ProviderRotationService([], start_index=0)


# -- Injected credentials (web-transition Phase 1.8 security fix) ---------------


def test_from_config_profiles_resolves_keys_from_injected_secrets_not_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The web server can inject credentials; ``os.environ`` is not consulted when it does.

    Red before the Phase 1.8 fix: ``from_config_profiles`` had no
    ``secrets`` parameter, so this call raised ``TypeError``. Green
    after: the key comes from the injected mapping even though the named
    variable is absent from the process environment.
    """
    monkeypatch.delenv("UADAS_TEST_PROVIDER_KEY", raising=False)
    config_profiles = [
        {
            "name": "web",
            "provider_type": "anthropic",
            "api_key_env_var": "UADAS_TEST_PROVIDER_KEY",
            "model": None,
        }
    ]

    service = ProviderRotationService.from_config_profiles(
        config_profiles,
        secrets={"UADAS_TEST_PROVIDER_KEY": "sk-injected-not-in-environ"},
    )

    assert service.active_profile.api_key == "sk-injected-not-in-environ"
    assert "UADAS_TEST_PROVIDER_KEY" not in os.environ


def test_from_config_profiles_still_reads_environ_when_no_secrets_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The desktop default is unchanged: with no ``secrets`` mapping, the environment is read."""
    monkeypatch.setenv("UADAS_TEST_PROVIDER_KEY", "sk-from-environ")
    config_profiles = [
        {
            "name": "desktop",
            "provider_type": "anthropic",
            "api_key_env_var": "UADAS_TEST_PROVIDER_KEY",
            "model": None,
        }
    ]

    service = ProviderRotationService.from_config_profiles(config_profiles)

    assert service.active_profile.api_key == "sk-from-environ"

"""Tests for orchestrator.backend_resolver — pure registry-driven backend resolution."""
import pytest
from datetime import datetime, timezone
from perpetua.discovery.backend import Backend, BackendKind, BackendHealth
from perpetua.discovery.registry import BackendRegistry
from orchestrator.backend_resolver import resolve_backend_for_spec


@pytest.mark.asyncio
async def test_resolver_picks_lmstudio_win_for_shared_coding():
    reg = BackendRegistry()
    reg._backends["lmstudio-win"] = Backend(
        "lmstudio-win", "http://192.168.254.103:1234/v1", BackendKind.LMSTUDIO,
        ("qwen3-coder-30b",), BackendHealth.ONLINE, datetime.now(timezone.utc),
    )
    spec = {"task_type": "coding", "target_tier": "shared", "model_hint": None,
            "base_url_override": None}
    backend = resolve_backend_for_spec(reg, spec)
    assert backend.base_url == "http://192.168.254.103:1234/v1"


@pytest.mark.asyncio
async def test_resolver_honors_base_url_override_matching_known_backend():
    """If caller passes a base_url_override that matches a registered backend, return it."""
    reg = BackendRegistry()
    reg._backends["lmstudio-win"] = Backend(
        "lmstudio-win", "http://192.168.254.103:1234/v1", BackendKind.LMSTUDIO,
        ("model-x",), BackendHealth.ONLINE, datetime.now(timezone.utc),
    )
    spec = {"base_url_override": "http://192.168.254.103:1234/v1"}
    backend = resolve_backend_for_spec(reg, spec)
    assert backend.name == "lmstudio-win"


@pytest.mark.asyncio
async def test_resolver_override_synthesizes_adhoc_backend_for_unknown_url():
    """If caller forces a URL not in the registry, synthesize an unverified adhoc Backend."""
    reg = BackendRegistry()
    spec = {"base_url_override": "http://192.168.254.222:1234/v1"}
    backend = resolve_backend_for_spec(reg, spec)
    assert backend.name == "adhoc"
    assert backend.base_url == "http://192.168.254.222:1234/v1"

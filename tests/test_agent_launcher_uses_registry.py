import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone
from perpetua.discovery.backend import Backend, BackendKind, BackendHealth
from perpetua.discovery.registry import BackendRegistry
from orchestrator.agent_launcher import resolve_backend_for_spec


@pytest.mark.asyncio
async def test_launcher_uses_registry_selection():
    reg = BackendRegistry()
    reg._backends["lmstudio-win"] = Backend(
        "lmstudio-win", "http://192.168.254.103:1234/v1", BackendKind.LMSTUDIO,
        ("qwen3-coder-30b",), BackendHealth.ONLINE, datetime.now(timezone.utc),
    )
    spec = {"task_type": "coding", "target_tier": "shared", "model_hint": None,
            "base_url_override": None}
    backend = resolve_backend_for_spec(reg, spec)
    assert backend.base_url == "http://192.168.254.103:1234/v1"

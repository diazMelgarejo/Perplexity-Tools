"""test_hardware_routing.py - Hardware-aware routing integration test.

Verifies that ModelRegistry correctly selects hardware-appropriate models
based on the profiles defined in hardware/SKILL.md and routes in routing.yml.
Specifically ensures deep_reasoning and code_analysis tasks target correctly.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, List
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# Ensure repo root is on PYTHONPATH
REPO_ROOT = Path(__file__).parent.parent
os.environ["OLLAMA_HOST"] = "http://127.0.0.1"

from orchestrator.model_registry import ModelRegistry
from orchestrator.fastapi_app import app

@pytest.fixture
def registry():
    return ModelRegistry(config_dir=str(REPO_ROOT / "config"))


@pytest.fixture
def client():
    async def fake_resolve_routing_state():
        return {
            "manager_endpoint": "http://192.168.254.103:11434",
            "manager_model": "glm-5.1:cloud",
            "manager_backend": "mac-ollama",
            "coder_endpoint": "http://192.168.254.100:1234",
            "coder_model": "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2",
            "coder_backend": "windows-lmstudio",
            "distributed": True,
        }

    with (
        patch("orchestrator.fastapi_app.resolve_routing_state", new=fake_resolve_routing_state),
        patch("orchestrator.fastapi_app.sync_ecc_tools", return_value={"status": "ok", "message": "mocked"}),
    ):
        with TestClient(app) as test_client:
            yield test_client

def test_deep_reasoning_routing_by_hardware_profile(registry):
    """
    Verifies that 'deep_reasoning' includes the Mac GLM orchestrator lane.
    deep_reasoning roles: [ultrathink, strategy, top-level, fallback]
    With preferred_device=mac-studio, glm-5.1:cloud should surface before cloud fallbacks.
    """
    chain = registry.route_task("deep_reasoning", preferred_device="mac-studio")

    # Chain must be non-empty
    assert len(chain) > 0, "deep_reasoning chain should not be empty"

    names = [m.name for m in chain]

    assert "glm-5.1:cloud" in names, "glm-5.1:cloud must be in deep_reasoning chain"
    assert "Qwen3.5-9B-MLX-4bit" in names, "Mac LM Studio fallback must remain in chain"

    # mac-studio models must be present
    mac_models = [m for m in chain if m.device == "mac-studio"]
    assert len(mac_models) > 0, "Should find at least one Mac model for deep reasoning roles"

    glm_idx = names.index("glm-5.1:cloud")
    general_cloud = [i for i, m in enumerate(chain)
                     if m.online and m.name not in ("glm-5.1:cloud", "claude-4-5-thinking")]
    assert all(glm_idx < ci for ci in general_cloud), \
        "glm-5.1:cloud should appear before general cloud fallbacks"

def test_code_analysis_routing_by_hardware_profile(registry):
    """
    Verifies 'code_analysis' routes correctly, preferring Windows LM Studio Qwen 27B.
    """
    chain = registry.route_task("code_analysis", preferred_device="win-rtx3080")

    # win-rtx3080 coder should be preferred
    first = chain[0]
    assert first.device == "win-rtx3080"
    assert "coding" in first.roles
    assert first.name == "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"


def test_autoresearch_prefers_windows_lmstudio(registry):
    chain = registry.route_task("autoresearch", preferred_device="win-rtx3080")
    assert chain[0].name == "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"
    assert chain[0].device == "win-rtx3080"
    assert "autoresearch-coder" in chain[0].roles


def test_orchestrate_hardware_selection(monkeypatch, client):
    """
    End-to-end check of /orchestrate selecting the right model per device.
    """
    async def always_ready(_candidate):
        return True, "mock-ready"

    monkeypatch.setattr("orchestrator.fastapi_app._candidate_availability", always_ready)

    # Task type 'coding' should pick win-rtx3080 if preferred
    resp = client.post("/orchestrate", json={
        "task": "def fib(n): return fib(n-1) + fib(n-2)",
        "task_type": "coding",
        "preferred_device": "win-rtx3080"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_model"]["device"] == "win-rtx3080"
    assert data["selected_model"]["name"] == "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"

    # Task type 'default' on mac-studio
    resp = client.post("/orchestrate", json={
        "task": "What is the capital of France?",
        "task_type": "default",
        "preferred_device": "mac-studio"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_model"]["device"] == "mac-studio"
    assert data["selected_model"]["name"] == "glm-5.1:cloud"


def test_orchestrate_falls_back_to_mac_lmstudio_when_glm_unavailable(monkeypatch, client):
    async def selective_ready(candidate):
        if candidate.name == "glm-5.1:cloud":
            return False, "rate-limited"
        return True, "mock-ready"

    monkeypatch.setattr("orchestrator.fastapi_app._candidate_availability", selective_ready)

    resp = client.post("/orchestrate", json={
        "task": "Summarize the release plan",
        "task_type": "default",
        "preferred_device": "mac-studio",
        "force": True,
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_model"]["name"] == "Qwen3.5-9B-MLX-4bit"
    availability = data["availability"]
    assert any(entry["detail"] == "rate-limited" for entry in availability.values())


def test_autoresearch_returns_user_action_when_no_local_backend_reachable(monkeypatch, client):
    async def none_ready(candidate):
        if candidate.backend in {"ollama", "lm-studio", "mlx"}:
            return False, "offline"
        return True, "not-probed"

    monkeypatch.setattr("orchestrator.fastapi_app._candidate_availability", none_ready)

    resp = client.post("/orchestrate", json={
        "task": "Run the next autoresearch loop",
        "task_type": "autoresearch",
        "preferred_device": "win-rtx3080",
        "force": True,
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "needs_user_action"
    assert "No viable local coder backend" in data["message"]

def test_coder_routes_to_lmstudio_when_ollama_offline():
    """Regression (PR #8 P1): win_ok=False, lms_ok=True → coder uses LM Studio, not Mac."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    async def run():
        with (
            patch("agent_launcher.check_remote_worker",   new=AsyncMock(return_value=False)),
            patch("agent_launcher.check_lmstudio_worker", new=AsyncMock(return_value=True)),
        ):
            import agent_launcher
            return await agent_launcher.initialize_environment()

    state = asyncio.run(run())
    assert state["coder_backend"] == "windows-lmstudio"
    assert "1234" in state["coder_endpoint"]
    assert state["distributed"] is True
    assert state["mac_only"] is False


def test_fallback_chain_across_hardware(registry):
    """
    Ensures that fallback chain includes models from other devices if local fails.
    """
    chain = registry.route_task("default", preferred_device="mac-studio")

    devices_in_chain = [m.device for m in chain]
    # Should include mac-studio first, then other devices as fallbacks
    assert devices_in_chain[0] == "mac-studio"
    assert any(d != "mac-studio" for d in devices_in_chain)
    assert "cloud" in devices_in_chain

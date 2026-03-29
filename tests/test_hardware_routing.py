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

# Ensure repo root is on PYTHONPATH
REPO_ROOT = Path(__file__).parent.parent
os.environ["OLLAMA_HOST"] = "http://127.0.0.1"

from orchestrator.model_registry import ModelRegistry
from orchestrator.fastapi_app import app

client = TestClient(app)

@pytest.fixture
def registry():
    return ModelRegistry(config_dir=str(REPO_ROOT / "config"))

def test_deep_reasoning_routing_by_hardware_profile(registry):
    """
    Verifies that 'deep_reasoning' task_type includes mac-studio models
    and that qwen3-30b-a3b-mlx (top-level, mac-studio) appears in the chain.
    deep_reasoning roles: [ultrathink, strategy, top-level, fallback]
    qwen3-30b-a3b-mlx has 'top-level' so it must appear in the chain.
    qwen3-30b-autoresearch-critic has 'strategy' (priority 6, win-rtx3080)
    and will precede it since no mac-studio model covers strategy.
    """
    chain = registry.route_task("deep_reasoning", preferred_device="mac-studio")

    # Chain must be non-empty
    assert len(chain) > 0, "deep_reasoning chain should not be empty"

    # qwen3-30b-a3b-mlx must appear somewhere in the chain (top-level role)
    names = [m.name for m in chain]
    assert "qwen3-30b-a3b-mlx" in names, "qwen3-30b-a3b-mlx must be in deep_reasoning chain"

    # mac-studio models must be present
    mac_models = [m for m in chain if m.device == "mac-studio"]
    assert len(mac_models) > 0, "Should find at least one Mac model for deep reasoning roles"

    # mac-studio models must appear before cloud-only models
    first_mac_idx = next(i for i, m in enumerate(chain) if m.device == "mac-studio")
    cloud_indices = [i for i, m in enumerate(chain) if m.online]
    assert all(first_mac_idx < ci for ci in cloud_indices), \
        "mac-studio models should appear before online/cloud models"

def test_code_analysis_routing_by_hardware_profile(registry):
    """
    Verifies 'code_analysis' routes correctly, preferring coding-specialist models.
    code_analysis roles: [ultrathink, coding, top-level, fallback]
    qwen3-coder-14b (win-rtx3080, priority=5) has role 'coding' and wins
    over qwen3-30b-a3b-lmstudio (priority=30, also has 'coding').
    """
    chain = registry.route_task("code_analysis", preferred_device="win-rtx3080")

    # win-rtx3080 coder should be preferred
    first = chain[0]
    assert first.device == "win-rtx3080"
    assert "coding" in first.roles
    assert "qwen3-coder-14b" in first.name

def test_orchestrate_hardware_selection():
    """
    End-to-end check of /orchestrate selecting the right model per device.
    """
    # Task type 'coding' should pick win-rtx3080 if preferred
    resp = client.post("/orchestrate", json={
        "task": "def fib(n): return fib(n-1) + fib(n-2)",
        "task_type": "coding",
        "preferred_device": "win-rtx3080"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_model"]["device"] == "win-rtx3080"
    assert "qwen3-coder-14b" in data["selected_model"]["name"] or "qwen3-30b-a3b-lmstudio" in data["selected_model"]["name"]

    # Task type 'default' on mac-studio
    resp = client.post("/orchestrate", json={
        "task": "What is the capital of France?",
        "task_type": "default",
        "preferred_device": "mac-studio"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["selected_model"]["device"] == "mac-studio"
    assert data["selected_model"]["name"] == "qwen3-30b-a3b-mlx"

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

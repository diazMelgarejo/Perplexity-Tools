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
from utils.hardware_policy import HardwareAffinityError, check_affinity, filter_models_for_platform, load_policy
import utils.hardware_policy as _hw_policy_mod


@pytest.fixture(autouse=True)
def clear_policy_cache():
    """Clear module-level _POLICY_CACHE before every test to prevent cross-test contamination."""
    _hw_policy_mod._POLICY_CACHE = None
    yield
    _hw_policy_mod._POLICY_CACHE = None


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


def test_hardware_policy_blocks_windows_only_on_mac():
    # Pass explicit policy so test is self-contained (live policy may evolve)
    policy = {
        "windows_only": ["Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"],
        "mac_only": [],
        "shared": [],
    }
    with pytest.raises(HardwareAffinityError, match="NEVER_MAC"):
        check_affinity("Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2", "mac", policy=policy)


def test_hardware_policy_blocks_mac_only_on_windows():
    # Pass explicit policy so test is self-contained (live policy may evolve)
    policy = {
        "windows_only": [],
        "mac_only": ["Qwen3.5-9B-MLX-4bit"],
        "shared": [],
    }
    with pytest.raises(HardwareAffinityError, match="NEVER_WIN"):
        check_affinity("Qwen3.5-9B-MLX-4bit", "win", policy=policy)


def test_hardware_policy_filter_is_case_insensitive():
    # Pass explicit policy: gemma-4-26B Windows GGUF model is windows_only in this test.
    # (Live policy uses 'shared' for all models due to LM Studio proxy — tests must be isolated.)
    policy = {
        "windows_only": ["gemma-4-26b-a4b-it-q4_k_m"],
        "mac_only": [],
        "shared": [],
    }
    models = [
        "Qwen3.5-9B-MLX-4bit",
        "gemma-4-26B-A4B-it-Q4_K_M",
        "unknown-local-experiment",
    ]
    assert filter_models_for_platform(models, "mac", policy=policy) == [
        "Qwen3.5-9B-MLX-4bit",
        "unknown-local-experiment",
    ]


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


def test_affinity_violation_does_not_silent_fallback():
    """Affinity errors in coder lane must escalate instead of silently degrading to Mac."""
    import asyncio
    from unittest.mock import AsyncMock, patch

    async def run():
        with (
            patch("agent_launcher.check_remote_worker", new=AsyncMock(return_value=False)),
            patch("agent_launcher.check_lmstudio_worker", new=AsyncMock(return_value=True)),
            patch("agent_launcher.check_affinity", side_effect=HardwareAffinityError("NEVER_MAC")),
        ):
            import agent_launcher
            return await agent_launcher.initialize_environment()

    with pytest.raises(HardwareAffinityError, match="NEVER_MAC"):
        asyncio.run(run())


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


# ---------------------------------------------------------------------------
# shared: section comment-out safety — parametrized across both parsers
# ---------------------------------------------------------------------------

COMMENTED_OUT_SHARED = """\
windows_only:
  - gemma-4-26b-a4b-it

mac_only:
  - gemma-4-e4b-it

# TODO(shared-models): out of scope until both machines verified online.
# shared:
"""

ABSENT_SHARED = """\
windows_only:
  - gemma-4-26b-a4b-it

mac_only:
  - gemma-4-e4b-it
"""

EXPLICIT_EMPTY_SHARED = """\
windows_only:
  - gemma-4-26b-a4b-it

mac_only:
  - gemma-4-e4b-it

shared:
"""


@pytest.mark.parametrize("yaml_text,label", [
    (COMMENTED_OUT_SHARED, "commented_out"),
    (ABSENT_SHARED, "absent"),
    (EXPLICIT_EMPTY_SHARED, "explicit_empty"),
])
def test_shared_section_variants_return_empty_list(tmp_path, yaml_text, label):
    """Both PyYAML and _simple_policy_parse must treat all 3 shared: variants identically."""
    policy_file = tmp_path / f"policy_{label}.yml"
    policy_file.write_text(yaml_text)

    # PyYAML path
    policy = load_policy(policy_path=policy_file, force_reload=True)
    assert policy.get("shared", []) == [], (
        f"[{label}] PyYAML path: shared should be empty list, got {policy.get('shared')}"
    )
    assert "gemma-4-26b-a4b-it" in policy.get("windows_only", [])
    assert "gemma-4-e4b-it" in policy.get("mac_only", [])

    # Force _simple_policy_parse path by making yaml unavailable
    import importlib
    import sys
    real_yaml = sys.modules.get("yaml")
    sys.modules["yaml"] = None  # type: ignore[assignment]
    _hw_policy_mod._POLICY_CACHE = None
    try:
        policy_fallback = load_policy(policy_path=policy_file, force_reload=True)
        assert policy_fallback.get("shared", []) == [], (
            f"[{label}] _simple_policy_parse path: shared should be empty, got {policy_fallback.get('shared')}"
        )
    finally:
        if real_yaml is not None:
            sys.modules["yaml"] = real_yaml
        else:
            del sys.modules["yaml"]
        _hw_policy_mod._POLICY_CACHE = None


def test_routing_affinity_keys_normalized():
    """All autoresearch routes in routing.yml must use 'affinity' key (not 'device_affinity')."""
    import yaml
    routing_path = REPO_ROOT / "config" / "routing.yml"
    routing = yaml.safe_load(routing_path.read_text())
    routes = routing.get("routes", {})
    for name, entry in routes.items():
        assert "device_affinity" not in entry, (
            f"Route '{name}' still uses deprecated 'device_affinity' key — migrate to 'affinity'"
        )

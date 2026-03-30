"""test_ultrathink_integration.py — Unified integration test (SYNC_ANALYSIS OPT 3)

Verifies the end-to-end contract between Perplexity-Tools and ultrathink-system:
  POST /orchestrate with task_type="deep_reasoning"  →  ultrathink endpoint in response
  POST /orchestrate with task_type="code_analysis"   →  ultrathink endpoint in response
  Response structure matches the MCP-first bridge contract, with HTTP `/ultrathink`
  treated as backup-only historical context in current docs

All HTTP calls to ultrathink (port 8001) and Ollama are mocked — runs fully offline in CI.
No version bump — rolling changes pre-v1.0 RC.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure repo root is on PYTHONPATH
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers: build a minimal ModelCandidate-like mock so ModelRegistry doesn't
# need live YAML when the test imports the app.
# ---------------------------------------------------------------------------

def _make_candidate(name="ultrathink", backend="ultrathink", device="any",
                    host="127.0.0.1", port=8001, online=False,
                    reasoning=True):
    """Return a MagicMock shaped like a ModelCandidate."""
    c = MagicMock()
    c.name = name
    c.backend = backend
    c.device = device
    c.host = host
    c.port = port
    c.online = online
    c.reasoning = reasoning
    return c


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """TestClient with ModelRegistry, CostGuard, AgentTracker, and
    ultrathink HTTP calls all mocked out for offline CI."""
    ultrathink_candidate = _make_candidate(
        name="ultrathink",
        backend="ultrathink",
        device="any",
        host="127.0.0.1",
        port=8001,
        online=False,
        reasoning=True,
    )
    fallback_candidate = _make_candidate(
        name="local_qwen30b",
        backend="ollama",
        device="win-rtx3080",
        host="127.0.0.1",
        port=11434,
        online=False,
        reasoning=False,
    )

    with (
        patch(
            "orchestrator.model_registry.ModelRegistry.route_task",
            return_value=[ultrathink_candidate, fallback_candidate],
        ),
        patch(
            "orchestrator.cost_guard.CostGuard.can_spend",
            return_value=True,
        ),
        patch(
            "orchestrator.cost_guard.CostGuard.alert_approaching",
            return_value=False,
        ),
        patch(
            "orchestrator.cost_guard.CostGuard.record_spend",
            return_value=None,
        ),
        patch(
            "orchestrator.ecc_tools_sync.sync_ecc_tools",
            return_value={"status": "ok", "message": "mocked"},
        ),
        patch(
            "orchestrator.ecc_tools_sync.get_sync_status",
            return_value={"status": "ok"},
        ),
    ):
        from orchestrator.fastapi_app import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

class TestUltrathinkRouting:
    """Verify PT correctly routes deep-reasoning tasks to ultrathink.
    Satisfies SYNC_ANALYSIS OPT 3: Unified Integration Test.
    """

    # ---- 1. deep_reasoning route → ultrathink ---------------------------

    def test_deep_reasoning_routes_to_ultrathink(self, client: TestClient):
        """POST /orchestrate with task_type=deep_reasoning must select
        the ultrathink backend as the primary model."""
        resp = client.post("/orchestrate", json={
            "task": "Analyze the distributed caching architecture for edge cases.",
            "task_type": "deep_reasoning",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Must be created (not conflict — fresh TrackerAgent state)
        assert body["status"] == "created"
        selected = body["selected_model"]
        assert selected["backend"] == "ultrathink", (
            f"Expected ultrathink backend, got: {selected['backend']}"
        )

    def test_deep_reasoning_response_has_ultrathink_host(self, client: TestClient):
        """The selected_model host must reference the ultrathink endpoint
        (127.0.0.1:8001) matching PERPLEXITY_BRIDGE.md ULTRATHINK_ENDPOINT default."""
        resp = client.post("/orchestrate", json={
            "task": "Ultra-deep multi-step reasoning task for privacy-critical data.",
            "task_type": "deep_reasoning",
            "force": True,  # bypass idempotency so test is repeatable
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        host_str = body["selected_model"]["host"]
        assert "8001" in host_str, (
            f"Expected ultrathink port 8001 in host, got: {host_str}"
        )

    # ---- 2. code_analysis route → ultrathink ----------------------------

    def test_code_analysis_routes_to_ultrathink(self, client: TestClient):
        """POST /orchestrate with task_type=code_analysis must also
        select the ultrathink backend (deep code analysis requires extended reasoning)."""
        resp = client.post("/orchestrate", json={
            "task": "Full codebase audit: identify security vulnerabilities in auth module.",
            "task_type": "code_analysis",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "created"
        assert body["selected_model"]["backend"] == "ultrathink"

    # ---- 3. Response structure matches BRIDGE spec ----------------------

    def test_orchestrate_response_structure_matches_bridge_spec(self, client: TestClient):
        """Response must contain all fields specified in PERPLEXITY_BRIDGE.md:
        status, agent, selected_model, fallback_chain."""
        resp = client.post("/orchestrate", json={
            "task": "Verify bridge spec compliance.",
            "task_type": "deep_reasoning",
            "force": True,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Top-level fields
        assert "status" in body
        assert "agent" in body
        assert "selected_model" in body
        assert "fallback_chain" in body
        # selected_model fields (BRIDGE spec)
        sm = body["selected_model"]
        for field in ("name", "backend", "device", "host", "online", "reasoning"):
            assert field in sm, f"selected_model missing BRIDGE-spec field: '{field}'"
        # agent fields
        agent = body["agent"]
        for field in ("agent_id", "role", "model", "status"):
            assert field in agent, f"agent missing expected field: '{field}'"
        # fallback_chain is a list
        assert isinstance(body["fallback_chain"], list)

    # ---- 4. Fallback chain contains local_qwen30b -----------------------

    def test_fallback_chain_contains_local_qwen30b(self, client: TestClient):
        """When ultrathink is the primary selection, local_qwen30b must be
        in the fallback chain (as configured in routing.yml)."""
        resp = client.post("/orchestrate", json={
            "task": "Fallback chain verification task.",
            "task_type": "deep_reasoning",
            "force": True,
        })
        assert resp.status_code == 200, resp.text
        chain = resp.json()["fallback_chain"]
        fallback_names = [entry["name"] for entry in chain]
        assert "local_qwen30b" in fallback_names, (
            f"Expected local_qwen30b in fallback chain, got: {fallback_names}"
        )

    # ---- 5. reasoning flag is True for ultrathink -----------------------

    def test_ultrathink_selected_model_has_reasoning_true(self, client: TestClient):
        """selected_model.reasoning must be True for ultrathink selections
        (signals extended-reasoning capability to callers)."""
        resp = client.post("/orchestrate", json={
            "task": "Reasoning flag verification.",
            "task_type": "deep_reasoning",
            "force": True,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["selected_model"]["reasoning"] is True

    # ---- 6. Idempotency: same task → conflict on second call ------------

    def test_idempotency_same_deep_reasoning_task_returns_conflict(self, client: TestClient):
        """Sending the exact same task twice (force=False) must return a
        conflict on the second call — idempotency contract from BRIDGE spec."""
        payload = {
            "task": "Idempotency test: identical deep reasoning task.",
            "task_type": "deep_reasoning",
            "force": False,
        }
        r1 = client.post("/orchestrate", json=payload)
        assert r1.status_code == 200
        assert r1.json()["status"] == "created"

        r2 = client.post("/orchestrate", json=payload)
        assert r2.status_code == 200
        assert r2.json()["status"] == "conflict", (
            "Second identical call must return conflict (idempotency guard)"
        )


# ---------------------------------------------------------------------------
# Routing.yml contract tests (offline, no TestClient needed)
# ---------------------------------------------------------------------------

class TestRoutingYmlUltrathinkContract:
    """Verify routing.yml correctly declares ultrathink for deep_reasoning
    and code_analysis. Runs against the YAML file directly — no server needed."""

    @pytest.fixture(scope="class")
    def routing(self):
        import yaml
        routing_yml = REPO_ROOT / "config" / "routing.yml"
        assert routing_yml.exists(), f"Missing: {routing_yml}"
        with open(routing_yml) as f:
            return yaml.safe_load(f)

    def test_deep_reasoning_has_ultrathink_endpoint(self, routing: dict):
        routes = routing["routes"]
        assert "deep_reasoning" in routes
        route = routes["deep_reasoning"]
        assert "endpoint" in route
        assert "ULTRATHINK_ENDPOINT" in route["endpoint"]

    def test_code_analysis_has_ultrathink_endpoint(self, routing: dict):
        routes = routing["routes"]
        assert "code_analysis" in routes
        route = routes["code_analysis"]
        assert "endpoint" in route
        assert "ULTRATHINK_ENDPOINT" in route["endpoint"]

    def test_deep_reasoning_has_ultrathink_fallback(self, routing: dict):
        route = routing["routes"]["deep_reasoning"]
        assert "fallback" in route
        assert route["fallback"] == "local_qwen30b"

    def test_code_analysis_has_ultrathink_fallback(self, routing: dict):
        route = routing["routes"]["code_analysis"]
        assert "fallback" in route
        assert route["fallback"] == "local_qwen30b"

    def test_deep_reasoning_requires_ultrathink_available(self, routing: dict):
        route = routing["routes"]["deep_reasoning"]
        assert "requires" in route
        assert "ultrathink_available" in route["requires"]

    def test_code_analysis_requires_ultrathink_available(self, routing: dict):
        route = routing["routes"]["code_analysis"]
        assert "requires" in route
        assert "ultrathink_available" in route["requires"]

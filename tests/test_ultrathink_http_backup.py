from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _make_candidate(
    name="ultrathink",
    backend="ultrathink",
    device="any",
    host="127.0.0.1",
    port=8001,
    online=False,
    reasoning=True,
):
    candidate = MagicMock()
    candidate.name = name
    candidate.backend = backend
    candidate.device = device
    candidate.host = host
    candidate.port = port
    candidate.online = online
    candidate.reasoning = reasoning
    return candidate


def test_orchestrate_calls_ultrathink_http_backup_with_mapped_depth(monkeypatch):
    monkeypatch.setenv("ULTRATHINK_HTTP_BACKUP_ENABLED", "true")
    monkeypatch.setenv("ULTRATHINK_ENDPOINT", "http://127.0.0.1:8001")

    ultrathink_candidate = _make_candidate()
    fallback_candidate = _make_candidate(
        name="local_qwen30b",
        backend="ollama",
        device="win-rtx3080",
        port=11434,
        reasoning=False,
    )
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "success",
                "result": "backup ok",
                "reasoning_depth": "ultra",
            }

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse()

    with (
        patch(
            "orchestrator.model_registry.ModelRegistry.route_task",
            return_value=[ultrathink_candidate, fallback_candidate],
        ),
        patch("orchestrator.cost_guard.CostGuard.can_spend", return_value=True),
        patch("orchestrator.cost_guard.CostGuard.alert_approaching", return_value=False),
        patch("orchestrator.cost_guard.CostGuard.record_spend", return_value=None),
        patch(
            "orchestrator.ecc_tools_sync.sync_ecc_tools",
            return_value={"status": "ok", "message": "mocked"},
        ),
        patch(
            "orchestrator.ecc_tools_sync.get_sync_status",
            return_value={"status": "ok"},
        ),
        patch("orchestrator.ultrathink_bridge.httpx.post", side_effect=fake_post),
    ):
        from orchestrator.fastapi_app import app

        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.post(
                "/orchestrate",
                json={
                    "task": "Analyze a privacy-critical distributed system failure.",
                    "task_type": "deep_reasoning",
                    "force": True,
                },
            )

    assert response.status_code == 200, response.text
    body = response.json()
    assert captured["url"] == "http://127.0.0.1:8001/ultrathink"
    assert captured["json"]["optimize_for"] == "reliability"
    assert captured["json"]["reasoning_depth"] == "ultra"
    assert body["ultrathink_http_backup"]["request"]["reasoning_depth"] == "ultra"
    assert body["ultrathink_http_backup"]["response"]["reasoning_depth"] == "ultra"

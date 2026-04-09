from __future__ import annotations

import asyncio
import json
from pathlib import Path

import orchestrator.control_plane as control_plane


def test_preflight_autoresearch_reports_handshake(monkeypatch, tmp_path):
    monkeypatch.setattr(
        control_plane.autoresearch_bridge,
        "preflight",
        lambda run_tag=None: {
            "sync_ok": True,
            "sha": "abc123def456",
            "error": "",
            "swarm_state_initialised": True,
        },
    )
    monkeypatch.setattr(
        control_plane.autoresearch_bridge,
        "SWARM_STATE_FILE",
        tmp_path / "swarm_state.md",
    )

    result = control_plane.preflight_autoresearch(run_tag="testrun", gateway_ready=True)

    assert result["ready"] is True
    assert [stage["stage"] for stage in result["handshake"]] == [
        "openclaw_ready",
        "autoresearch_sync",
        "swarm_state_ready",
    ]


def test_bootstrap_runtime_writes_resolved_payload(monkeypatch, tmp_path):
    async def fake_resolve_routing_state():
        return {
            "manager_backend": "mac-lmstudio",
            "manager_endpoint": "http://127.0.0.1:1234",
            "manager_model": "Qwen3.5-9B-MLX-4bit",
            "coder_backend": "windows-lmstudio",
            "coder_endpoint": "http://192.168.0.10:1234",
            "coder_model": "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2",
            "distributed": True,
        }

    async def fake_reconcile_gateway(force: bool = False):
        return {
            "ok": True,
            "gateway_ready": True,
            "gateway_url": "http://127.0.0.1:18789",
            "role_routing": {
                "topology": "manager-local_researcher-remote",
            },
            "openclaw_config": {"gateway": {"port": 18789}},
        }

    monkeypatch.setattr(
        control_plane,
        "ensure_credentials",
        lambda **kwargs: {
            "configured": True,
            "ready_for_api": False,
            "validated": False,
            "auth_mode": "web-login",
            "has_api_key": False,
            "message": "Web-login fallback selected.",
        },
    )
    monkeypatch.setattr(control_plane, "resolve_routing_state", fake_resolve_routing_state)
    monkeypatch.setattr(control_plane, "reconcile_gateway", fake_reconcile_gateway)
    monkeypatch.setattr(
        control_plane,
        "preflight_autoresearch",
        lambda **kwargs: {
            "sync_ok": True,
            "ready": True,
            "sha": "abc123def456",
            "handshake": [{"stage": "openclaw_ready", "ok": True}],
        },
    )

    runtime_path = tmp_path / "runtime_payload.json"
    payload = asyncio.run(
        control_plane.bootstrap_runtime(
            interactive=False,
            runtime_state_path=runtime_path,
            print_progress=False,
        )
    )

    assert runtime_path.exists()
    saved = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert payload["paths"]["runtime_state"] == str(runtime_path.resolve())
    assert saved["gateway"]["gateway_url"] == "http://127.0.0.1:18789"
    assert saved["routing"]["distributed"] is True
    assert [stage["name"] for stage in saved["stages"]] == [
        "perplexity_credentials",
        "routing",
        "gateway",
        "autoresearch",
    ]

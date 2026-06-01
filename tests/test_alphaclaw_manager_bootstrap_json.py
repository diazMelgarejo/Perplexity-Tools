"""Tests for alphaclaw_bootstrap --json stdout parsing in alphaclaw_manager."""

from __future__ import annotations

import json

from orchestrator.alphaclaw_manager import _parse_bootstrap_json


def test_parse_bootstrap_json_pure_payload():
    payload = {
        "gateway_ready": True,
        "gateway_url": "http://127.0.0.1:18789",
        "openclaw_config": {"gateway": {"port": 18789}},
        "role_routing": {"topology": "single"},
    }
    assert _parse_bootstrap_json(json.dumps(payload)) == payload


def test_parse_bootstrap_json_mixed_log_lines_and_indented_json():
    payload = {
        "ok": True,
        "gateway_ready": True,
        "gateway_url": "http://127.0.0.1:18789",
        "openclaw_config": {"agents": {}},
        "role_routing": {"coder_backend": "windows-lmstudio"},
    }
    stdout = (
        "[alphaclaw] → Probing candidate ports\n"
        "[alphaclaw] ✓ Gateway already running\n"
        + json.dumps(payload, indent=2)
        + "\n"
    )
    assert _parse_bootstrap_json(stdout) == payload


def test_parse_bootstrap_json_returns_empty_on_garbage():
    assert _parse_bootstrap_json("") == {}
    assert _parse_bootstrap_json("[alphaclaw] no json here\n") == {}

"""alphaclaw_manager bootstrap JSON parsing and gateway state."""
from __future__ import annotations

import json

from orchestrator.alphaclaw_manager import _parse_bootstrap_json


def test_parse_bootstrap_json_accepts_pure_json():
    payload = {"ok": True, "openclaw_config": {"agents": {"list": []}}}
    assert _parse_bootstrap_json(json.dumps(payload)) == payload


def test_parse_bootstrap_json_extracts_trailing_blob_after_progress_logs():
    payload = {
        "ok": True,
        "gateway_ready": True,
        "gateway_url": "http://127.0.0.1:18789",
        "openclaw_config": {"gateway": {"port": 18789}},
        "role_routing": {"topology": "manager-local_researcher-remote"},
    }
    stdout = "\n".join(
        [
            "[alphaclaw] → Probing candidate ports: [3000, 18789]",
            "[alphaclaw] ✓ Gateway already running — commandeering",
            json.dumps(payload, indent=2),
        ]
    )
    assert _parse_bootstrap_json(stdout) == payload


def test_parse_bootstrap_json_returns_empty_on_garbage():
    assert _parse_bootstrap_json("[alphaclaw] no json here\n") == {}

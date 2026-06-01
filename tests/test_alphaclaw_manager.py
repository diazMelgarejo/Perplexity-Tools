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


# ─── Additional edge-case tests ────────────────────────────────────────────────


def test_parse_bootstrap_json_empty_string_returns_empty():
    assert _parse_bootstrap_json("") == {}


def test_parse_bootstrap_json_whitespace_only_returns_empty():
    assert _parse_bootstrap_json("   \n\t  ") == {}


def test_parse_bootstrap_json_json_array_returns_empty():
    # The function requires a dict; arrays must be rejected.
    assert _parse_bootstrap_json(json.dumps([{"ok": True}])) == {}


def test_parse_bootstrap_json_json_string_scalar_returns_empty():
    assert _parse_bootstrap_json(json.dumps("ok")) == {}


def test_parse_bootstrap_json_json_number_scalar_returns_empty():
    assert _parse_bootstrap_json(json.dumps(42)) == {}


def test_parse_bootstrap_json_json_bool_scalar_returns_empty():
    assert _parse_bootstrap_json(json.dumps(True)) == {}


def test_parse_bootstrap_json_json_null_returns_empty():
    assert _parse_bootstrap_json(json.dumps(None)) == {}


def test_parse_bootstrap_json_minimal_dict_returned_as_is():
    payload = {"ok": True}
    assert _parse_bootstrap_json(json.dumps(payload)) == payload


def test_parse_bootstrap_json_preserves_openclaw_config_key():
    payload = {"ok": True, "openclaw_config": {"gateway": {"port": 18789}}}
    result = _parse_bootstrap_json(json.dumps(payload))
    assert result["openclaw_config"] == {"gateway": {"port": 18789}}


def test_parse_bootstrap_json_preserves_role_routing_key():
    payload = {"ok": True, "role_routing": {"topology": "manager-local"}}
    result = _parse_bootstrap_json(json.dumps(payload))
    assert result["role_routing"] == {"topology": "manager-local"}


def test_parse_bootstrap_json_empty_dict_returns_empty_dict():
    assert _parse_bootstrap_json("{}") == {}


def test_parse_bootstrap_json_deeply_nested_payload_preserved():
    payload = {
        "ok": True,
        "openclaw_config": {
            "agents": {"list": ["manager", "local_researcher"]},
            "gateway": {"port": 18789, "host": "127.0.0.1"},
        },
        "role_routing": {"topology": "manager-local_researcher-remote"},
        "gateway_url": "http://127.0.0.1:18789",
        "gateway_ready": True,
    }
    assert _parse_bootstrap_json(json.dumps(payload)) == payload


def test_parse_bootstrap_json_truncated_json_returns_empty():
    truncated = '{"ok": true, "openclaw_config": {'
    assert _parse_bootstrap_json(truncated) == {}


def test_parse_bootstrap_json_strips_surrounding_whitespace():
    payload = {"ok": True}
    padded = "  \n" + json.dumps(payload) + "\n  "
    assert _parse_bootstrap_json(padded) == payload

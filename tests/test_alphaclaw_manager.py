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


# ── Additional edge-case / regression tests ───────────────────────────────────


def test_parse_bootstrap_json_returns_empty_on_empty_string():
    assert _parse_bootstrap_json("") == {}


def test_parse_bootstrap_json_returns_empty_on_none():
    # None should be treated as empty input, not raise.
    assert _parse_bootstrap_json(None) == {}  # type: ignore[arg-type]


def test_parse_bootstrap_json_returns_empty_on_whitespace_only():
    assert _parse_bootstrap_json("   \n\t  ") == {}


def test_parse_bootstrap_json_returns_empty_for_json_array():
    # A top-level JSON array is not a dict — must return {}.
    assert _parse_bootstrap_json(json.dumps([1, 2, 3])) == {}


def test_parse_bootstrap_json_returns_empty_for_json_string():
    # A JSON-encoded string is not a dict.
    assert _parse_bootstrap_json(json.dumps("just a string")) == {}


def test_parse_bootstrap_json_returns_empty_for_json_number():
    assert _parse_bootstrap_json("42") == {}


def test_parse_bootstrap_json_returns_empty_for_json_null():
    assert _parse_bootstrap_json("null") == {}


def test_parse_bootstrap_json_accepts_minimal_ok_payload():
    # Minimal valid gateway-ready shape.
    payload = {"ok": True, "gateway_ready": True, "gateway_url": "http://127.0.0.1:3000"}
    assert _parse_bootstrap_json(json.dumps(payload)) == payload


def test_parse_bootstrap_json_preserves_nested_openclaw_config():
    # Nested config dicts must round-trip exactly.
    payload = {
        "ok": True,
        "openclaw_config": {
            "gateway": {"port": 18789, "host": "127.0.0.1"},
            "agents": {"list": ["manager", "researcher"]},
        },
        "role_routing": {"topology": "manager-local_researcher-remote"},
    }
    assert _parse_bootstrap_json(json.dumps(payload)) == payload


def test_parse_bootstrap_json_returns_empty_for_truncated_json():
    # Truncated / malformed JSON must not raise — return {} gracefully.
    assert _parse_bootstrap_json('{"ok": true, "gateway_url":') == {}


def test_parse_bootstrap_json_accepts_payload_with_extra_keys():
    # Unknown future keys must be preserved, not silently dropped.
    payload = {"ok": True, "future_key": "future_value", "nested": {"a": 1}}
    result = _parse_bootstrap_json(json.dumps(payload))
    assert result == payload
    assert result["future_key"] == "future_value"

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


# ── Additional boundary / regression tests ────────────────────────────────────


def test_parse_bootstrap_json_accepts_dict_with_ok_false():
    # A dict where ok is False is still a valid dict — must be returned, not
    # treated as an error sentinel.
    payload = {"ok": False, "error": "gateway_not_ready"}
    result = _parse_bootstrap_json(json.dumps(payload))
    assert result == payload
    assert result["ok"] is False


def test_parse_bootstrap_json_preserves_unicode_values():
    # Unicode in string values must round-trip without corruption.
    payload = {"ok": True, "gateway_url": "http://127.0.0.1:18789", "label": "✓ ready — café"}
    assert _parse_bootstrap_json(json.dumps(payload)) == payload


def test_parse_bootstrap_json_preserves_boolean_values():
    # Both True and False at any level must be preserved as Python bools.
    payload = {"ok": True, "gateway_ready": False, "flags": {"debug": True}}
    result = _parse_bootstrap_json(json.dumps(payload))
    assert result["ok"] is True
    assert result["gateway_ready"] is False
    assert result["flags"]["debug"] is True


def test_parse_bootstrap_json_preserves_list_values_in_dict():
    # Lists nested inside the dict must be preserved verbatim.
    payload = {"ok": True, "ports": [3000, 18789], "agents": ["manager", "researcher"]}
    result = _parse_bootstrap_json(json.dumps(payload))
    assert result["ports"] == [3000, 18789]
    assert result["agents"] == ["manager", "researcher"]


def test_parse_bootstrap_json_returns_empty_for_json_boolean_true():
    # Top-level JSON `true` is not a dict.
    assert _parse_bootstrap_json("true") == {}


def test_parse_bootstrap_json_returns_empty_for_json_boolean_false():
    # Top-level JSON `false` is not a dict.
    assert _parse_bootstrap_json("false") == {}


def test_parse_bootstrap_json_handles_deeply_nested_structure():
    # Deep nesting must round-trip without truncation.
    payload = {
        "ok": True,
        "openclaw_config": {
            "gateway": {
                "port": 18789,
                "host": "127.0.0.1",
                "tls": {"enabled": False, "cert": None},
            },
            "agents": {
                "manager": {"model": "claude-3-5-sonnet", "max_tokens": 8192},
                "researcher": {"model": "claude-3-haiku", "max_tokens": 4096},
            },
        },
    }
    assert _parse_bootstrap_json(json.dumps(payload)) == payload


def test_parse_bootstrap_json_returns_empty_for_leading_trailing_garbage():
    # Garbage surrounding an otherwise-valid JSON object makes the whole
    # input unparseable — must return {} without raising.
    assert _parse_bootstrap_json('prefix {"ok": true} suffix') == {}


def test_parse_bootstrap_json_returns_empty_for_json_with_trailing_comma():
    # Trailing commas are not valid JSON — must not raise.
    assert _parse_bootstrap_json('{"ok": true,}') == {}


def test_parse_bootstrap_json_integer_zero_port_preserved():
    # Edge-case: port 0 is a valid integer and must not be dropped.
    payload = {"ok": True, "port": 0}
    result = _parse_bootstrap_json(json.dumps(payload))
    assert result["port"] == 0

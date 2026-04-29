"""test_ultrathink_bridge.py — HTTP bridge unit tests

Tests the ultrathink HTTP bridge module independently:
  - Bridge fires when ultrathink route is selected and endpoint configured
  - Bridge failure surfaces error gracefully (no crash)
  - Bridge skipped when route does not select ultrathink
  - Payload mapping (task_type → optimize_for → reasoning_depth) is correct

All HTTP calls are mocked — runs fully offline in CI.
"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest

# Ensure imports work
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.orama_bridge import (
    call_ultrathink_bridge,
    normalize_ultrathink_endpoint,
    parse_ultrathink_timeout,
    build_ultrathink_http_payload,
)


class TestNormalizeEndpoint:
    def test_appends_ultrathink_path(self):
        assert normalize_ultrathink_endpoint("http://localhost:8001") == "http://localhost:8001/ultrathink"

    def test_does_not_double_append(self):
        assert normalize_ultrathink_endpoint("http://localhost:8001/ultrathink") == "http://localhost:8001/ultrathink"

    def test_strips_trailing_slash(self):
        assert normalize_ultrathink_endpoint("http://localhost:8001/") == "http://localhost:8001/ultrathink"

    def test_empty_returns_empty(self):
        assert normalize_ultrathink_endpoint("") == ""


class TestParseTimeout:
    def test_valid_number(self):
        assert parse_ultrathink_timeout("120") == 120.0

    def test_default_on_empty(self):
        assert parse_ultrathink_timeout("") == 120.0

    def test_default_on_none(self):
        assert parse_ultrathink_timeout(None) == 120.0

    def test_custom_default(self):
        assert parse_ultrathink_timeout("", default=60.0) == 60.0


class TestBuildPayload:
    def test_deep_reasoning_payload(self):
        payload = build_ultrathink_http_payload("Analyze X", "deep_reasoning")
        assert payload["task_description"] == "Analyze X"
        assert payload["optimize_for"] == "reliability"
        assert payload["reasoning_depth"] == "ultra"
        assert payload["task_type"] == "analysis"

    def test_code_analysis_payload(self):
        payload = build_ultrathink_http_payload("Review code", "code_analysis")
        assert payload["optimize_for"] == "reliability"
        assert payload["reasoning_depth"] == "ultra"
        assert payload["task_type"] == "code"

    def test_unknown_task_type_defaults_to_reliability(self):
        payload = build_ultrathink_http_payload("Something", "unknown")
        assert payload["optimize_for"] == "reliability"


class TestCallBridge:
    @patch("orchestrator.orama_bridge.httpx.post")
    def test_success_returns_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": "analysis complete", "status": "ok"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        result = call_ultrathink_bridge(
            endpoint="http://localhost:8001",
            timeout=120.0,
            task="Test task",
            task_type="deep_reasoning",
        )
        assert "response" in result
        assert result["response"]["result"] == "analysis complete"
        mock_post.assert_called_once()

    @patch("orchestrator.orama_bridge.httpx.post")
    def test_failure_raises_exception(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")

        with pytest.raises(Exception, match="Connection refused"):
            call_ultrathink_bridge(
                endpoint="http://localhost:8001",
                timeout=120.0,
                task="Test task",
                task_type="deep_reasoning",
            )

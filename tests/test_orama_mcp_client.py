"""tests/test_ultrathink_mcp_client.py
======================================
Tests for MCP-Optional transport: UltrathinkMCPClient and
call_ultrathink_mcp_or_bridge().

Critical branches:
1. MCP success — HTTP path is never touched.
2. MCP failure (any exception) → HTTP fallback with correct mapped payload.
3. Stub response detection → falls back to HTTP.
4. ULTRATHINK_MCP_SERVER_CMD unset → HTTP only, no MCP attempt.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

_GOOD_MCP_RESULT: Dict[str, Any] = {
    "task_id": "test-uuid-1234",
    "status": "done",
    "result": "This is the deep reasoning output.",
    "model_used": "qwen3.5:35b-a3b-q4_K_M",
    "execution_time_ms": 3200,
}

_STUB_MCP_RESULT: Dict[str, Any] = {
    "task_id": "test-uuid-5678",
    "status": "started",
    "message": "Poll ultrathink_status for updates.",
}

_HTTP_MOCK_RESPONSE = {
    "status": "success",
    "result": "HTTP fallback response.",
    "model_used": "qwen3:8b-instruct",
    "execution_time_ms": 1200,
    "reasoning_depth": "ultra",
}


# ── call_ultrathink_mcp_or_bridge tests ───────────────────────────────────────

class TestCallUltrathinkMcpOrBridge:

    @pytest.mark.asyncio
    async def test_mcp_success_does_not_touch_http(self, monkeypatch):
        """When MCP succeeds, httpx.AsyncClient.post must never be called."""
        monkeypatch.setenv("ULTRATHINK_MCP_SERVER_CMD", "python fake_server.py")

        mock_client = MagicMock()
        mock_client.call_solve = AsyncMock(return_value=_GOOD_MCP_RESULT)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        http_post = AsyncMock()

        with patch(
            "orchestrator.orama_mcp_client.UltrathinkMCPClient",
            return_value=mock_client,
        ), patch("httpx.AsyncClient.post", http_post):
            from orchestrator.orama_bridge import call_ultrathink_mcp_or_bridge
            result = await call_ultrathink_mcp_or_bridge(
                endpoint="http://localhost:8001",
                timeout=30.0,
                task="explain quantum entanglement",
                task_type="deep_reasoning",
            )

        assert result["transport"] == "mcp"
        assert result["result"] == _GOOD_MCP_RESULT
        http_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_mcp_failure_falls_back_to_http_with_correct_payload(self, monkeypatch):
        """When MCP raises, HTTP fallback is called with the correct mapped payload."""
        monkeypatch.setenv("ULTRATHINK_MCP_SERVER_CMD", "python fake_server.py")

        mock_client = AsyncMock()
        mock_client.call_solve = AsyncMock(side_effect=RuntimeError("subprocess crashed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = _HTTP_MOCK_RESPONSE
        mock_http_response.raise_for_status = MagicMock()

        with patch(
            "orchestrator.orama_mcp_client.UltrathinkMCPClient",
            return_value=mock_client,
        ), patch("httpx.AsyncClient") as mock_async_client_cls:
            mock_async_client_instance = MagicMock()
            mock_async_client_instance.post = AsyncMock(return_value=mock_http_response)
            mock_async_client_instance.__aenter__ = AsyncMock(return_value=mock_async_client_instance)
            mock_async_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_async_client_cls.return_value = mock_async_client_instance

            from orchestrator.orama_bridge import (
                build_ultrathink_http_payload,
                call_ultrathink_mcp_or_bridge,
            )
            result = await call_ultrathink_mcp_or_bridge(
                endpoint="http://localhost:8001",
                timeout=30.0,
                task="refactor this function",
                task_type="code_analysis",
            )

        assert result["transport"] == "http"
        assert result["response"] == _HTTP_MOCK_RESPONSE

        # Verify payload is the correct mapped value
        expected_payload = build_ultrathink_http_payload("refactor this function", "code_analysis")
        mock_async_client_instance.post.assert_called_once()
        _, call_kwargs = mock_async_client_instance.post.call_args
        assert call_kwargs["json"] == expected_payload

    @pytest.mark.asyncio
    async def test_stub_response_triggers_http_fallback(self, monkeypatch):
        """Stub response (no 'result' key) raises ValueError → HTTP fallback."""
        monkeypatch.setenv("ULTRATHINK_MCP_SERVER_CMD", "python fake_server.py")

        mock_client = MagicMock()
        mock_client.call_solve = AsyncMock(
            side_effect=ValueError("MCP _solve() returned stub response")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = _HTTP_MOCK_RESPONSE
        mock_http_response.raise_for_status = MagicMock()

        with patch(
            "orchestrator.orama_mcp_client.UltrathinkMCPClient",
            return_value=mock_client,
        ), patch("httpx.AsyncClient") as mock_async_client_cls:
            mock_async_client_instance = MagicMock()
            mock_async_client_instance.post = AsyncMock(return_value=mock_http_response)
            mock_async_client_instance.__aenter__ = AsyncMock(return_value=mock_async_client_instance)
            mock_async_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_async_client_cls.return_value = mock_async_client_instance

            from orchestrator.orama_bridge import call_ultrathink_mcp_or_bridge
            result = await call_ultrathink_mcp_or_bridge(
                endpoint="http://localhost:8001",
                timeout=30.0,
                task="design a caching layer",
                task_type="deep_reasoning",
            )

        assert result["transport"] == "http"
        mock_async_client_instance.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_mcp_cmd_goes_straight_to_http(self, monkeypatch):
        """When ULTRATHINK_MCP_SERVER_CMD is unset, MCP is never attempted."""
        monkeypatch.delenv("ULTRATHINK_MCP_SERVER_CMD", raising=False)

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = _HTTP_MOCK_RESPONSE
        mock_http_response.raise_for_status = MagicMock()

        with patch(
            "orchestrator.orama_mcp_client.UltrathinkMCPClient"
        ) as mock_mcp_cls, patch("httpx.AsyncClient") as mock_async_client_cls:
            mock_async_client_instance = MagicMock()
            mock_async_client_instance.post = AsyncMock(return_value=mock_http_response)
            mock_async_client_instance.__aenter__ = AsyncMock(return_value=mock_async_client_instance)
            mock_async_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_async_client_cls.return_value = mock_async_client_instance

            from orchestrator.orama_bridge import call_ultrathink_mcp_or_bridge
            result = await call_ultrathink_mcp_or_bridge(
                endpoint="http://localhost:8001",
                timeout=30.0,
                task="summarize this document",
                task_type="deep_reasoning",
            )

        assert result["transport"] == "http"
        mock_mcp_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_total_mcp_timeout_falls_back_to_http(self, monkeypatch):
        monkeypatch.setenv("ULTRATHINK_MCP_SERVER_CMD", "python fake_server.py")

        class _SlowClient:
            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                await asyncio.sleep(0.05)
                return self

            async def __aexit__(self, *_args):
                return False

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = _HTTP_MOCK_RESPONSE
        mock_http_response.raise_for_status = MagicMock()

        with patch(
            "orchestrator.orama_mcp_client.UltrathinkMCPClient",
            _SlowClient,
        ), patch("httpx.AsyncClient") as mock_async_client_cls:
            mock_async_client_instance = MagicMock()
            mock_async_client_instance.post = AsyncMock(return_value=mock_http_response)
            mock_async_client_instance.__aenter__ = AsyncMock(return_value=mock_async_client_instance)
            mock_async_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_async_client_cls.return_value = mock_async_client_instance

            from orchestrator.orama_bridge import call_ultrathink_mcp_or_bridge

            result = await call_ultrathink_mcp_or_bridge(
                endpoint="http://localhost:8001",
                timeout=0.01,
                task="timed MCP call",
                task_type="deep_reasoning",
            )

        assert result["transport"] == "http"
        mock_async_client_instance.post.assert_called_once()


# ── UltrathinkMCPClient.call_solve unit tests ─────────────────────────────────

class TestUltrathinkMCPClientCallSolve:

    @pytest.mark.asyncio
    async def test_call_solve_raises_on_stub_response(self):
        """call_solve raises ValueError when server returns stub (no 'result' key)."""
        from orchestrator.orama_mcp_client import UltrathinkMCPClient

        client = UltrathinkMCPClient(["python", "fake.py"], timeout=10.0)
        client._proc = MagicMock()
        client._proc.returncode = None

        stub_rpc_response = {"jsonrpc": "2.0", "id": 1, "result": _STUB_MCP_RESULT}
        client._rpc = AsyncMock(return_value=stub_rpc_response)

        with pytest.raises(ValueError, match="stub response"):
            await client.call_solve("test task", "deep_reasoning")

    @pytest.mark.asyncio
    async def test_call_solve_returns_result_on_success(self):
        """call_solve returns the result dict when server returns a full response."""
        from orchestrator.orama_mcp_client import UltrathinkMCPClient

        client = UltrathinkMCPClient(["python", "fake.py"], timeout=10.0)
        client._proc = MagicMock()
        client._proc.returncode = None

        good_rpc_response = {"jsonrpc": "2.0", "id": 1, "result": _GOOD_MCP_RESULT}
        client._rpc = AsyncMock(return_value=good_rpc_response)

        result = await client.call_solve("test task", "deep_reasoning")
        assert result == _GOOD_MCP_RESULT
        assert result["status"] == "done"
        assert "result" in result


class TestUltrathinkMCPClientStop:

    @pytest.mark.asyncio
    async def test_stop_kills_and_waits_when_terminate_times_out(self):
        from orchestrator.orama_mcp_client import UltrathinkMCPClient

        client = UltrathinkMCPClient(["python", "fake.py"], timeout=10.0)
        stdin = MagicMock()
        stdin.close = MagicMock()
        stdin.wait_closed = AsyncMock()

        proc = MagicMock()
        proc.returncode = None
        proc.stdin = stdin
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        client._proc = proc

        async def _timeout_and_close(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError

        with patch("orchestrator.orama_mcp_client.asyncio.wait_for", side_effect=_timeout_and_close):
            await client.stop()

        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()
        stdin.close.assert_called_once()
        stdin.wait_closed.assert_awaited_once()
        assert client._proc is None

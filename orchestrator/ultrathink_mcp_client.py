"""ultrathink_mcp_client.py
==========================
Async MCP client for ultrathink-system stdio JSON-RPC server.

Spawns the ultrathink orchestration server as a subprocess, sends `initialize`,
then issues `tools/call` for `ultrathink_solve`. Returns the full result dict on
success. Raises on every failure condition so the caller can fall back to HTTP.

Failure conditions (all raise, triggering HTTP fallback):
- Subprocess fails to start or exits unexpectedly
- `initialize` response missing `capabilities.tools`
- asyncio.TimeoutError on any readline
- JSON-RPC error response (`"error"` key present)
- Malformed/non-JSON stdout
- Stub response: `status != "done"` or `"result"` key absent

Usage:
    async with UltrathinkMCPClient(server_cmd, timeout=120.0) as client:
        result = await client.call_solve(task, task_type)
"""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from typing import Any, Dict, List, Optional

log = logging.getLogger("orchestrator.ultrathink_mcp_client")

TASK_TYPE_TO_OPTIMIZE_FOR: Dict[str, str] = {
    "deep_reasoning": "reliability",
    "code_analysis": "reliability",
}

_MCP_PROTOCOL_VERSION = "2024-11-05"


class UltrathinkMCPClient:
    """Async MCP client — spawns ultrathink stdio server, calls ultrathink_solve."""

    def __init__(self, server_cmd: List[str], timeout: float = 120.0) -> None:
        self._cmd = server_cmd
        self._timeout = timeout
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._req_id = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def _start(self) -> None:
        """Spawn subprocess and complete MCP initialize handshake."""
        self._proc = await asyncio.create_subprocess_exec(
            *self._cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        init_response = await self._rpc(
            "initialize",
            {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "clientInfo": {"name": "perplexity-tools", "version": "0.9.9.0"},
                "capabilities": {},
            },
        )
        caps = init_response.get("result", {}).get("capabilities", {})
        if "tools" not in caps:
            raise RuntimeError(
                f"MCP server missing 'tools' capability: {init_response}"
            )

    async def stop(self) -> None:
        """Terminate subprocess cleanly."""
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except Exception:
                self._proc.kill()
        self._proc = None

    async def __aenter__(self) -> "UltrathinkMCPClient":
        await self._start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    # ── JSON-RPC transport ─────────────────────────────────────────────────────

    async def _rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send one JSON-RPC request; return the parsed response dict."""
        if self._proc is None or self._proc.returncode is not None:
            raise RuntimeError("MCP subprocess is not running")

        self._req_id += 1
        request = {"jsonrpc": "2.0", "id": self._req_id, "method": method, "params": params}
        line = json.dumps(request) + "\n"

        assert self._proc.stdin is not None
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

        assert self._proc.stdout is not None
        raw = await asyncio.wait_for(
            self._proc.stdout.readline(), timeout=self._timeout
        )
        if not raw:
            raise RuntimeError("MCP subprocess closed stdout unexpectedly")

        response = json.loads(raw.decode().strip())
        if "error" in response:
            raise RuntimeError(
                f"MCP JSON-RPC error: {response['error']}"
            )
        return response

    # ── Public API ─────────────────────────────────────────────────────────────

    async def call_solve(self, task: str, task_type: str) -> Dict[str, Any]:
        """Call ultrathink_solve; raise if result is absent or stub-only."""
        optimize_for = TASK_TYPE_TO_OPTIMIZE_FOR.get(task_type, "reliability")
        response = await self._rpc(
            "tools/call",
            {
                "name": "ultrathink_solve",
                "arguments": {"task": task, "optimize_for": optimize_for},
            },
        )
        result = response.get("result", {})

        # Stub detection: server returns {status: "started"} without "result" key
        if result.get("status") != "done" or "result" not in result:
            raise ValueError(
                f"MCP _solve() returned stub response (status={result.get('status')!r}); "
                "falling back to HTTP bridge"
            )

        log.info(
            "MCP call_solve success | task_type=%s model=%s exec_ms=%s",
            task_type,
            result.get("model_used", "unknown"),
            result.get("execution_time_ms", "?"),
        )
        return result

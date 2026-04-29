from __future__ import annotations

import asyncio
import logging
import os
import shlex
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger("orchestrator.orama_bridge")


OPTIMIZE_FOR_TO_REASONING_DEPTH = {
    "reliability": "ultra",
    "creativity": "deep",
    "speed": "standard",
}

TASK_TYPE_TO_OPTIMIZE_FOR = {
    "deep_reasoning": "reliability",
    "code_analysis": "reliability",
}

TASK_TYPE_TO_HTTP_TASK_TYPE = {
    "deep_reasoning": "analysis",
    "code_analysis": "code",
}


def normalize_ultrathink_endpoint(endpoint: str) -> str:
    expanded = os.path.expandvars(str(endpoint or "")).rstrip("/")
    if not expanded:
        return ""
    if expanded.endswith("/ultrathink"):
        return expanded
    return f"{expanded}/ultrathink"


def parse_ultrathink_timeout(timeout_value: Any, default: float = 120.0) -> float:
    expanded = os.path.expandvars(str(timeout_value or "")).strip()
    try:
        return float(expanded)
    except (TypeError, ValueError):
        return default


def build_ultrathink_http_payload(task: str, task_type: str) -> Dict[str, Any]:
    optimize_for = TASK_TYPE_TO_OPTIMIZE_FOR.get(task_type, "reliability")
    reasoning_depth = OPTIMIZE_FOR_TO_REASONING_DEPTH[optimize_for]
    http_task_type = TASK_TYPE_TO_HTTP_TASK_TYPE.get(task_type, "analysis")
    return {
        "task_description": task,
        "task_type": http_task_type,
        "optimize_for": optimize_for,
        "reasoning_depth": reasoning_depth,
    }


def call_ultrathink_bridge(
    *,
    endpoint: str,
    timeout: float,
    task: str,
    task_type: str,
) -> Dict[str, Any]:
    """Synchronous HTTP bridge — kept for backward compatibility and direct callers."""
    url = normalize_ultrathink_endpoint(endpoint)
    payload = build_ultrathink_http_payload(task, task_type)
    response = httpx.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return {
        "endpoint": url,
        "request": payload,
        "response": response.json(),
    }


# ── MCP-Optional async wrapper ────────────────────────────────────────────────

def _mcp_server_cmd() -> Optional[List[str]]:
    """Return parsed server command from env, or None if unset."""
    raw = os.getenv("ULTRATHINK_MCP_SERVER_CMD", "").strip()
    return shlex.split(raw) if raw else None


async def call_ultrathink_mcp_or_bridge(
    *,
    endpoint: str,
    timeout: float,
    task: str,
    task_type: str,
) -> Dict[str, Any]:
    """Try MCP transport first; fall back to async HTTP on any failure.

    MCP is attempted only when ULTRATHINK_MCP_SERVER_CMD is set.
    Returns a dict with a 'transport' key: "mcp" or "http".
    The HTTP path uses httpx.AsyncClient to avoid blocking the FastAPI event loop.
    """
    from orchestrator.orama_mcp_client import UltrathinkMCPClient

    cmd = _mcp_server_cmd()
    if cmd:
        try:
            async with UltrathinkMCPClient(cmd, timeout=timeout) as client:
                async with asyncio.timeout(timeout):
                    result = await client.call_solve(task, task_type)
            return {"transport": "mcp", "result": result}
        except Exception as exc:
            log.warning("MCP transport failed (%s), falling back to HTTP", exc)

    # Async HTTP fallback — does not block the FastAPI event loop
    url = normalize_ultrathink_endpoint(endpoint)
    payload = build_ultrathink_http_payload(task, task_type)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    return {"transport": "http", "endpoint": url, "request": payload, "response": resp.json()}

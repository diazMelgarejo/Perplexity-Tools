from __future__ import annotations

import os
from typing import Any, Dict

import httpx


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
    url = normalize_ultrathink_endpoint(endpoint)
    payload = build_ultrathink_http_payload(task, task_type)
    response = httpx.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return {
        "endpoint": url,
        "request": payload,
        "response": response.json(),
    }

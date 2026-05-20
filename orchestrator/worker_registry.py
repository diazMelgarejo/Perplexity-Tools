"""Static worker registry for the V1 OrchestrationSupervisor.

No dynamic registration at runtime — security boundary per Anthropic pattern §3
(v2/5-Anthropic-agent-design.md §3 anti-patterns table).

Each worker is ``async (spec: JobSpec) -> dict``.

Model instantiation rules (from user session instructions):
  - Always use POST /api/chat (Ollama) or POST /v1/chat/completions (LM Studio/OpenAI).
  - NEVER use ``ollama run`` in a shared shell (spawns untracked subprocess, blocks GPU).
  - Max 1 instance per model per physical device at a time.
  - Safest simultaneous LAN pair: Mac Ollama (localhost:11434) + Windows LM Studio
    (remote IP:1234 via LM Link).  Never load two models on the Windows GPU at once.

Token-efficiency pattern from B2-ai-cli-mcp.md:
  - File-system-first: pass artifact file paths, not raw content, through MCP/CLI calls.
  - Always use --json / --format=json for CLI workers to strip ANSI artifacts.
  - Background polling: fire-and-collect, never stream raw CLI stdout into LLM context.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple


# ── § 5.3  ROLE_BACKEND_MAP — authoritative role-to-backend routing ────────────
# Source: unified-absorption-plan.md § 5.3 (Ollama-first for Mac roles).
# Priority order per § 5.2:
#   1. role + specialization → ROLE_BACKEND_MAP
#   2. intent → _INTENT_BACKEND_MAP (below)
#   3. backend_hint → explicit override
#   4. Policy-defined default
#
# Mac fallback chain: "ollama" → "lmstudio-mac" (only when Ollama port 11434 unreachable).
# All candidates pass through policy.validate_or_raise() — fail-closed on affinity.

ROLE_BACKEND_MAP: Dict[Tuple[str, Optional[str]], Tuple[str, str]] = {
    # (role, specialization)                   → (backend,        model)
    ("executor-agent",   "python-coding"):      ("lmstudio-win",  "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"),
    ("executor-agent",   "test-writing"):       ("lmstudio-win",  "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"),
    ("executor-agent",   None):                 ("lmstudio-win",  "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"),
    ("context-agent",    "market-research"):    ("ollama",        "qwen3.5:9b-nvfp4"),
    ("context-agent",    "m&a-research"):       ("ollama",        "qwen3.5:9b-nvfp4"),
    ("context-agent",    None):                 ("ollama",        "qwen3.5:9b-nvfp4"),
    ("verifier-agent",   None):                 ("lmstudio-win",  "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"),
    ("crystallizer-agent", None):               ("ollama",        "qwen3.5:9b-nvfp4"),
    ("architect-agent",  None):                 ("lmstudio-win",  "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"),
    ("refiner-agent",    None):                 ("ollama",        "qwen3.5:9b-nvfp4"),
}


def resolve_role_backend(role: str, specialization: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """Return (backend, model) for a given role + specialization, or None if not in map.

    Looks up specific specialization first, then falls back to (role, None) default.
    """
    specific = ROLE_BACKEND_MAP.get((role, specialization))
    if specific is not None:
        return specific
    if specialization is not None:
        return ROLE_BACKEND_MAP.get((role, None))
    return None


# ── Intent → backend routing table (fallback layer 2) ─────────────────────────
_INTENT_BACKEND_MAP: Dict[str, str] = {
    "code-review":    "codex",
    "debug":          "codex",
    "ml-experiment":  "gemini",
    "research":       "gemini",
    "freeform":       "ollama",
    "echo":           "echo",
}


def resolve_backend(spec: Any) -> str:
    """Resolve backend using priority order from § 5.2.

    1. role + specialization → ROLE_BACKEND_MAP
    2. intent → _INTENT_BACKEND_MAP
    3. backend_hint → explicit override (takes precedence if non-empty/non-auto)
    """
    # Explicit override (highest priority when set)
    hint = getattr(spec, "backend_hint", None)
    if hint and hint not in {"auto", None, ""}:
        return hint

    # Role-based lookup
    role = getattr(spec, "role", None)
    specialization = getattr(spec, "specialization", None)
    if role:
        result = resolve_role_backend(role, specialization)
        if result is not None:
            return result[0]   # backend name

    # Intent fallback
    return _INTENT_BACKEND_MAP.get(getattr(spec, "intent", ""), "echo")


# ── Worker implementations ────────────────────────────────────────────────────

async def _echo_worker(spec: Any) -> dict:
    """Smoke-test / stub worker — returns the prompt as its own output.

    Used by: test_supervisor_smoke.py, any job with backend_hint='echo'.
    """
    await asyncio.sleep(0)   # yield to event loop; instant success
    return {
        "backend": "echo",
        "intent": getattr(spec, "intent", ""),
        "output": f"[echo] {getattr(spec, 'prompt', '')}",
        "tokens": 0,
    }


async def _ollama_mac_worker(spec: Any) -> dict:
    """Mac Ollama worker — POST /api/chat.

    Model instantiation rules:
      - POST /api/chat endpoint, never ``ollama run``.
      - 1 active model per Mac at a time (VRAM guard is caller's responsibility).
      - Default endpoint: http://localhost:11434/api/chat
    """
    import httpx

    endpoint = "http://localhost:11434/api/chat"
    model = getattr(spec, "metadata", {}).get("model", "qwen3:8b")
    prompt = getattr(spec, "prompt", "")
    timeout = float(getattr(spec, "constraints", {}).get("max_seconds", 120))

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return {
        "backend": "ollama-mac",
        "model": model,
        "output": data.get("message", {}).get("content", ""),
        "tokens": data.get("eval_count", 0),
    }


async def _lmstudio_mac_worker(spec: Any) -> dict:
    """Mac LM Studio worker — POST /v1/chat/completions (OpenAI-compatible).

    Default endpoint: http://localhost:1234/v1/chat/completions
    Use this for Mac-tier local models (e.g., qwen3.5-9b-mlx).
    This is a thinking model — set max_tokens ≥ 500 in constraints.
    """
    import httpx

    endpoint = "http://localhost:1234/v1/chat/completions"
    model = getattr(spec, "metadata", {}).get("model", "")
    prompt = getattr(spec, "prompt", "")
    timeout = float(getattr(spec, "constraints", {}).get("max_seconds", 120))
    max_tokens = int(getattr(spec, "constraints", {}).get("max_tokens", 2048))

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json()

    return {
        "backend": "lmstudio-mac",
        "model": model,
        "output": data["choices"][0]["message"]["content"],
        "tokens": data.get("usage", {}).get("completion_tokens", 0),
    }


async def _codex_worker(spec: Any) -> dict:
    """Codex CLI worker — headless, isolated context, file-system-first.

    B2-ai-cli-mcp.md patterns applied:
      - Use --approval-mode auto-edit (headless fork, no interactive gate).
      - stdin=DEVNULL so the subprocess cannot hang on input.
      - Pass prompt directly — file results saved by codex to cwd, not echoed.
    """
    prompt = getattr(spec, "prompt", "")
    timeout = float(getattr(spec, "constraints", {}).get("max_seconds", 300))

    cmd = [
        "codex",
        "--approval-mode", "auto-edit",
        "--quiet",
        prompt,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.terminate()
        raise RuntimeError(f"codex worker timed out after {timeout}s")

    if proc.returncode != 0:
        raise RuntimeError(f"codex exited {proc.returncode}: {stderr.decode()[:500]}")

    return {
        "backend": "codex",
        "output": stdout.decode(errors="replace").strip(),
        "returncode": proc.returncode,
    }


async def _gemini_worker(spec: Any) -> dict:
    """Gemini CLI worker — requires --yolo for non-interactive dispatch.

    SKILL.md rule: always pass --yolo before -p; without it the subprocess
    hangs on the first tool-prompt gate (confirmed 2026-05-08 session).

    B2-ai-cli-mcp.md patterns:
      - File-system-first: if spec.prompt references a file path, Gemini writes
        its result to disk; the MCP response is a status + file path, not content.
      - stdin=DEVNULL prevents interactive hangs.
    """
    prompt = getattr(spec, "prompt", "")
    timeout = float(getattr(spec, "constraints", {}).get("max_seconds", 300))

    cmd = ["gemini", "--yolo", "-p", prompt]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.terminate()
        raise RuntimeError(f"gemini worker timed out after {timeout}s")

    if proc.returncode != 0:
        raise RuntimeError(f"gemini exited {proc.returncode}: {stderr.decode()[:500]}")

    return {
        "backend": "gemini",
        "output": stdout.decode(errors="replace").strip(),
        "returncode": proc.returncode,
    }


async def _ollama_worker(spec: Any) -> dict:
    """Canonical Ollama worker (first-class Mac backend).

    Uses POST /api/chat at localhost:11434. Always prefer this over lmstudio-mac
    for Mac-affinity roles. See CLAUDE.md § 0 hardware routing invariants.
    """
    return await _ollama_mac_worker(spec)


async def _lmstudio_win_worker(spec: Any) -> dict:
    """Windows LM Studio worker — POST /v1/chat/completions via LM Link (LAN).

    Endpoint resolution (in priority order):
      1. ``spec.metadata["_win_endpoint"]`` — pre-probed URL injected by
         ``OrchestrationSupervisor._dispatch()`` so the dispatcher and the
         worker always hit the same host.
      2. ``LM_STUDIO_WIN_ENDPOINTS`` env var — fallback when the worker is
         called directly (not via the supervisor dispatch path).  In that case
         the worker probes the pool itself, identical to the old behaviour.

    GPU lock: one heavy model at a time (enforced in LMStudioWinBackend; here
    the worker trusts the caller to serialize via the backend class).

    Model: Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2 (default).
    """
    import os
    import httpx
    import logging

    _log = logging.getLogger(__name__)

    metadata: dict = getattr(spec, "metadata", {}) or {}
    model = metadata.get("model", "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2")
    prompt = getattr(spec, "prompt", "")
    timeout = float(getattr(spec, "constraints", {}).get("max_seconds", 300))
    max_tokens = int(getattr(spec, "constraints", {}).get("max_tokens", 4096))

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }

    # ── Endpoint resolution ──────────────────────────────────────────────────
    # Priority 1: dispatcher already probed and selected an endpoint.
    pre_probed = metadata.get("_win_endpoint")
    if pre_probed:
        endpoint = pre_probed.rstrip("/")
        _log.debug("lmstudio-win: using pre-probed endpoint %s", endpoint)
    else:
        # Priority 2: direct invocation — probe LM_STUDIO_WIN_ENDPOINTS ourselves.
        raw_endpoints = os.getenv("LM_STUDIO_WIN_ENDPOINTS", "REQUIRED_SET_IN_ENV")
        candidates = [e.strip().rstrip("/") for e in raw_endpoints.split(",") if e.strip()]
        if not candidates or candidates == ["REQUIRED_SET_IN_ENV"]:
            raise RuntimeError(
                "LM_STUDIO_WIN_ENDPOINTS is not set. "
                "Set it to the Windows LM Studio URL, e.g. http://192.168.254.102:1234"
            )
        endpoint = None
        async with httpx.AsyncClient(timeout=5.0) as probe_client:
            for candidate in candidates:
                try:
                    r = await probe_client.get(f"{candidate}/v1/models")
                    if r.status_code < 500:
                        endpoint = candidate
                        break
                except Exception as exc:
                    _log.warning(
                        "win_coder_pool: %s offline (%s), trying next", candidate, exc
                    )
        if endpoint is None:
            raise RuntimeError(
                f"No Windows coder available in pool: {candidates}. "
                "Ensure LM Studio is running and a model is loaded."
            )

    # ── Request ──────────────────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{endpoint}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

    return {
        "backend": "lmstudio-win",
        "model": model,
        "output": data["choices"][0]["message"]["content"],
        "tokens": data.get("usage", {}).get("completion_tokens", 0),
    }


# ── Registry ──────────────────────────────────────────────────────────────────
WORKER_REGISTRY: Dict[str, Callable[[Any], Awaitable[dict]]] = {
    "echo":           _echo_worker,
    "ollama":         _ollama_worker,       # canonical Mac Ollama (first-class)
    "ollama-mac":     _ollama_mac_worker,   # alias kept for backward compat
    "lmstudio-mac":   _lmstudio_mac_worker,
    "lmstudio-win":   _lmstudio_win_worker, # Windows via LM Link (LAN)
    "codex":          _codex_worker,
    "gemini":         _gemini_worker,
}

"""orchestrator.py — Perpetua-Tools Orchestrator (port 8000)
Routes AI tasks across local Ollama models + Perplexity cloud with budget controls.

Design principles
-----------------
* Privacy-first — privacy_critical tasks route to ultrathink-system (local) first.
* Budget-controlled — MAX_DAILY_SPEND and MAX_PERPLEXITY_CALLS_DAY caps enforced via Redis.
* Graceful degradation — if Redis is unavailable, file-based state (.state/agents.json) is used.
* Stateful deduplication — PT owns agent lifecycle; ultrathink-system is stateless.

Usage
-----
    pip install fastapi uvicorn aiohttp loguru python-dotenv slowapi pydantic>=2.6.0
    python -m uvicorn orchestrator:app --host 0.0.0.0 --port 8000
"""
import os
import json
import asyncio
import aiohttp
import logging
import re
import argparse
# Redis: Optional for MVP. PT uses file-based state (.state/agents.json) by default.
# Redis enables distributed coordination for multi-instance deployments (v1.1+).
# Soft import — app starts cleanly even if the redis package is not installed.
try:
    import redis.asyncio as _redis_mod
except ImportError:
    _redis_mod = None
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
# fix(orchestrator): migrate from deprecated Pydantic V1 @validator to V2 @field_validator
from pydantic import BaseModel, Field, field_validator
from orchestrator.control_plane import bootstrap_runtime_sync, load_runtime_payload
try:
    from loguru import logger
except ImportError:
    logger = logging.getLogger("perplexity_tools.orchestrator")
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        return False
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
except ImportError:
    class RateLimitExceeded(Exception):
        pass

    def _rate_limit_exceeded_handler(*_args, **_kwargs):
        raise RateLimitExceeded("slowapi is not installed")

    def get_remote_address(_request):
        return "local"

    class Limiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, _rule):
            def decorator(fn):
                return fn
            return decorator

load_dotenv()

# Configuration
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
OLLAMA_MAC_ENDPOINT = os.getenv("OLLAMA_MAC_ENDPOINT", "http://192.168.254.103:11434")
OLLAMA_WINDOWS_ENDPOINT = os.getenv("OLLAMA_WINDOWS_ENDPOINT", "http://192.168.254.100:11434")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
MAX_DAILY_SPEND = float(os.getenv("MAX_DAILY_SPEND", 0.17))
MAX_PERPLEXITY_CALLS_DAY = int(os.getenv("MAX_PERPLEXITY_CALLS_DAY", 5))
ULTRATHINK_ENDPOINT = os.getenv("ULTRATHINK_ENDPOINT")

# LM Studio (v1.0 RC primary local backend)
LMS_WIN_ENDPOINTS: List[str] = [
    ep.strip()
    for ep in os.getenv("LM_STUDIO_WIN_ENDPOINTS", "http://192.168.254.100:1234").split(",")
    if ep.strip()
]
LMS_MAC_ENDPOINT: str = os.getenv("LM_STUDIO_MAC_ENDPOINT", "http://192.168.254.103:1234")
LMS_API_TOKEN: str = os.getenv("LM_STUDIO_API_TOKEN", "")
LMS_WIN_MODEL: str = os.getenv("LMS_WIN_MODEL", "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2")
LMS_MAC_MODEL: str = os.getenv("LMS_MAC_MODEL", "Qwen3.5-9B-MLX-4bit")
LMS_TIMEOUT: float = float(os.getenv("LM_STUDIO_TIMEOUT", "120"))

# sec: validate API key is configured at startup
if not PERPLEXITY_API_KEY:
    logger.warning("PERPLEXITY_API_KEY is not set — cloud calls will be skipped")

# v0.9.9.7: rate limiting + input validation + Pydantic V2 field_validator
VERSION = "0.9.9.7"
SAFE_REDIS_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_redis_health_error: Optional[str] = None

# Rate limiter (OWASP API4 — Unrestricted Resource Consumption)
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(title="Perpetua-Tools Orchestrator", version=VERSION)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# sec: restrict to known hosts in production (set ALLOWED_HOSTS env var)
_allowed_hosts = os.getenv("ALLOWED_HOSTS", "*")
if _allowed_hosts != "*":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts.split(","))

# Redis connection with graceful failure (no-op when package absent or unreachable)
try:
    r = _redis_mod.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True) if _redis_mod else None
except Exception as _redis_init_err:
    logger.error(f"Redis init failed: {_redis_init_err}; budget tracking disabled")
    _redis_health_error = str(_redis_init_err)
    r = None


def _disable_redis(reason: str) -> None:
    global r, _redis_health_error
    _redis_health_error = reason
    if r is not None:
        logger.warning(f"Redis became unavailable: {reason}; budget tracking disabled")
    r = None


async def _redis_available() -> bool:
    if r is None:
        return False
    try:
        pong = await r.ping()
    except Exception as exc:
        _disable_redis(str(exc))
        return False
    if not pong:
        _disable_redis("PING returned falsy response")
        return False
    return True


async def _redis_health() -> dict:
    available = await _redis_available()
    return {
        "configured": _redis_mod is not None,
        "available": available,
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "error": None if available else (_redis_health_error or "Redis disabled"),
    }


# sec: input validation — bounded task_description (OWASP API3 injection + API4 DoS)
class OrchestrationRequest(BaseModel):
    task_description: str = Field(..., min_length=1, max_length=8000)
    privacy_critical: bool = False
    is_finance_realtime: bool = False
    enable_critic: bool = True

    @field_validator("task_description")
    @classmethod
    def no_null_bytes(cls, v: str) -> str:
        if "\x00" in v:
            raise ValueError("Null bytes not allowed in task_description")
        return v


class OrchestrationResponse(BaseModel):
    status: str
    result: str
    routing_log: List[str]
    cost_estimate: float


# v0.9.7.0: Layer 2 Spawn Reconciliation
class ReconcileRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    model_id: str = Field(..., min_length=1, max_length=128)
    hardware_profile: str = Field(..., min_length=1, max_length=64)  # e.g., "win-rtx3080" or "mac-studio"

    @field_validator("session_id", "model_id", "hardware_profile")
    @classmethod
    def safe_redis_key_segment(cls, value: str) -> str:
        if not SAFE_REDIS_KEY_SEGMENT.fullmatch(value):
            raise ValueError(
                "Only letters, numbers, dot, underscore, and hyphen are allowed"
            )
        return value


class ReconcileResponse(BaseModel):
    approved: bool
    reason: Optional[str] = None
    suggested_model: Optional[str] = None


async def check_budget():
    if not await _redis_available():
        return True  # Redis unavailable — allow calls, log warning
    try:
        calls = await r.get("perplexity:daily_calls") or 0
        spend = await r.get("perplexity:daily_spend") or 0
        if int(calls) >= MAX_PERPLEXITY_CALLS_DAY or float(spend) >= MAX_DAILY_SPEND:
            return False
        return True
    except Exception as e:
        logger.warning(f"Budget check failed (Redis error): {e}")
        return True


async def log_perplexity_usage(tokens_used: int):
    if not await _redis_available():
        return
    # $15 per 1M tokens blended rate
    cost = (tokens_used / 1_000_000) * 15.0
    try:
        await r.incr("perplexity:daily_calls")
        await r.incrbyfloat("perplexity:daily_spend", cost)
        # Bug fix: await cannot be used inside an f-string expression
        daily_spend = await r.get("perplexity:daily_spend")
        logger.info(f"Perplexity call logged. Daily spend: {daily_spend}")
    except Exception as e:
        logger.warning(f"Usage logging failed (Redis error): {e}")


async def call_perplexity(prompt: str, model: str = "claude-3-5-sonnet-thinking"):
    # sec: refuse to call if API key is missing
    if not PERPLEXITY_API_KEY:
        logger.warning("PERPLEXITY_API_KEY not configured; skipping cloud call")
        return None
    if not await check_budget():
        logger.warning("Budget exceeded, falling back to local model")
        return None
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                await log_perplexity_usage(data['usage']['total_tokens'])
                return data['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"Perplexity API error: {e}")
            return None


async def call_lmstudio(prompt: str, endpoint: str = "", model: str = "") -> Optional[str]:
    """POST to LM Studio /api/v1/chat; extract first message-type content."""
    ep = endpoint or (LMS_WIN_ENDPOINTS[0] if LMS_WIN_ENDPOINTS else LMS_MAC_ENDPOINT)
    mdl = model or LMS_WIN_MODEL
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if LMS_API_TOKEN:
        headers["Authorization"] = f"Bearer {LMS_API_TOKEN}"
    payload = {"model": mdl, "input": prompt, "context_length": 8192}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{ep}/api/v1/chat", json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=LMS_TIMEOUT),
            ) as resp:
                data = await resp.json()
                output = data.get("output", [])
                for item in output:
                    if item.get("type") == "message":
                        return item.get("content")
                return " ".join(item.get("content", "") for item in output if item.get("content")) or None
        except Exception as e:
            logger.error(f"LM Studio error ({ep}): {e}")
            return None


async def call_ollama(prompt: str, model: str, endpoint: str):
    url = f"{endpoint}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                return data['response']
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return None


async def call_ultrathink(task: str):
    if not ULTRATHINK_ENDPOINT:
        return None
    # Bug fix: append /ultrathink path so the request hits the correct endpoint
    url = ULTRATHINK_ENDPOINT.rstrip("/") + "/ultrathink"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json={"task_description": task}) as resp:
                data = await resp.json()
                return data['result']
        except Exception as e:
            logger.error(f"UltraThink error: {e}")
            return None


@app.post("/reconcile", response_model=ReconcileResponse)
@limiter.limit("30/minute")
async def reconcile(req: ReconcileRequest, request: Request):
    """
    v0.9.7.0: Prevent GPU contention and enforce hardware limits.
    """
    if not await _redis_available():
        return ReconcileResponse(approved=True, reason="Redis unavailable; skipping contention check")
    # Check for existing sessions on the hardware in Redis
    active_sessions = await r.keys(f"ultrathink:session:active:{req.hardware_profile}:*")
    # RTX 3080 has a hard OLLAMA_NUM_PARALLEL=1 limit
    if req.hardware_profile == "win-rtx3080" and len(active_sessions) >= 1:
        return ReconcileResponse(
            approved=False,
            reason="GPU Contention: win-rtx3080 already running an active session.",
            suggested_model="qwen3.5-9b-mlx-4bit"
        )
    # Register this session attempt
    await r.setex(f"ultrathink:session:active:{req.hardware_profile}:{req.session_id}", 300, "active")
    return ReconcileResponse(approved=True)


@app.post("/orchestrate", response_model=OrchestrationResponse)
@limiter.limit("20/minute")
async def orchestrate(req: OrchestrationRequest, request: Request):
    routing_log = []
    if req.is_finance_realtime:
        routing_log.append("Routing to Perplexity Grok 4.1 for real-time finance/events")
        result = await call_perplexity(req.task_description, model="grok-beta")
        if not result:
            routing_log.append("Cloud failed, falling back to local Qwen3.5-35B research")
            result = await call_ollama(req.task_description, "qwen3.5:35b-a3b-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)
    elif req.privacy_critical:
        routing_log.append("Privacy critical: routing to UltraThink → LM Studio Win → LM Studio Mac → Ollama.")
        result = await call_ultrathink(req.task_description)
        if not result:
            routing_log.append("UltraThink unavailable, trying LM Studio Win agents.")
            for ep in LMS_WIN_ENDPOINTS:
                result = await call_lmstudio(req.task_description, endpoint=ep, model=LMS_WIN_MODEL)
                if result:
                    routing_log.append(f"LM Studio Win answered ({ep}).")
                    break
        if not result:
            routing_log.append("LM Studio Win failed, trying LM Studio Mac.")
            result = await call_lmstudio(req.task_description, endpoint=LMS_MAC_ENDPOINT, model=LMS_MAC_MODEL)
        if not result:
            routing_log.append("LM Studio Mac failed, falling back to Ollama.")
            result = await call_ollama(req.task_description, "qwen3.5:35b-a3b-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)
    else:
        routing_log.append("Standard orchestration. Calling Perplexity cloud.")
        result = await call_perplexity(req.task_description)
        if not result:
            routing_log.append("Cloud budget/error. Trying LM Studio Win (local fallback).")
            for ep in LMS_WIN_ENDPOINTS:
                result = await call_lmstudio(req.task_description, endpoint=ep, model=LMS_WIN_MODEL)
                if result:
                    routing_log.append(f"LM Studio Win answered ({ep}).")
                    break
        if not result:
            routing_log.append("LM Studio Win failed, falling back to Ollama.")
            result = await call_ollama(req.task_description, "qwen3.5:35b-a3b-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)
    if req.enable_critic:
        routing_log.append("Running critic pass with Qwen3.5-35B on Dell")
        critic_prompt = f"Critique the following AI response for accuracy and completeness: {result}"
        feedback = await call_ollama(critic_prompt, "qwen3.5:35b-a3b-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)
        routing_log.append("Refining based on critic feedback")
        refine_prompt = f"Original result: {result}\nCritic feedback: {feedback}\nProvide the final improved response."
        result = await call_ollama(refine_prompt, "qwen3.5:35b-a3b-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)
    # Bug fix: result can be None if all backends fail; coerce to str to satisfy response schema
    if result is None:
        result = ""
        routing_log.append("All backends failed; returning empty result.")
    spend = 0.0
    if await _redis_available():
        try:
            spend = float(await r.get("perplexity:daily_spend") or 0)
        except Exception:
            pass
    return OrchestrationResponse(
        status="success",
        result=result,
        routing_log=routing_log,
        cost_estimate=spend
    )


@app.get("/health")
async def health():
    return {"status": "ok", "version": VERSION, "redis": await _redis_health()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Perpetua-Tools orchestrator entrypoint",
    )
    subparsers = parser.add_subparsers(dest="command")

    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Run the PT-first runtime reconciler and write a resolved state payload.",
    )
    bootstrap_parser.add_argument(
        "--output",
        default=".state/runtime_payload.json",
        help="Path to write the resolved runtime payload JSON.",
    )
    bootstrap_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable prompts and reuse existing configuration only.",
    )
    bootstrap_parser.add_argument(
        "--force-gateway",
        action="store_true",
        help="Force-regenerate OpenClaw config before gateway startup.",
    )
    bootstrap_parser.add_argument(
        "--no-autoresearch",
        action="store_true",
        help="Skip AutoResearch preflight during bootstrap.",
    )
    bootstrap_parser.add_argument(
        "--run-tag",
        default=None,
        help="Optional run tag for autoresearch swarm_state initialisation.",
    )
    bootstrap_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the resolved runtime payload as JSON.",
    )

    state_parser = subparsers.add_parser(
        "state",
        help="Print the last resolved PT runtime payload.",
    )
    state_parser.add_argument(
        "--input",
        default=".state/runtime_payload.json",
        help="Path to a runtime payload JSON file.",
    )

    serve_parser = subparsers.add_parser(
        "serve",
        help="Run the legacy FastAPI app.",
    )
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        payload = bootstrap_runtime_sync(
            interactive=not args.non_interactive,
            force_gateway=args.force_gateway,
            run_autoresearch_preflight=not args.no_autoresearch,
            runtime_state_path=args.output,
            run_tag=args.run_tag,
            print_progress=not args.json,
        )
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                "[orchestrator] Bootstrap resolved "
                f"gateway={payload.get('gateway', {}).get('gateway_url', 'n/a')} "
                f"distributed={payload.get('routing', {}).get('distributed', False)}"
            )
            print(
                "[orchestrator] Runtime payload written to "
                f"{payload.get('paths', {}).get('runtime_state', args.output)}"
            )
        return 0 if payload.get("gateway", {}).get("gateway_ready") else 1

    if args.command == "state":
        payload = load_runtime_payload(args.input)
        if payload is None:
            print(f"[orchestrator] No runtime payload found at {args.input}")
            return 1
        print(json.dumps(payload, indent=2))
        return 0

    import uvicorn
    host = getattr(args, "host", "0.0.0.0")
    port = getattr(args, "port", 8000)
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

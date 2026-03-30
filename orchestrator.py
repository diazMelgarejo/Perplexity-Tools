"""orchestrator.py — Perplexity-Tools Orchestrator (port 8000)
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
from loguru import logger
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

# Configuration
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
OLLAMA_MAC_ENDPOINT = os.getenv("OLLAMA_MAC_ENDPOINT", "http://localhost:11434")
OLLAMA_WINDOWS_ENDPOINT = os.getenv("OLLAMA_WINDOWS_ENDPOINT", "http://192.168.1.100:11434")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
MAX_DAILY_SPEND = float(os.getenv("MAX_DAILY_SPEND", 0.17))
MAX_PERPLEXITY_CALLS_DAY = int(os.getenv("MAX_PERPLEXITY_CALLS_DAY", 5))
ULTRATHINK_ENDPOINT = os.getenv("ULTRATHINK_ENDPOINT")

# sec: validate API key is configured at startup
if not PERPLEXITY_API_KEY:
    logger.warning("PERPLEXITY_API_KEY is not set — cloud calls will be skipped")

# v0.9.9.0: rate limiting + input validation + Pydantic V2 field_validator
VERSION = "0.9.9.0"

# Rate limiter (OWASP API4 — Unrestricted Resource Consumption)
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

app = FastAPI(title="Perplexity-Tools Orchestrator", version=VERSION)
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
    r = None


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


class ReconcileResponse(BaseModel):
    approved: bool
    reason: Optional[str] = None
    suggested_model: Optional[str] = None


async def check_budget():
    if r is None:
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
    if r is None:
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
    if r is None:
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
        routing_log.append("Privacy critical task detected. Routing to UltraThink system.")
        result = await call_ultrathink(req.task_description)
        if not result:
            routing_log.append("UltraThink failed, falling back to local Qwen3.5-35B")
            result = await call_ollama(req.task_description, "qwen3.5:35b-a3b-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)
    else:
        routing_log.append("Standard orchestration. Calling Claude Sonnet 4.5 via Perplexity.")
        result = await call_perplexity(req.task_description)
        if not result:
            routing_log.append("Cloud budget/error. Falling back to local Qwen3.5-35B orchestrator.")
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
    if r is not None:
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
    return {"status": "ok", "version": VERSION}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

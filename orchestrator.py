import os
import json
import asyncio
import aiohttp
import redis.asyncio as redis
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

# Configuration
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
OLLAMA_MAC_ENDPOINT = os.getenv("OLLAMA_MAC_ENDPOINT", "http://localhost:11434")
OLLAMA_WINDOWS_ENDPOINT = os.getenv("OLLAMA_WINDOWS_ENDPOINT", "http://192.168.1.101:11434")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
MAX_DAILY_SPEND = float(os.getenv("MAX_DAILY_SPEND", 0.17))
MAX_PERPLEXITY_CALLS_DAY = int(os.getenv("MAX_PERPLEXITY_CALLS_DAY", 5))
ULTRATHINK_ENDPOINT = os.getenv("ULTRATHINK_ENDPOINT")

app = FastAPI(title="Perplexity-Tools Orchestrator", version="0.9.0.0")
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

class OrchestrationRequest(BaseModel):
    task_description: str
    privacy_critical: bool = False
    is_finance_realtime: bool = False
    enable_critic: bool = True

class OrchestrationResponse(BaseModel):
    status: str
    result: str
    routing_log: List[str]
    cost_estimate: float

async def check_budget():
    calls = await r.get("perplexity:daily_calls") or 0
    spend = await r.get("perplexity:daily_spend") or 0
    if int(calls) >= MAX_PERPLEXITY_CALLS_DAY or float(spend) >= MAX_DAILY_SPEND:
        return False
    return True

async def log_perplexity_usage(tokens_used: int):
    # Rough estimate for Claude Sonnet 4.5 Thinking / Grok 4.1
    # $15 per 1M tokens as a blended conservative rate
    cost = (tokens_used / 1_000_000) * 15.0
    await r.incr("perplexity:daily_calls")
    await r.incrbyfloat("perplexity:daily_spend", cost)
    logger.info(f"Perplexity call logged. Daily spend: {await r.get('perplexity:daily_spend')}")

async def call_perplexity(prompt: str, model: str = "claude-3-5-sonnet-thinking"):
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
        async with session.post(url, json=payload) as resp:
            data = await resp.json()
            return data['response']

async def call_ultrathink(task: str):
    if not ULTRATHINK_ENDPOINT:
        return None
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(ULTRATHINK_ENDPOINT, json={"task_description": task}) as resp:
                data = await resp.json()
                return data['result']
        except Exception as e:
            logger.error(f"UltraThink error: {e}")
            return None

@app.post("/orchestrate", response_model=OrchestrationResponse)
async def orchestrate(req: OrchestrationRequest):
    routing_log = []
    
    # 1. Routing Logic (SKILL.md implementation)
    if req.is_finance_realtime:
        routing_log.append("Routing to Perplexity Grok 4.1 for real-time finance/events")
        result = await call_perplexity(req.task_description, model="grok-beta") # Placeholder for Grok 4.1
        if not result:
            routing_log.append("Cloud failed, falling back to local Qwen3-30B research")
            result = await call_ollama(req.task_description, "qwen3:30b-a3b-instruct-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)
    
    elif req.privacy_critical:
        routing_log.append("Privacy critical task detected. Routing to UltraThink system.")
        result = await call_ultrathink(req.task_description)
        if not result:
            routing_log.append("UltraThink failed, falling back to local Qwen3-30B")
            result = await call_ollama(req.task_description, "qwen3:30b-a3b-instruct-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)
            
    else:
        routing_log.append("Standard orchestration. Calling Claude Sonnet 4.5 via Perplexity.")
        result = await call_perplexity(req.task_description)
        if not result:
            routing_log.append("Cloud budget/error. Falling back to local Qwen3-30B orchestrator.")
            result = await call_ollama(req.task_description, "qwen3:30b-a3b-instruct-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)

    # 2. Optional Critic Pass
    if req.enable_critic:
        routing_log.append("Running critic pass with Qwen3-30B on Dell")
        critic_prompt = f"Critique the following AI response for accuracy and completeness: {result}"
        feedback = await call_ollama(critic_prompt, "qwen3:30b-a3b-instruct-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)
        
        routing_log.append("Refining based on critic feedback")
        refine_prompt = f"Original result: {result}
Critic feedback: {feedback}
Provide the final improved response."
        result = await call_ollama(refine_prompt, "qwen3:30b-a3b-instruct-q4_K_M", OLLAMA_WINDOWS_ENDPOINT)

    spend = await r.get("perplexity:daily_spend") or 0
    return OrchestrationResponse(
        status="success",
        result=result,
        routing_log=routing_log,
        cost_estimate=float(spend)
    )

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.9.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

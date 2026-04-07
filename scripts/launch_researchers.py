#!/usr/bin/env python3
"""
launch_researchers.py
---------------------
Tandem autoresearcher launcher.

Spawns two concurrent research agents — one on Mac (Ollama) and one on
Windows (LM Studio or Ollama) — using whatever backends are live at
startup.  Each agent sends a configurable research task in a loop and
writes structured activity to .state/researcher_activity.jsonl, which
the portal at :8002 reads and displays.

Usage:
    python scripts/launch_researchers.py
    python scripts/launch_researchers.py --task "summarise recent LLM papers"
    python scripts/launch_researchers.py --once   # single pass, then exit
    python scripts/launch_researchers.py --interval 60  # seconds between rounds

Environment:
    STATE_DIR                  where to write activity log (default: .state)
    RESEARCHER_POLL_INTERVAL   seconds between rounds (default: 30)
    LM_STUDIO_API_TOKEN        passed through for secured LM Studio instances
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Allow running from repo root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from orchestrator.agent_tracker import AgentTracker  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("researchers")

# ── config ────────────────────────────────────────────────────────────────────

STATE_DIR = Path(os.getenv("STATE_DIR", ".state"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
ACTIVITY_LOG = STATE_DIR / "researcher_activity.jsonl"

POLL_INTERVAL = int(os.getenv("RESEARCHER_POLL_INTERVAL", "30"))
MAX_EVENTS    = 200
REQUEST_TIMEOUT = 90.0

DEFAULT_TASK = (
    "You are an autoresearcher agent. Briefly state your current hardware context, "
    "the model you are running on, and one concrete observation about LLM inference "
    "efficiency you find interesting right now. Keep it to 2-3 sentences."
)

tracker = AgentTracker(state_dir=str(STATE_DIR))


# ── activity log ──────────────────────────────────────────────────────────────

def _append_event(
    agent_id: str,
    role: str,
    model: str,
    backend: str,
    event: str,
    msg: str,
) -> None:
    entry = {
        "ts":       time.time(),
        "agent_id": agent_id,
        "agent":    role,
        "model":    model,
        "backend":  backend,
        "event":    event,
        "msg":      msg[:600],
    }
    lines: list[str] = []
    if ACTIVITY_LOG.exists():
        lines = [ln for ln in ACTIVITY_LOG.read_text().splitlines() if ln.strip()]
    lines.append(json.dumps(entry))
    if len(lines) > MAX_EVENTS:
        lines = lines[-MAX_EVENTS:]
    ACTIVITY_LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── model calls ───────────────────────────────────────────────────────────────

async def _ollama_chat(endpoint: str, model: str, prompt: str) -> str:
    url = f"{endpoint.rstrip('/')}/api/generate"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(url, json={"model": model, "prompt": prompt, "stream": False})
        r.raise_for_status()
        return r.json().get("response", "").strip()


async def _lmstudio_chat(endpoint: str, model: str, prompt: str) -> str:
    url = f"{endpoint.rstrip('/')}/v1/chat/completions"
    token = os.getenv("LM_STUDIO_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    payload = {
        "model":      model,
        "messages":   [{"role": "user", "content": prompt}],
        "max_tokens": 256,
        "stream":     False,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


# ── model discovery ───────────────────────────────────────────────────────────

async def _resolve_ollama_model(endpoint: str, preferred: str) -> str | None:
    """Return preferred model if present in Ollama, else first available, else None."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{endpoint.rstrip('/')}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
    except Exception as exc:
        log.warning("Ollama tag list failed (%s): %s", endpoint, exc)
        return None
    if not models:
        log.warning("Ollama at %s has no models pulled", endpoint)
        return None
    if preferred in models:
        return preferred
    log.warning("Model %r not in Ollama — using %r instead", preferred, models[0])
    return models[0]


async def _resolve_lmstudio_model(endpoint: str, preferred: str) -> str | None:
    """Return preferred model if LM Studio reports it, else first loaded model, else None."""
    token = os.getenv("LM_STUDIO_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{endpoint.rstrip('/')}/v1/models", headers=headers)
            r.raise_for_status()
            models = [m["id"] for m in r.json().get("data", [])]
    except Exception as exc:
        log.warning("LM Studio model list failed (%s): %s", endpoint, exc)
        return None
    if not models:
        log.warning("LM Studio at %s has no models loaded", endpoint)
        return None
    if preferred in models:
        return preferred
    log.warning("Model %r not in LM Studio — using %r instead", preferred, models[0])
    return models[0]


# ── researcher coroutine ──────────────────────────────────────────────────────

async def run_researcher(
    role: str,
    endpoint: str,
    model: str,
    backend: str,
    task: str,
    loop_once: bool,
    interval: int,
) -> None:
    """Register and run a single researcher agent loop."""
    use_lmstudio = "lmstudio" in backend or ":1234" in endpoint

    # Discover the actually-loaded model before committing to it
    if use_lmstudio:
        resolved = await _resolve_lmstudio_model(endpoint, model)
    else:
        resolved = await _resolve_ollama_model(endpoint, model)

    if resolved is None:
        log.error("[%s] no model available at %s — skipping", role, endpoint)
        return
    if resolved != model:
        log.info("[%s] model remapped %r → %r", role, model, resolved)
        model = resolved

    agent = tracker.register(
        role=role,
        model=model,
        backend=backend,
        host=endpoint,
        port=0,
        metadata={"endpoint": endpoint},
        status="running",
    )
    log.info("[%s] started  agent_id=%s  model=%s  backend=%s", role, agent.agent_id, model, backend)
    _append_event(agent.agent_id, role, model, backend, "started",
                  f"endpoint={endpoint} model={model}")

    iteration = 0

    try:
        while True:
            iteration += 1
            _append_event(agent.agent_id, role, model, backend, "query_sent",
                          f"Iteration #{iteration}")
            tracker.update_status(agent.agent_id, "running")
            try:
                if use_lmstudio:
                    reply = await _lmstudio_chat(endpoint, model, task)
                else:
                    reply = await _ollama_chat(endpoint, model, task)

                tracker.update_status(agent.agent_id, "idle")
                _append_event(agent.agent_id, role, model, backend, "reply", reply)
                log.info("[%s] reply: %s", role, reply[:140])
            except Exception as exc:
                tracker.update_status(agent.agent_id, "error")
                _append_event(agent.agent_id, role, model, backend, "error", str(exc))
                log.warning("[%s] error: %s", role, exc)

            if loop_once:
                break
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass
    finally:
        tracker.update_status(agent.agent_id, "stopped")
        _append_event(agent.agent_id, role, model, backend, "stopped", "Researcher stopped")
        log.info("[%s] stopped", role)


# ── entry ─────────────────────────────────────────────────────────────────────

async def main(task: str, loop_once: bool, interval: int) -> None:
    # Detect live backends via agent_launcher
    from agent_launcher import initialize_environment

    log.info("Probing backends via agent_launcher.initialize_environment() …")
    routing = await initialize_environment()
    log.info(
        "Routing resolved — mac=%s/%s  coder=%s/%s  distributed=%s",
        routing["manager_endpoint"], routing["manager_model"],
        routing["coder_endpoint"],   routing["coder_model"],
        routing["distributed"],
    )

    jobs: list[asyncio.Task] = []

    if routing.get("mac_reachable", True):
        jobs.append(asyncio.create_task(run_researcher(
            role="mac-researcher",
            endpoint=routing["manager_endpoint"],
            model=routing["manager_model"],
            backend=routing.get("manager_backend", "mac-ollama"),
            task=task,
            loop_once=loop_once,
            interval=interval,
        )))
    else:
        log.warning("Mac Ollama not reachable at %s — skipping mac-researcher",
                    routing["manager_endpoint"])

    win_backend = routing.get("coder_backend", "")
    if routing["distributed"] and win_backend != "mac-degraded":
        jobs.append(asyncio.create_task(run_researcher(
            role="win-researcher",
            endpoint=routing["coder_endpoint"],
            model=routing["coder_model"],
            backend=win_backend,
            task=task,
            loop_once=loop_once,
            interval=interval,
        )))
    else:
        log.warning("Windows backend not reachable — running mac-researcher only (degraded mode)")

    if not jobs:
        log.error("No backends reachable (Mac Ollama down, no Windows LMS). "
                  "Start Ollama ('ollama serve') or configure WINDOWS_IP / LM Studio.")
        return

    try:
        await asyncio.gather(*jobs)
    except (KeyboardInterrupt, asyncio.CancelledError):
        for j in jobs:
            j.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tandem autoresearcher launcher")
    parser.add_argument("--task",     default=DEFAULT_TASK, help="Research task prompt")
    parser.add_argument("--once",     action="store_true",  help="Single pass then exit")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL,
                        help="Seconds between iterations (default: %(default)s)")
    args = parser.parse_args()

    try:
        asyncio.run(main(task=args.task, loop_once=args.once, interval=args.interval))
    except KeyboardInterrupt:
        pass

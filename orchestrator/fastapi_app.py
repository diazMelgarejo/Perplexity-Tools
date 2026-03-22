from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orchestrator.agent_tracker import AgentTracker
from orchestrator.connectivity import backend_health_map
from orchestrator.cost_guard import CostGuard
from orchestrator.model_registry import ModelRegistry


# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Perplexity-Tools Orchestrator",
    version="0.9.0.0",
    description=(
        "Top-level idempotent multi-agent orchestrator. "
        "Repo #1 — complements ultrathink-system (Repo #2) "
        "with per-device model selection and fallback logic."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tracker = AgentTracker()
registry = ModelRegistry()
cost_guard = CostGuard()


# ── request / response models ─────────────────────────────────────────────────

class OrchestrateRequest(BaseModel):
    task: str
    task_type: str = "default"
    preferred_device: Optional[str] = None
    estimated_cost: float = 0.0
    parent_agent_id: Optional[str] = None
    force: bool = False  # if True, skip idempotency check (user confirmed)


class ConflictResponse(BaseModel):
    conflict: bool
    message: str
    existing_agents: List[Dict[str, Any]]


# ── health ─────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
def health(
    ollama_host: str = Query("http://127.0.0.1:11434"),
    lm_studio_host: str = Query("http://127.0.0.1:1234"),
    mlx_host: str = Query("http://127.0.0.1:8081"),
) -> Dict[str, Any]:
    """Backend connectivity health check — supports Mac+Win+shared Ollama."""
    return {
        "status": "ok",
        "version": "0.9.0.0",
        "backends": backend_health_map(
            ollama_host=ollama_host,
            lm_studio_host=lm_studio_host,
            mlx_host=mlx_host,
        ),
    }


# ── budget ────────────────────────────────────────────────────────────────────

@app.get("/budget", tags=["cost"])
def budget() -> Dict[str, Any]:
    return cost_guard.snapshot()


# ── agents ────────────────────────────────────────────────────────────────────

@app.get("/agents", tags=["agents"])
def list_agents(status: Optional[str] = None) -> Dict[str, Any]:
    agents = tracker.list_agents(status=status)
    return {"agents": [asdict(a) for a in agents]}


@app.get("/agents/conflicts", tags=["agents"])
def detect_conflicts() -> ConflictResponse:
    conflicts = tracker.detect_conflicts()
    if conflicts:
        return ConflictResponse(
            conflict=True,
            message=(
                f"{len(conflicts)} duplicate-role agent(s) detected. "
                "Resolve or pass force=true on /orchestrate to override."
            ),
            existing_agents=[asdict(a) for a in conflicts],
        )
    return ConflictResponse(conflict=False, message="No conflicts", existing_agents=[])


@app.delete("/agents/{agent_id}", tags=["agents"])
def destroy_agent(agent_id: str) -> Dict[str, Any]:
    ok = tracker.destroy(agent_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"destroyed": agent_id}


@app.delete("/agents/gc/stopped", tags=["agents"])
def gc_stopped() -> Dict[str, Any]:
    removed = tracker.destroy_stopped()
    return {"removed": removed}


# ── models ────────────────────────────────────────────────────────────────────

@app.get("/models", tags=["models"])
def list_models() -> Dict[str, Any]:
    return {"models": [m.__dict__ for m in registry.list_models()]}


@app.get("/models/route", tags=["models"])
def route(
    task_type: str = Query("default"),
    preferred_device: Optional[str] = Query(None),
) -> Dict[str, Any]:
    chain = registry.route_task(task_type, preferred_device=preferred_device)
    return {"fallback_chain": [m.__dict__ for m in chain]}


# ── orchestrate ───────────────────────────────────────────────────────────────

@app.post("/orchestrate", tags=["orchestrate"])
def orchestrate(req: OrchestrateRequest) -> Dict[str, Any]:
    """
    Idempotent orchestration entrypoint.

    1. Compute task_hash from task_type + task content.
    2. Check for existing running agent with same role/hash.
       → If found and force=False: return conflict prompt for user.
       → If found and force=True: proceed (user confirmed).
    3. Check budget.
    4. Select model via ModelRegistry.route_task().
    5. Register agent, record spend, return agent + fallback chain.
    """
    task_hash = sha256(f"{req.task_type}:{req.task}".encode()).hexdigest()

    # ── idempotency check ────────────────────────────────────────────────────
    existing = tracker.find_existing(role=req.task_type, task_hash=task_hash)
    if existing and not req.force:
        return {
            "status": "conflict",
            "message": (
                "A running agent already exists for this role and task. "
                "Pass force=true to override, or use the existing agent below."
            ),
            "existing_agent": asdict(existing),
        }

    # ── budget check ─────────────────────────────────────────────────────────
    snap = cost_guard.snapshot()
    if not cost_guard.can_spend(req.estimated_cost):
        raise HTTPException(
            status_code=402,
            detail=(
                f"Daily budget exceeded. Remaining: ${snap.get('remaining', 0):.4f}"
            ),
        )

    if cost_guard.alert_approaching():
        snap2 = cost_guard.snapshot()
        budget_warning = (
            f"⚠️ Budget at {snap2['daily_spend']:.2f} / {snap2['daily_budget']:.2f} (≥80%)"
        )
    else:
        budget_warning = None

    # ── model selection (SKILL.md → ModelRegistry → fallback chain) ──────────
    candidates = registry.route_task(
        req.task_type, preferred_device=req.preferred_device
    )
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"No model candidates found for task_type='{req.task_type}'",
        )

    selected = candidates[0]

    # ── register and activate agent ──────────────────────────────────────────
    agent = tracker.register(
        role=req.task_type,
        model=selected.name,
        backend=selected.backend,
        host=selected.host,
        port=selected.port,
        task_hash=task_hash,
        parent_agent_id=req.parent_agent_id,
        metadata={
            "reasoning": selected.reasoning,
            "device": selected.device,
            "online": selected.online,
        },
    )
    tracker.update_status(agent.agent_id, "running")
    cost_guard.record_spend(req.estimated_cost)

    response: Dict[str, Any] = {
        "status": "created",
        "agent": asdict(tracker.update_status(agent.agent_id, "idle")),
        "selected_model": {
            "name": selected.name,
            "backend": selected.backend,
            "device": selected.device,
            "host": f"{selected.host}:{selected.port}",
            "online": selected.online,
            "reasoning": selected.reasoning,
        },
        "fallback_chain": [
            {
                "priority": i + 2,
                "name": m.name,
                "backend": m.backend,
                "device": m.device,
                "online": m.online,
            }
            for i, m in enumerate(candidates[1:5])
        ],
    }
    if budget_warning:
        response["budget_warning"] = budget_warning
    return response


# ── entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("orchestrator.fastapi_app:app", host="0.0.0.0", port=8000, reload=True)

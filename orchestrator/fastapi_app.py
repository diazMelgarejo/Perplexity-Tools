from __future__ import annotations

import logging
from contextlib import asynccontextmanager
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
from orchestrator import autoresearch_bridge
from orchestrator.ecc_tools_sync import get_sync_status, sync_ecc_tools

_startup_log = logging.getLogger("orchestrator.fastapi_app")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        ecc_result = sync_ecc_tools(force=False)
        _startup_log.info(
            "ECC Tools sync: %s — %s",
            ecc_result.get("status"),
            ecc_result.get("message", ""),
        )
    except Exception as exc:
        _startup_log.warning("ECC Tools sync failed (non-fatal): %s", exc)
    yield


# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Perplexity-Tools Orchestrator",
    version="0.9.6.0",
    description=(
        "Top-level idempotent multi-agent orchestrator. "
        "Repo #1 — complements ultrathink-system (Repo #2) "
        "with per-device model selection and fallback logic."
    ),
    lifespan=_lifespan,
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

@app.get("/ecc/status", tags=["ecc"])
def ecc_status() -> Dict[str, Any]:
    """Return the last ECC Tools sync status without running a new sync."""
    return get_sync_status()


@app.post("/ecc/sync", tags=["ecc"])
def ecc_sync(force: bool = Query(False)) -> Dict[str, Any]:
    """
    Trigger an idempotent ECC Tools sync. Pass force=true to copy all managed files.
    """
    try:
        return sync_ecc_tools(force=force)
    except Exception as exc:
        _startup_log.exception("ECC sync endpoint error")
        return {"status": "error", "message": str(exc)}


@app.get("/health", tags=["system"])
def health(
    ollama_host: str = Query("http://127.0.0.1:11434"),
    lm_studio_host: str = Query("http://127.0.0.1:1234"),
    mlx_host: str = Query("http://127.0.0.1:8081"),
) -> Dict[str, Any]:
    """Backend connectivity health check — supports Mac+Win+shared Ollama."""
    return {
        "status": "ok",
        "version": "0.9.6.0",
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
    running = tracker.update_status(agent.agent_id, "running")
    if running is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Agent record missing after registration (e.g., concurrent deletion). "
                "Retry orchestration or inspect GET /agents."
            ),
        )

    idle = tracker.update_status(agent.agent_id, "idle")
    if idle is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Agent record disappeared before idle transition (e.g., concurrent DELETE). "
                "Retry orchestration or inspect GET /agents."
            ),
        )

    # Charge only after both transitions succeeded (avoids recording spend if deleted mid-flight).
    cost_guard.record_spend(req.estimated_cost)

    response: Dict[str, Any] = {
        "status": "created",
        "agent": asdict(idle),
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


# ── autoresearch (karpathy/autoresearch foot-soldier swarm) ──────────────

@app.post("/autoresearch/sync", tags=["autoresearch"])
def autoresearch_sync(run_tag: Optional[str] = Query(None)) -> Dict[str, Any]:
    """
    Idempotent sync of karpathy/autoresearch on the Windows GPU runner.
    Calls autoresearch_bridge.preflight() — bootstraps + syncs the repo,
    and optionally initialises swarm_state.md if run_tag is supplied.
    """
    result = autoresearch_bridge.preflight(run_tag=run_tag)
    if not result["sync_ok"]:
        raise HTTPException(
            status_code=500,
            detail=f"Autoresearch sync failed: {result['error']}",
        )
    return result


@app.get("/autoresearch/gpu_status", tags=["autoresearch"])
def autoresearch_gpu_status() -> Dict[str, Any]:
    """
    Query the GPU lock status from swarm_state.md.
    Returns {"gpu_idle": bool, "swarm_state": SwarmState} for orchestrator.
    """
    state = autoresearch_bridge.read_swarm_state()
    return {
        "gpu_idle": state.gpu_status.upper() == "IDLE",
        "swarm_state": {
            "gpu_status": state.gpu_status,
            "baseline_val_bpb": state.baseline_val_bpb,
            "baseline_sha": state.baseline_sha,
            "orchestrator_directive": state.orchestrator_directive,
            "evaluator_findings": state.evaluator_findings,
        },
    }


# ── entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("orchestrator.fastapi_app:app", host="0.0.0.0", port=8000, reload=True)

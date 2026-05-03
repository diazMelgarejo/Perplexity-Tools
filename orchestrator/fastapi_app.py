from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orchestrator import autoresearch_bridge
from orchestrator.agent_tracker import AgentTracker
from orchestrator.connectivity import backend_health_map
from orchestrator.control_plane import (
    bootstrap_runtime,
    load_runtime_payload,
    resolve_routing_state,
)
from orchestrator.cost_guard import CostGuard
from orchestrator.ecc_tools_sync import get_sync_status, sync_ecc_tools
from orchestrator.model_registry import ModelRegistry
from orchestrator.orama_bridge import (
    call_ultrathink_mcp_or_bridge,
    parse_ultrathink_timeout,
)

_startup_log = logging.getLogger("orchestrator.fastapi_app")
_GLM_ORCHESTRATOR_MODEL = "glm-5.1:cloud"
_AUTORESEARCH_TASK_TYPES = {"autoresearch", "autoresearch-coder", "ml-experiment"}
_LOCAL_RUNTIME_BACKENDS = {"ollama", "lm-studio", "mlx"}


def _run_ecc_sync_bg() -> None:
    """Blocking ECC sync run in a worker thread so startup stays responsive."""
    try:
        ecc_result = sync_ecc_tools(force=False)
        _startup_log.info(
            "ECC Tools sync: %s - %s",
            ecc_result.get("status"),
            ecc_result.get("message", ""),
        )
    except Exception as exc:  # noqa: BLE001
        _startup_log.warning("ECC Tools sync failed (non-fatal): %s", exc)


async def _resolve_routing_bg() -> None:
    """Resolve routing state in background — non-blocking startup."""
    try:
        routing = await resolve_routing_state()
        _startup_log.info(
            "Routing: manager=%s coder=%s (%s) distributed=%s",
            routing["manager_endpoint"],
            routing["coder_endpoint"],
            routing.get("coder_backend", "?"),
            routing["distributed"],
        )
    except Exception as exc:  # noqa: BLE001
        _startup_log.warning("Backend detection failed (non-fatal): %s", exc)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Both background tasks fire at t=0; neither blocks port binding.
    asyncio.get_event_loop().run_in_executor(None, _run_ecc_sync_bg)
    asyncio.create_task(_resolve_routing_bg(), name="routing-bg")
    yield


app = FastAPI(
    title="Perpetua-Tools Orchestrator",
    version="0.9.9.7",
    description=(
        "Top-level idempotent multi-agent orchestrator. "
        "Repo #1 complements ultrathink-system with routing, runtime "
        "reconciliation, and control-plane state."
    ),
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:8002", "http://127.0.0.1:8002",  # portal
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

tracker = AgentTracker()
registry = ModelRegistry()
cost_guard = CostGuard()
_ULTRATHINK_TASK_TYPES = {"deep_reasoning", "code_analysis"}

# ── User-input queue ──────────────────────────────────────────────────────────
# Shared in-process queue; agents poll GET /user-input/next to consume tasks.
# Portal or CLI can push via POST /user-input.
_USER_INPUT_QUEUE: collections.deque[Dict[str, Any]] = collections.deque(maxlen=50)


class OrchestrateRequest(BaseModel):
    task: str
    task_type: str = "default"
    preferred_device: Optional[str] = None
    estimated_cost: float = 0.0
    parent_agent_id: Optional[str] = None
    force: bool = False


class ConflictResponse(BaseModel):
    conflict: bool
    message: str
    existing_agents: List[Dict[str, Any]]


def _runtime_summary() -> dict[str, Any]:
    runtime_state = load_runtime_payload()
    if runtime_state is None:
        return {"available": False, "gateway_ready": False, "distributed": False}
    return {
        "available": True,
        "gateway_ready": bool(runtime_state.get("gateway", {}).get("gateway_ready")),
        "distributed": bool(runtime_state.get("routing", {}).get("distributed")),
    }


def _candidate_base_url(host: str, port: int) -> str:
    parsed = urlparse(host)
    if parsed.scheme and parsed.hostname:
        scheme = parsed.scheme
        hostname = parsed.hostname
        resolved_port = parsed.port or port
        return f"{scheme}://{hostname}:{resolved_port}"
    return f"{host.rstrip('/')}:{port}"


def _normalize_model_name(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _model_matches(available: str, expected: str) -> bool:
    lhs = _normalize_model_name(available)
    rhs = _normalize_model_name(expected)
    return lhs == rhs or lhs.startswith(rhs) or rhs.startswith(lhs) or rhs in lhs or lhs in rhs


def _is_local_candidate(model: Any) -> bool:
    return getattr(model, "backend", "") in _LOCAL_RUNTIME_BACKENDS and getattr(model, "device", "") != "cloud"


async def _probe_openai_compatible(
    base_url: str,
    expected_model: str,
    *,
    timeout: float,
    token: str = "",
) -> tuple[bool, str]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{base_url}/v1/models", headers=headers)
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"
        payload = resp.json()
        models = payload.get("data", []) if isinstance(payload, dict) else []
        ids = [
            item.get("id") or item.get("name") or ""
            for item in models
            if isinstance(item, dict)
        ]
        if ids and any(_model_matches(model_id, expected_model) for model_id in ids):
            return True, "model-available"
        if ids:
            return False, f"model-not-loaded:{expected_model}"
        return True, "reachable"


async def _probe_ollama_model(
    base_url: str,
    expected_model: str,
    *,
    timeout: float,
) -> tuple[bool, str]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{base_url}/api/tags")
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"
        payload = resp.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        names = [
            item.get("name") or item.get("model") or ""
            for item in models
            if isinstance(item, dict)
        ]
        if names and any(_model_matches(name, expected_model) for name in names):
            return True, "model-available"
        if names:
            return False, f"model-not-loaded:{expected_model}"
        return True, "reachable"


async def _probe_glm_cloud_candidate(model: Any) -> tuple[bool, str]:
    timeout = float(os.getenv("GLM_PROBE_TIMEOUT", "8"))
    base_url = _candidate_base_url(model.host, model.port)
    payload = {
        "model": model.name,
        "prompt": "ping",
        "stream": False,
        "options": {"num_predict": 1},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base_url}/api/generate", json=payload)
        if resp.status_code == 429:
            return False, "rate-limited"
        if resp.status_code >= 400:
            return False, f"HTTP {resp.status_code}"
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            return False, str(data["error"])
        if isinstance(data, dict) and (data.get("response") is not None or data.get("done") is not None):
            return True, "glm-ready"
        return False, "empty-response"


async def _candidate_availability(model: Any) -> tuple[bool, str]:
    backend = getattr(model, "backend", "")
    name = getattr(model, "name", "")
    if backend not in _LOCAL_RUNTIME_BACKENDS:
        return True, "not-probed"

    try:
        base_url = _candidate_base_url(model.host, model.port)
        timeout = float(os.getenv("MODEL_PROBE_TIMEOUT", "3"))
        if name == _GLM_ORCHESTRATOR_MODEL:
            return await _probe_glm_cloud_candidate(model)
        if backend == "ollama":
            return await _probe_ollama_model(base_url, name, timeout=timeout)
        if backend in {"lm-studio", "mlx"}:
            return await _probe_openai_compatible(
                base_url,
                name,
                timeout=timeout,
                token=os.getenv("LM_STUDIO_API_TOKEN", ""),
            )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return True, "unhandled-backend"


async def _resolve_candidates(
    candidates: List[Any],
    task_type: str,
) -> tuple[list[Any], dict[str, dict[str, Any]]]:
    resolved: list[Any] = []
    availability: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        ready, detail = await _candidate_availability(candidate)
        key = f"{getattr(candidate, 'name', 'unknown')}@{getattr(candidate, 'device', 'unknown')}"
        availability[key] = {
            "ready": ready,
            "detail": detail,
            "backend": getattr(candidate, "backend", ""),
            "device": getattr(candidate, "device", ""),
        }
        if ready:
            resolved.append(candidate)

    if task_type in _AUTORESEARCH_TASK_TYPES:
        local_ready = [candidate for candidate in resolved if _is_local_candidate(candidate)]
        if not local_ready:
            return [], availability
        return local_ready, availability

    return resolved or candidates, availability


@app.get("/ecc/status", tags=["ecc"])
def ecc_status() -> Dict[str, Any]:
    return get_sync_status()


@app.post("/ecc/sync", tags=["ecc"])
def ecc_sync(force: bool = Query(False)) -> Dict[str, Any]:
    try:
        return sync_ecc_tools(force=force)
    except Exception as exc:  # noqa: BLE001
        _startup_log.exception("ECC sync endpoint error")
        return {"status": "error", "message": str(exc)}


class UserInputRequest(BaseModel):
    message: str
    source: str = "portal"  # "portal" | "cli"


@app.post("/user-input", tags=["user-input"])
def post_user_input(req: UserInputRequest) -> Dict[str, Any]:
    """Queue a task message from the portal or CLI for researchers to pick up."""
    entry = {"message": req.message, "source": req.source, "ts": time.time()}
    _USER_INPUT_QUEUE.appendleft(entry)
    return {"status": "queued", "queue_depth": len(_USER_INPUT_QUEUE), "entry": entry}


@app.get("/user-input/next", tags=["user-input"])
def get_user_input_next() -> Dict[str, Any]:
    """Pop and return the next queued user message. Returns null message when empty."""
    if _USER_INPUT_QUEUE:
        return {"message": _USER_INPUT_QUEUE.pop()}
    return {"message": None}


@app.get("/user-input/status", tags=["user-input"])
def get_user_input_status() -> Dict[str, Any]:
    """Return queue depth and all pending messages (without consuming them)."""
    return {
        "queue_depth": len(_USER_INPUT_QUEUE),
        "pending": list(_USER_INPUT_QUEUE),
    }


@app.get("/health", tags=["system"])
def health(
    ollama_host: str = os.getenv("OLLAMA_MAC_ENDPOINT", "http://127.0.0.1:11434"),
    lm_studio_host: str = os.getenv("LM_STUDIO_MAC_ENDPOINT", "http://127.0.0.1:1234"),
    mlx_host: str = "http://127.0.0.1:8081",
) -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": "0.9.9.7",
        "runtime": _runtime_summary(),
        "backends": backend_health_map(
            ollama_host=ollama_host,
            lm_studio_host=lm_studio_host,
            mlx_host=mlx_host,
        ),
    }


@app.get("/budget", tags=["cost"])
def budget() -> Dict[str, Any]:
    return cost_guard.snapshot()


@app.get("/runtime", tags=["runtime"])
def runtime_state() -> Dict[str, Any]:
    payload = load_runtime_payload()
    if payload is None:
        return {"available": False, "runtime": None}
    return {"available": True, "runtime": payload}


@app.post("/runtime/bootstrap", tags=["runtime"])
async def runtime_bootstrap(
    force_gateway: bool = Query(False),
    autoresearch: bool = Query(True),
    run_tag: Optional[str] = Query(None),
) -> Dict[str, Any]:
    return await bootstrap_runtime(
        interactive=False,
        force_gateway=force_gateway,
        run_autoresearch_preflight=autoresearch,
        run_tag=run_tag,
        print_progress=False,
    )


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


@app.get("/activity", tags=["agents"])
def get_activity(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    from json import JSONDecodeError

    path = Path(".state/researcher_activity.jsonl")
    if not path.exists():
        return {"events": [], "count": 0}

    raw_lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events: List[Dict[str, Any]] = []
    for line in raw_lines[-limit:]:
        try:
            events.append(json.loads(line))
        except JSONDecodeError:
            pass
    events.sort(key=lambda event: event.get("ts", 0), reverse=True)
    return {"events": events, "count": len(events)}


@app.get("/models", tags=["models"])
def list_models() -> Dict[str, Any]:
    return {"models": [model.__dict__ for model in registry.list_models()]}


@app.get("/models/route", tags=["models"])
def route(
    task_type: str = Query("default"),
    preferred_device: Optional[str] = Query(None),
) -> Dict[str, Any]:
    chain = registry.route_task(task_type, preferred_device=preferred_device)
    return {"fallback_chain": [model.__dict__ for model in chain]}


@app.post("/orchestrate", tags=["orchestrate"])
async def orchestrate(req: OrchestrateRequest) -> Dict[str, Any]:
    task_hash = sha256(f"{req.task_type}:{req.task}".encode()).hexdigest()

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

    snapshot = cost_guard.snapshot()
    if not cost_guard.can_spend(req.estimated_cost):
        raise HTTPException(
            status_code=402,
            detail=f"Daily budget exceeded. Remaining: ${snapshot.get('remaining', 0):.4f}",
        )

    budget_warning = None
    if cost_guard.alert_approaching():
        budget_state = cost_guard.snapshot()
        budget_warning = (
            f"Budget at {budget_state['daily_spend']:.2f} / "
            f"{budget_state['daily_budget']:.2f} (>=80%)"
        )

    route_candidates = registry.route_task(req.task_type, preferred_device=req.preferred_device)
    if not route_candidates:
        raise HTTPException(
            status_code=404,
            detail=f"No model candidates found for task_type='{req.task_type}'",
        )

    candidates, availability = await _resolve_candidates(route_candidates, req.task_type)
    if req.task_type in _AUTORESEARCH_TASK_TYPES and not candidates:
        return {
            "status": "needs_user_action",
            "message": (
                "No viable local coder backend is reachable for autoresearch. "
                "Start Windows LM Studio Qwen 27B, qwen3-coder:14b on Windows Ollama, "
                "or a reachable local LM Studio fallback, then retry."
            ),
            "runtime": _runtime_summary(),
            "availability": availability,
        }

    selected = candidates[0]
    route_cfg = registry.routing_cfg.get("routes", {}).get(req.task_type, {})

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
        status="idle",
    )
    cost_guard.record_spend(req.estimated_cost)

    response: Dict[str, Any] = {
        "status": "created",
        "agent": asdict(agent),
        "selected_model": {
            "name": selected.name,
            "backend": selected.backend,
            "device": selected.device,
            "host": _candidate_base_url(selected.host, selected.port),
            "online": selected.online,
            "reasoning": selected.reasoning,
        },
        "fallback_chain": [
            {
                "priority": index + 2,
                "name": model.name,
                "backend": model.backend,
                "device": model.device,
                "online": model.online,
            }
            for index, model in enumerate(
                [model for model in route_candidates if model is not selected][:5]
            )
        ],
        "runtime": _runtime_summary(),
        "availability": availability,
    }
    if budget_warning:
        response["budget_warning"] = budget_warning

    if req.task_type in _ULTRATHINK_TASK_TYPES and route_cfg.get("endpoint"):
        timeout = parse_ultrathink_timeout(route_cfg.get("timeout"))
        try:
            response["ultrathink_bridge"] = {
                "enabled": True,
                **await call_ultrathink_mcp_or_bridge(
                    endpoint=str(route_cfg["endpoint"]),
                    timeout=timeout,
                    task=req.task,
                    task_type=req.task_type,
                ),
            }
        except Exception as exc:  # noqa: BLE001
            _startup_log.warning("UltraThink bridge call failed: %s", exc)
            response["ultrathink_bridge"] = {
                "enabled": True,
                "error": str(exc),
                "endpoint": os.path.expandvars(str(route_cfg["endpoint"])),
            }
    return response


@app.post("/autoresearch/sync", tags=["autoresearch"])
def autoresearch_sync(run_tag: Optional[str] = Query(None)) -> Dict[str, Any]:
    result = autoresearch_bridge.preflight(run_tag=run_tag)
    if not result["sync_ok"]:
        raise HTTPException(
            status_code=500,
            detail=f"Autoresearch sync failed: {result['error']}",
        )
    return result


@app.get("/autoresearch/gpu_status", tags=["autoresearch"])
def autoresearch_gpu_status() -> Dict[str, Any]:
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("orchestrator.fastapi_app:app", host="0.0.0.0", port=8000, reload=True)

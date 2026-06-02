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
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from orchestrator.control_plane_auth import (
    control_plane_auth_failure,
    ensure_control_plane_token,
    pt_path_requires_auth,
    redact_runtime_payload,
)

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

# GC guard for fire-and-forget startup tasks (D_GCG-1 from RAG backport 2026-05-22).
# asyncio.create_task() only holds a *weak* reference; without a strong reference
# in this set the task can be collected before it completes.  Each task discards
# itself via done-callback so the set stays bounded.
_bg_startup_tasks: set[asyncio.Task] = set()


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
    token = ensure_control_plane_token()
    if token:
        _startup_log.info(
            "Control-plane bearer auth active; token persisted to .state/control_plane_token"
        )
    # Both background tasks fire at t=0; neither blocks port binding.
    asyncio.get_event_loop().run_in_executor(None, _run_ecc_sync_bg)
    # Hold a strong reference so GC cannot collect the task before it runs (D_GCG-1).
    _routing_task = asyncio.create_task(_resolve_routing_bg(), name="routing-bg")
    _bg_startup_tasks.add(_routing_task)
    _routing_task.add_done_callback(_bg_startup_tasks.discard)
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
        "http://localhost:3000", "http://localhost:3000",
        "http://localhost:8002", "http://localhost:8002",  # portal
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def _control_plane_auth_middleware(request: Request, call_next):
    if pt_path_requires_auth(request.url.path, request.method):
        failure = control_plane_auth_failure(request)
        if failure is not None:
            return failure
    return await call_next(request)


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
    message: str = Field(..., min_length=1, max_length=4000)
    source: str = "portal"  # "portal" | "cli"


@app.post("/user-input", tags=["user-input"])
def post_user_input(req: UserInputRequest) -> Dict[str, Any]:
    """Queue a task message from the portal or CLI for researchers to pick up."""
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required")
    entry = {"message": message, "source": req.source, "ts": time.time()}
    _USER_INPUT_QUEUE.appendleft(entry)
    return {"status": "queued", "queue_depth": len(_USER_INPUT_QUEUE), "entry": entry}


@app.get("/user-input/next", tags=["user-input"])
def get_user_input_next() -> Dict[str, Any]:
    """Return and remove the next queued user message.

    Empty queue: ``{"message": null}`` only (no ``source`` / ``ts`` keys).
    When a message is available, returns the enqueued ``message`` and, when
    present on the queued entry, ``source`` and ``ts`` (via ``dict.get``).

    Implementation uses two complementary guards (additive, not either/or):
    - ``if not _USER_INPUT_QUEUE`` — fast path for idle queue; preserves the
      historical empty response shape used by portal researchers and CLI pollers.
    - ``try`` / ``except IndexError`` on ``pop()`` — covers concurrent
      ``GET /user-input/next`` callers that race between the emptiness check
      and the pop; treated as empty, not a server error.

    Returns:
        dict: ``{"message": None}`` if no entry is available (empty queue or
        concurrent race); otherwise
        ``{"message": str, "source": str | None, "ts": int | float | None}``.
    """
    if not _USER_INPUT_QUEUE:
        return {"message": None}
    try:
        entry = _USER_INPUT_QUEUE.pop()
    except IndexError:
        # Another poller drained the queue after our check — same contract as empty.
        return {"message": None}
    return {
        "message": entry["message"],
        "source": entry.get("source"),
        "ts": entry.get("ts"),
    }


@app.get("/user-input/status", tags=["user-input"])
def get_user_input_status() -> Dict[str, Any]:
    """Return queue depth and all pending messages (without consuming them)."""
    return {
        "queue_depth": len(_USER_INPUT_QUEUE),
        "pending": list(_USER_INPUT_QUEUE),
    }


@app.get("/health", tags=["system"])
def health(
    ollama_host: str = os.getenv("OLLAMA_MAC_ENDPOINT", "http://localhost:11434"),
    lm_studio_host: str = os.getenv("LM_STUDIO_MAC_ENDPOINT", "http://localhost:1234"),
    mlx_host: str = "http://localhost:8081",
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
    return {"available": True, "runtime": redact_runtime_payload(payload)}


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
                "Start Windows LM Studio (Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2) "
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


# ── V1 Supervisor endpoints ───────────────────────────────────────────────────
# Thin HTTP surface over OrchestrationSupervisor — handlers ≤ 10 lines each.
# Brainstorm ref: orama-system/docs/2026-05-08-v1-supervisor-brainstorm.md §5
# Legacy /orchestrate route (orchestrator.py) stays intact — backwards compatible.

import re as _re

from orchestrator.supervisor import JobSpec, JobStatus, OrchestrationSupervisor, _new_id

# Security: job_id flows into filesystem paths (.state/jobs/<id>/result.json)
# via OrchestrationSupervisor. Validate the format at the HTTP boundary so a
# path-traversal payload (e.g. ".." or absolute paths) never reaches disk I/O.
# _new_id() generates uuid.uuid4() — accept only that exact shape.
_UUID4_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    _re.IGNORECASE,
)


def _validate_job_id(job_id: str) -> str:
    """
    Validate that job_id is a server-issued UUIDv4.
    
    Raises:
        HTTPException: 400 with a fixed detail message if `job_id` does not match the strict UUIDv4 pattern.
    
    Returns:
        str: The validated `job_id` unchanged.
    """
    if not _UUID4_RE.match(job_id):
        raise HTTPException(
            status_code=400,
            detail="job_id must be a uuid4-formatted server-issued identifier",
        )
    return job_id


_supervisor: OrchestrationSupervisor | None = None


def _get_supervisor() -> OrchestrationSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = OrchestrationSupervisor()
    return _supervisor


class _JobSubmitRequest(BaseModel):
    intent:       str = "freeform"
    prompt:       str
    backend_hint: Optional[str] = None
    constraints:  Dict[str, Any] = {}
    metadata:     Dict[str, Any] = {}
    # Skill routing: maps to openclaw-skills SKILL_MAP when non-empty.
    # Without this field the skill gate in _dispatch() is never triggered
    # for API-submitted jobs.
    task_type:    str = ""


@app.post("/v1/jobs", tags=["supervisor"])
async def supervisor_submit_job(req: _JobSubmitRequest):
    """Submit a job to the V1 OrchestrationSupervisor (file-based persistence)."""
    spec = JobSpec(
        job_id=_new_id(),
        intent=req.intent,
        prompt=req.prompt,
        backend_hint=req.backend_hint,
        constraints=req.constraints,
        metadata=req.metadata,
        task_type=req.task_type,
    )
    try:
        job_id = await _get_supervisor().submit_job(spec)
        return {"job_id": job_id, "state": JobStatus.QUEUED.value}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/v1/jobs", tags=["supervisor"])
async def supervisor_list_jobs(status: Optional[str] = None):
    """List all known jobs, optionally filtered by status string."""
    try:
        filter_status = JobStatus(status) if status else None
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown status: {status}") from None
    return {"jobs": _get_supervisor().list_jobs(status=filter_status)}


@app.get("/v1/jobs/{job_id}", tags=["supervisor"])
async def supervisor_get_job(job_id: str):
    """
    Retrieve the last-known state for the specified supervisor job.
    
    Parameters:
        job_id (str): Job identifier (must be a UUIDv4).
    
    Returns:
        dict: The job's last-known status as returned by the supervisor.
    
    Raises:
        HTTPException: 400 if `job_id` fails UUIDv4 validation.
        HTTPException: 404 if no job with `job_id` exists.
    """
    _validate_job_id(job_id)
    result = await _get_supervisor().get_status(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@app.post("/v1/jobs/{job_id}/cancel", tags=["supervisor"])
async def supervisor_cancel_job(job_id: str):
    """
    Request cancellation of a running job identified by its job ID.
    
    Parameters:
        job_id (str): UUIDv4 job identifier. Must match the server's UUIDv4 format; otherwise an HTTPException(400) is raised.
    
    Returns:
        dict: {
            "job_id": job_id,
            "cancel_requested": bool
        } where `cancel_requested` is `True` if a cancellation was requested, `False` otherwise.
    """
    _validate_job_id(job_id)
    cancelled = await _get_supervisor().cancel(job_id)
    return {"job_id": job_id, "cancel_requested": cancelled}


@app.post("/v1/jobs/{job_id}/replay", tags=["supervisor"])
async def supervisor_replay_job(job_id: str):
    """
    Replay a completed, failed, or cancelled job by creating a new job with a fresh job_id.
    
    Validates that `job_id` is a UUIDv4; on success requests the supervisor to replay the job and returns the new job's id and queued state.
    
    Parameters:
        job_id (str): The UUIDv4 identifier of the existing job to replay.
    
    Returns:
        dict: {
            "original_job_id": <original id>,
            "new_job_id": <newly issued job id>,
            "state": JobStatus.QUEUED.value
        }
    
    Raises:
        HTTPException: 400 if `job_id` is not a valid UUIDv4.
        HTTPException: 404 if the original job cannot be found or replay is not possible.
    """
    _validate_job_id(job_id)
    try:
        new_id = await _get_supervisor().replay(job_id)
        return {"original_job_id": job_id, "new_job_id": new_id, "state": JobStatus.QUEUED.value}
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found") from None


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("orchestrator.fastapi_app:app", host="localhost", port=8000, reload=True)

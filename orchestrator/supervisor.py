"""Perpetua-Tools V1 OrchestrationSupervisor — file-based persistence only.

No DB, no SQLite.  All state lives in two artefacts:
  .state/jobs.jsonl          — append-only event log (one JSON line per transition)
  .state/jobs/<id>/result.json — per-job result artifact

Dispatch shape (Anthropic pattern): coordinator → worker, depth ≤ MAX_DEPTH=1.
Workers never spawn sub-workers (hard-enforced at submit_job time).

References:
  - Anthropic pattern synthesis: v2/5-Anthropic-agent-design.md §1, §2, §4
  - Brainstorm doc: orama-system/docs/2026-05-08-v1-supervisor-brainstorm.md §4
  - SKILL.md rules: no auto-retry on HardwareAffinityError; fail-closed
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.dispatch_models import backend_requires_dispatch_model
from utils.hardware_policy import HardwareAffinityError, check_affinity


# ── Constants ─────────────────────────────────────────────────────────────────
MAX_DEPTH = 1       # Anthropic hard constraint: depth > 1 rejected
MAX_THREADS = 25    # Anthropic spec ceiling — 25 concurrent workers max
STATE_DIR = Path(".state")
JOBS_JSONL = STATE_DIR / "jobs.jsonl"

# Backends that run entirely on the Mac GPU.  The Windows coder pool preempts
# these when a healthy Windows endpoint is available.  "mlx" is included so a
# future MLX worker (Apple Silicon accelerated) is also preempted correctly.
# Must stay in sync with worker_registry.WORKER_REGISTRY key names.
_MAC_LOCAL_BACKENDS: frozenset = frozenset(
    {"ollama", "ollama-mac", "lmstudio-mac", "mlx"}
)


# ── Enums ─────────────────────────────────────────────────────────────────────
class JobStatus(str, Enum):
    """Lifecycle states for a supervisor job."""
    QUEUED        = "queued"
    RUNNING       = "running"
    WAITING_INPUT = "waiting_input"
    SUCCEEDED     = "succeeded"
    FAILED        = "failed"
    CANCELLED     = "cancelled"


def _new_id_default() -> str:
    return str(uuid.uuid4())


def _now_iso_default() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobSpec(BaseModel):
    """Immutable job descriptor submitted to the supervisor.

    New fields added in § 5.1 of the unified absorption plan:
      role, specialization, session_id, parent_orchestrator_id,
      artifact_policy, depth.
    All existing fields remain backward-compatible (job_id and prompt
    now have sensible defaults so old call sites that omit them still work).
    """
    model_config = ConfigDict(frozen=True)

    # Core (all optional with safe defaults for backward compat)
    job_id:       str  = Field(default_factory=_new_id_default)
    intent:       str  = ""
    prompt:       str  = ""
    backend_hint: Optional[str] = None   # "auto"|"codex"|"gemini"|…
    constraints:  Union[List[str], Dict[str, Any]] = Field(default_factory=dict)   # max_seconds/tokens (dict) or constraint tags (list)
    metadata:     Dict[str, Any] = Field(default_factory=dict)   # model, …
    created_at:   str  = Field(default_factory=_now_iso_default)

    # New worker-role fields (§ 5.1)
    role:                    Optional[str] = None
    specialization:          Optional[str] = None
    session_id:              Optional[str] = None
    parent_orchestrator_id:  Optional[str] = None
    artifact_policy:         Optional[str] = None   # "default" | None | custom tag

    # V1 depth invariant: workers do NOT spawn sub-workers
    depth: int = Field(default=0, ge=0)

    # Skill routing: maps to openclaw-skills SKILL_MAP when set
    task_type: str = ""

    @field_validator("depth", mode="before")
    @classmethod
    def no_sub_workers(cls, v: Any) -> int:
        val = int(v)
        if val != 0:
            raise ValueError(
                "Workers cannot spawn sub-workers in V1. depth must be 0."
            )
        return val

    def to_dict(self) -> dict:
        return self.model_dump()


# ── Pure persistence helpers ──────────────────────────────────────────────────
def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_state_dir(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "jobs").mkdir(exist_ok=True)


def _append_event(jobs_file: Path, job_id: str, event: dict) -> None:
    """
    Append a single JSONL event record for a job to the given jobs file.
    
    The written record combines an ISO UTC timestamp (`ts`), the provided `job_id`, and the key/value pairs from `event` (any `JobStatus` values are serialized to their `.value`). The append is performed under an exclusive file lock and flushed to stable storage to avoid interleaved lines and to make the entry durable on disk.
    """
    import fcntl as _fcntl
    import os as _os
    # Serialise JobStatus values to their string form
    serialisable = {
        k: (v.value if isinstance(v, JobStatus) else v)
        for k, v in event.items()
    }
    line = json.dumps({"ts": _now_iso(), "job_id": job_id, **serialisable}) + "\n"
    with jobs_file.open("a", encoding="utf-8") as fh:
        try:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX)
            fh.write(line)
            fh.flush()
            _os.fsync(fh.fileno())
        finally:
            try:
                _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
            except OSError:
                pass  # lock release on a closing fh is non-fatal


def _load_events(jobs_file: Path) -> list[dict]:
    """
    Load persisted job event records from a JSONL file.
    
    Ignores empty lines and silently skips lines that fail JSON decoding (tolerates truncated or corrupt trailing lines).
    
    Returns:
        list[dict]: Parsed event objects in file order; an empty list if the file does not exist.
    """
    if not jobs_file.exists():
        return []
    events: list[dict] = []
    for raw in jobs_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return events


def _latest_status_per_job(events: list[dict]) -> dict[str, dict]:
    """Fold the event log → last-known event per job_id."""
    states: dict[str, dict] = {}
    for evt in events:
        jid = evt.get("job_id")
        if jid:
            states[jid] = evt
    return states


# ── Main supervisor class ─────────────────────────────────────────────────────
class OrchestrationSupervisor:
    """
    V1 durable orchestration supervisor.

    File-based persistence — no DB, no SQLite.
    All state transitions append to .state/jobs.jsonl.
    Per-job results land in .state/jobs/<id>/result.json.

    Public API (wired to FastAPI in orchestrator/fastapi_app.py):
      submit_job(spec)       → job_id (str)
      get_status(job_id)     → dict | None
      cancel(job_id)         → bool
      replay(job_id, …)      → new job_id (str)
      list_jobs(status?)     → list[dict]
    """

    MAX_DEPTH   = MAX_DEPTH
    MAX_THREADS = MAX_THREADS

    def __init__(self, state_dir: Path | str = STATE_DIR):
        """
        Initialize the OrchestrationSupervisor and prepare on-disk state and runtime caches.
        
        Parameters:
            state_dir (Path | str): Directory used to persist supervisor state (jobs.jsonl and per-job artifacts). Defaults to the module-level STATE_DIR.
        
        Side effects:
            - Ensures the state directory and its jobs subdirectory exist.
            - Sets the process environment variable `PT_STATE_DIR` to the resolved state directory path.
            - Initializes in-memory runtime fields (active task map, cached gossip bus handle, and gossip failure flag).
        """
        self._state_dir = Path(state_dir)
        self._jobs_file = self._state_dir / "jobs.jsonl"
        self._active: dict[str, asyncio.Task] = {}
        # Cached GossipBus (set on first _record_to_gossip; reused per
        # supervisor instance to avoid re-running CREATE TABLE IF NOT EXISTS
        # schema DDL on every job completion). Lazy because GossipBus opens an
        # aiosqlite connection — we don't pay for that if no jobs ever emit.
        self._gossip_bus = None
        # Once-per-process rate limit for gossip emit failures. First failure
        # logs at WARNING (so ops sees memory recall is broken); subsequent
        # failures drop back to DEBUG to avoid log spam.
        self._gossip_warned = False
        _ensure_state_dir(self._state_dir)
        # Process-global PT_STATE_DIR mutation — load-bearing for memory_node's
        # module-level `_default_bus` singleton. memory_node._get_default_bus()
        # is called from request paths that don't have a supervisor handle and
        # resolves the DB path via this env var. Single supervisor per process
        # in production; tests use monkeypatch.setenv for isolation.
        # Colocate GossipBus with jobs.jsonl so memory recall sees completed work.
        os.environ["PT_STATE_DIR"] = str(self._state_dir.resolve())

    # ── Public API ─────────────────────────────────────────────────────────────

    async def submit_job(self, spec: JobSpec) -> str:
        """Validate → persist QUEUED → fire async worker task → return job_id."""
        # Only the dispatcher may set _win_endpoint (injected after pool probe).
        if spec.metadata and "_win_endpoint" in spec.metadata:
            meta = {k: v for k, v in spec.metadata.items() if k != "_win_endpoint"}
            spec = spec.model_copy(update={"metadata": meta})

        # Depth guard — workers cannot spawn sub-workers
        if spec.depth > self.MAX_DEPTH:
            raise ValueError(
                f"Depth {spec.depth} exceeds MAX_DEPTH={self.MAX_DEPTH}. "
                "Worker spawning sub-workers is forbidden."
            )
        # Thread ceiling
        if len(self._active) >= self.MAX_THREADS:
            raise RuntimeError(
                f"Thread ceiling {self.MAX_THREADS} reached; cannot accept new job."
            )
        # Hardware affinity + explicit model ids BEFORE any LLM call (Anthropic Pattern 4).
        # Uses resolved backend (not only backend_hint) so role/intent paths cannot skip policy.
        from orchestrator.worker_registry import resolve_backend

        backend = resolve_backend(spec)
        if backend_requires_dispatch_model(backend):
            # Affinity gate only — do not inject metadata.model here. Injection at
            # QUEUED time pins Mac defaults so Windows pool preemption would POST the
            # wrong model id to lmstudio-win (see test_submit_then_win_preempt_*).
            from utils.dispatch_models import resolve_dispatch_model

            plat = OrchestrationSupervisor._backend_to_platform(backend)
            model_id = resolve_dispatch_model(
                backend,
                spec.metadata or {},
                role=spec.role,
                specialization=spec.specialization,
            )
            check_affinity(model_id, plat)

        self._append_event(spec.job_id, {"status": JobStatus.QUEUED, "spec": spec.to_dict()})
        task = asyncio.create_task(
            self._run_worker(spec),
            name=f"worker-{spec.job_id}",
        )
        self._active[spec.job_id] = task
        return spec.job_id

    async def get_status(self, job_id: str) -> dict | None:
        """Return last-known event for job_id, augmented with artifact path."""
        events = _load_events(self._jobs_file)
        states = _latest_status_per_job(events)
        raw = states.get(job_id)
        if raw is None:
            return None

        result_path = self._state_dir / "jobs" / job_id / "result.json"
        result = None
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        return {
            **raw,
            "artifact": str(result_path) if result_path.exists() else None,
            "result": result,
        }

    async def cancel(self, job_id: str) -> bool:
        """Cancel a running job.  Returns True if cancellation was requested."""
        task = self._active.get(job_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def replay(self, job_id: str, overrides: dict | None = None) -> str:
        """Re-run a failed or cancelled job under a new job_id."""
        events = _load_events(self._jobs_file)
        states = _latest_status_per_job(events)
        raw = states.get(job_id)
        if raw is None:
            raise ValueError(f"Job {job_id} not found")

        spec_dict = raw.get("spec", {})
        if overrides:
            spec_dict = {**spec_dict, **overrides}

        new_spec = JobSpec(
            job_id=_new_id(),
            intent=spec_dict.get("intent", "freeform"),
            prompt=spec_dict.get("prompt", ""),
            backend_hint=spec_dict.get("backend_hint"),
            constraints=spec_dict.get("constraints", {}),
            metadata=spec_dict.get("metadata", {}),
            role=spec_dict.get("role"),
            specialization=spec_dict.get("specialization"),
            session_id=spec_dict.get("session_id"),
            parent_orchestrator_id=spec_dict.get("parent_orchestrator_id"),
            artifact_policy=spec_dict.get("artifact_policy"),
            # Preserve skill-routing field so retries follow the same path.
            task_type=spec_dict.get("task_type", ""),
        )
        return await self.submit_job(new_spec)

    def list_jobs(self, status: Optional[JobStatus] = None) -> list[dict]:
        """Return all known jobs, optionally filtered by status."""
        events = _load_events(self._jobs_file)
        states = _latest_status_per_job(events)
        jobs = list(states.values())
        if status is not None:
            jobs = [j for j in jobs if j.get("status") == status.value]
        return jobs

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _run_worker(self, spec: JobSpec) -> None:
        """
        Execute a job, persist its result artifact, record lifecycle events, and emit gossip notifications.
        
        Appends a RUNNING event, calls the dispatch pipeline, writes the job artifact to .state/jobs/<job_id>/result.json (the serialized UTF-8 payload is capped at 2 MiB; if exceeded a truncated marker object is written), then appends a SUCCEEDED event and emits a "result" gossip. On HardwareAffinityError records a FAILED event with `policy: True` and emits an "error" gossip; on any other exception records a FAILED event and emits an "error" gossip. On cancellation records a CANCELLED event before re-raising the cancellation. Always removes the job from the active task map when finished.
        
        Parameters:
            spec (JobSpec): Immutable descriptor of the job to run; its `job_id` is used for event records and artifact path.
        
        Raises:
            asyncio.CancelledError: Re-raised after recording a CANCELLED event when the running task is cancelled.
        """
        self._append_event(spec.job_id, {"status": JobStatus.RUNNING})
        job_dir = self._state_dir / "jobs" / spec.job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        try:
            result = await self._dispatch(spec)
            # Write result artifact BEFORE persisting final state.
            # Critical ordering from Anthropic spec: write checkpoint then kill,
            # never kill then write (data loss on crash during termination).
            #
            # Security (2026-05-28 v1 audit, HIGH 5): cap result size at 2 MiB.
            # An LLM running away (or a prompt-injected loop) can return many MB
            # of text per job; without a cap this fills .state/ and degrades the
            # supervisor. Truncated marker lets _dispatch tests assert the cap.
            _MAX_RESULT_BYTES = 2 * 1024 * 1024  # 2 MiB
            serialized = json.dumps(result, ensure_ascii=False, indent=2)
            if len(serialized.encode("utf-8")) > _MAX_RESULT_BYTES:
                truncated = {
                    "status": "truncated",
                    "reason": f"result exceeded {_MAX_RESULT_BYTES} bytes",
                    "original_size_bytes": len(serialized.encode("utf-8")),
                }
                serialized = json.dumps(truncated, ensure_ascii=False, indent=2)
            (job_dir / "result.json").write_text(serialized, encoding="utf-8")
            self._append_event(spec.job_id, {
                "status": JobStatus.SUCCEEDED,
                "artifact": str(job_dir / "result.json"),
            })
            await self._record_to_gossip("result", spec)

        except asyncio.CancelledError:
            # Write CANCELLED checkpoint BEFORE propagating cancellation
            self._append_event(spec.job_id, {"status": JobStatus.CANCELLED})
            raise

        except HardwareAffinityError as exc:
            # Fail-closed — SKILL.md rule: no auto-retry on policy errors
            self._append_event(spec.job_id, {
                "status": JobStatus.FAILED,
                "error": str(exc),
                "policy": True,
            })
            await self._record_to_gossip("error", spec, {"detail": str(exc), "policy": True})

        except Exception as exc:
            self._append_event(spec.job_id, {
                "status": JobStatus.FAILED,
                "error": str(exc),
            })
            await self._record_to_gossip("error", spec, {"detail": str(exc)})

        finally:
            self._active.pop(spec.job_id, None)

    async def _record_to_gossip(
        self,
        event_type: str,
        spec: JobSpec,
        extra: dict | None = None,
    ) -> None:
        """
        Emit a job-related event to the GossipBus for downstream memory and gossip.
        
        Builds a payload containing `job_id`, `prompt`, `intent`, and `role` when present, merges `extra` if provided, lazily initializes the GossipBus, ensures the gossip DB is ready, and emits the event. All exceptions are suppressed: the first emission failure is logged at WARNING and subsequent failures are logged at DEBUG.
        
        Parameters:
            extra (dict | None): Additional key/value pairs to merge into the emitted payload.
        """
        import logging

        payload: dict = {
            "job_id": spec.job_id,
            "prompt": spec.prompt,
            "intent": spec.intent,
        }
        if spec.role:
            payload["role"] = spec.role
        if extra:
            payload.update(extra)
        try:
            from orchestrator.memory_node import ensure_gossip_db_ready  # noqa: PLC0415

            if self._gossip_bus is None:
                from orchestrator.gossip_bus import GossipBus, resolve_gossip_db_path  # noqa: PLC0415
                self._gossip_bus = GossipBus(resolve_gossip_db_path(self._state_dir))

            await ensure_gossip_db_ready(self._gossip_bus)
            await self._gossip_bus.emit(event_type, payload)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover
            log = logging.getLogger(__name__)
            if not self._gossip_warned:
                log.warning(
                    "_record_to_gossip: gossip emit failed — memory recall will not see "
                    "this job. Further failures suppressed to DEBUG. (%s)",
                    exc,
                )
                self._gossip_warned = True
            else:
                log.debug("_record_to_gossip: skipped — %s", exc)

    async def _inject_memory_context(self, spec: JobSpec) -> JobSpec:
        """
        Injects retrieved memory snippets into the job prompt when memory is enabled.
        
        If memory retrieval yields one or more text hits, a numbered "[MEMORY CONTEXT]" block
        is prepended to the existing prompt and a new JobSpec with the enriched prompt is returned.
        If memory is disabled via spec.metadata["use_memory"] == False, or retrieval returns no
        usable hits, the original spec is returned unchanged. This function never raises; on error
        it returns the original spec.
        
        Returns:
            JobSpec: the updated JobSpec with an injected memory context when available, otherwise the original spec.
        """
        if (spec.metadata or {}).get("use_memory", True) is False:
            return spec
        try:
            from orchestrator.memory_node import retrieve_context  # noqa: PLC0415
            hits = await retrieve_context(spec.prompt or spec.intent or "")
            if not hits:
                return spec
            context_block = "\n".join(
                f"[{i + 1}] {h.get('text', '')}" for i, h in enumerate(hits) if h.get("text")
            )
            if not context_block.strip():
                return spec
            enriched_prompt = (
                f"[MEMORY CONTEXT]\n{context_block}\n[END MEMORY CONTEXT]\n\n"
                + (spec.prompt or "")
            )
            return spec.model_copy(update={"prompt": enriched_prompt})
        except Exception as exc:  # pragma: no cover
            import logging  # noqa: PLC0415
            logging.getLogger(__name__).debug(
                "_inject_memory_context: error (ignored) — %s", exc
            )
            return spec

    async def _dispatch(self, spec: JobSpec) -> dict:
        """Route spec to the correct backend worker and return its result dict.

        Priority:
          0. Memory context injection (RAG — item 7) — enriches prompt when store
             has relevant context; degrades silently if store is empty or unavailable.
          1. openclaw-skills primary path (deterministic, zero-LLM)
          2. resolve_backend — compute the intended backend from role/intent/hint
          3. Windows coder pool probe — two cases:
             a. Mac-local backends (ollama, ollama-mac, lmstudio-mac, mlx):
                Windows preempts entirely when pool is reachable.
             b. Explicit ``lmstudio-win`` (via role map or backend_hint):
                Pool is probed to inject ``_win_endpoint``; without it the worker
                falls back to ``LM_STUDIO_WIN_ENDPOINTS`` which may not be set in
                environments that only configure ``WIN_CODER_ENDPOINTS``.
             Non-Windows backends (echo, codex, gemini) are never probed.
          4. Normal backend routing via WORKER_REGISTRY
        """
        import logging
        _log = logging.getLogger(__name__)

        # 0. Memory context injection — enriches prompt before any routing decision.
        #    Degrades silently: empty store, missing dependencies → original spec unchanged.
        spec = await self._inject_memory_context(spec)

        # 1. Spawning gate — check if this task maps to a known openclaw-skills ID
        skill_envelope = self._try_skill_envelope(spec)
        if skill_envelope is not None:
            _log.info(
                "spawn_gate: routing job %s to skill %s",
                spec.job_id, skill_envelope.skill_id,
            )
            # SkillEnvelope is a @dataclass, not a Pydantic model — use to_dict().
            return {"status": "ok", "skill_envelope": skill_envelope.to_dict()}

        # 2. Resolve the intended backend first so the Windows override can
        #    inspect it. Must happen before any probe to avoid hijacking jobs
        #    whose backend_hint or intent points at non-Mac-local workers.
        from orchestrator.worker_registry import WORKER_REGISTRY, resolve_backend
        backend = resolve_backend(spec)

        # 3. Windows coder pool probe.
        # Probe whenever the job is destined for any Windows LM Studio path:
        #   • Mac-local backends → pool preempts routing (override)
        #   • explicit lmstudio-win → pool injects _win_endpoint (no routing change)
        # Skipped entirely for echo/codex/gemini/cloud so no unnecessary LAN probe.
        _needs_win_probe = backend in _MAC_LOCAL_BACKENDS or backend == "lmstudio-win"
        if _needs_win_probe:
            win_url = await self._get_reachable_windows_coder()
            if win_url is not None:
                from utils.model_endpoint_url import redact_endpoint_for_log

                _log.info(
                    "windows_coder_pool: dispatching job %s to %s",
                    spec.job_id,
                    redact_endpoint_for_log(win_url),
                )
                # Re-validate affinity for Windows + inject explicit model id (never "").
                spec_for_win = self._prepare_spec_for_inference(
                    spec, "lmstudio-win", affinity_platform="win"
                )
                worker_fn = WORKER_REGISTRY.get("lmstudio-win", WORKER_REGISTRY["echo"])
                spec_for_win = spec_for_win.model_copy(
                    update={
                        "metadata": {
                            **(spec_for_win.metadata or {}),
                            "_win_endpoint": win_url,
                        }
                    }
                )
                result = await worker_fn(spec_for_win)
                if backend in _MAC_LOCAL_BACKENDS:
                    # Mac-local preempted by Windows — flag for callers/tests.
                    return {**result, "routed_to_windows": True, "windows_endpoint": win_url}
                # Explicit lmstudio-win: no preemption flag; endpoint was injected above.
                return result
            # Pool unreachable: Mac-local falls through to normal routing (may fail);
            # explicit lmstudio-win falls through to worker's LM_STUDIO_WIN_ENDPOINTS.

        # 4. Normal backend routing (resolve_backend already called above)
        worker_fn = WORKER_REGISTRY.get(backend, WORKER_REGISTRY["echo"])
        if backend_requires_dispatch_model(backend):
            spec = self._prepare_spec_for_inference(spec, backend)
        return await worker_fn(spec)

    @staticmethod
    def _try_skill_envelope(spec: "JobSpec"):
        """Return a SkillEnvelope if this task maps to a known openclaw-skills ID, else None.

        Routing invariant (fail-closed): if ``task_type`` IS mapped to a skill,
        any resolver failure raises ``RuntimeError`` — it never silently degrades
        to a lower-priority backend.  This prevents a misconfigured or missing
        openclaw-skills tree from routing privileged tasks to the wrong model.
        """
        from orchestrator.openclaw_skill_resolver import (
            RecursionBudgetExceeded,
            SkillResolutionError,
            resolve_skill,
        )

        _SKILL_MAP = {
            "new_agent": "openclaw-new-agent",
            "add_channel": "openclaw-add-channel",
            "add_cron": "openclaw-add-cron",
            "dream_setup": "openclaw-dream-setup",
            "add_script": "openclaw-add-script",
            "add_secret": "openclaw-add-secret",
            "status": "openclaw-status",
            "restart": "openclaw-restart",
            "stow": "openclaw-stow",
        }
        task_type = getattr(spec, "task_type", None) or ""
        skill_id = _SKILL_MAP.get(task_type)
        if not skill_id:
            return None
        try:
            args = getattr(spec, "metadata", {}) or {}
            return resolve_skill(skill_id, args, agent_id=spec.job_id)
        except RecursionBudgetExceeded:
            # Fail-closed: recursion budget is a hard safety guard, not a routing
            # hint. Re-raise so _run_worker marks the job FAILED rather than
            # silently falling through to a lower-priority dispatch path.
            raise
        except SkillResolutionError as exc:
            # task_type IS mapped → the skill MUST resolve or the job FAILS.
            # Never silently degrade to a lower-priority backend when the caller
            # explicitly requested a skill-routed task_type.
            raise RuntimeError(
                f"Skill routing failed for task_type={task_type!r} "
                f"(skill_id={skill_id!r}): {exc}"
            ) from exc
        # Do NOT catch generic Exception here — unmapped bugs should propagate
        # and be caught by _run_worker, not swallowed inside the skill gate.

    @staticmethod
    async def _get_reachable_windows_coder() -> "str | None":
        """Return the first reachable Windows coder URL from WIN_CODER_ENDPOINTS, or None.

        Uses an async httpx probe so slow/offline endpoints never block the event
        loop.  Each endpoint is tried in order with a short timeout (2.5 s).
        Returns None silently when the pool is empty or all endpoints are offline.
        """
        import os
        import httpx

        from utils.model_endpoint_url import (
            ModelEndpointPolicyError,
            parse_model_endpoint_list,
            redact_endpoint_for_log,
        )

        raw = os.environ.get("WIN_CODER_ENDPOINTS", "")
        try:
            pool = parse_model_endpoint_list(raw)
        except ModelEndpointPolicyError as exc:
            log = __import__("logging").getLogger(__name__)
            log.error("windows_coder_pool: invalid WIN_CODER_ENDPOINTS — %s", exc)
            return None
        if not pool:
            return None

        log = __import__("logging").getLogger(__name__)
        async with httpx.AsyncClient(timeout=2.5) as client:
            for url in pool:
                try:
                    r = await client.get(f"{url}/v1/models")
                    if r.status_code < 400:
                        log.info(
                            "windows_coder_pool: %s is reachable",
                            redact_endpoint_for_log(url),
                        )
                        return url
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "windows_coder_pool: probe failed for %s — %s",
                        redact_endpoint_for_log(url),
                        exc,
                    )
        log.warning(
            "windows_coder_pool: no reachable Windows coder in pool (%d endpoints)",
            len(pool),
        )
        return None

    def _append_event(self, job_id: str, event: dict) -> None:
        _append_event(self._jobs_file, job_id, event)

    @staticmethod
    def _prepare_spec_for_inference(
        spec: JobSpec,
        backend: str,
        *,
        affinity_platform: str | None = None,
    ) -> JobSpec:
        """Resolve explicit model id, run affinity gate, inject metadata.model when missing.

        lmstudio-mac must never rely on LM Studio's "loaded model" fallback (anti-mirror).
        """
        if not backend_requires_dispatch_model(backend):
            return spec

        from utils.dispatch_models import ensure_metadata_model, resolve_dispatch_model

        plat = affinity_platform or OrchestrationSupervisor._backend_to_platform(backend)
        win_target = plat if plat == "win" else None
        meta = ensure_metadata_model(
            backend,
            spec.metadata or {},
            role=spec.role,
            specialization=spec.specialization,
            target_platform=win_target,
        )
        model_id = resolve_dispatch_model(
            backend,
            meta,
            role=spec.role,
            specialization=spec.specialization,
            target_platform=win_target,
        )
        check_affinity(model_id, plat)
        if meta != (spec.metadata or {}):
            return spec.model_copy(update={"metadata": meta})
        return spec

    @staticmethod
    def _backend_to_platform(backend_hint: str) -> str:
        h = backend_hint.lower()
        if "win" in h:
            return "win"
        return "mac"  # ollama, lmstudio-mac, codex (runs on Mac), gemini (cloud)

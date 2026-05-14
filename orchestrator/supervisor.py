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
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.hardware_policy import HardwareAffinityError, check_affinity


# ── Constants ─────────────────────────────────────────────────────────────────
MAX_DEPTH = 1       # Anthropic hard constraint: depth > 1 rejected
MAX_THREADS = 25    # Anthropic spec ceiling — 25 concurrent workers max
STATE_DIR = Path(".state")
JOBS_JSONL = STATE_DIR / "jobs.jsonl"


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
    """Append one JSON event line.  Thread-safe via Python GIL + append mode."""
    # Serialise JobStatus values to their string form
    serialisable = {
        k: (v.value if isinstance(v, JobStatus) else v)
        for k, v in event.items()
    }
    line = json.dumps({"ts": _now_iso(), "job_id": job_id, **serialisable}) + "\n"
    with jobs_file.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _load_events(jobs_file: Path) -> list[dict]:
    """Return all events from jobs.jsonl; empty list if the file is missing."""
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
        self._state_dir = Path(state_dir)
        self._jobs_file = self._state_dir / "jobs.jsonl"
        self._active: dict[str, asyncio.Task] = {}
        _ensure_state_dir(self._state_dir)

    # ── Public API ─────────────────────────────────────────────────────────────

    async def submit_job(self, spec: JobSpec) -> str:
        """Validate → persist QUEUED → fire async worker task → return job_id."""
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
        # Hardware affinity check BEFORE any LLM call (Anthropic Pattern 4)
        if spec.backend_hint and spec.backend_hint not in {"auto", "cloud", "freeform", "echo", None, ""}:
            platform = self._backend_to_platform(spec.backend_hint)
            # check_affinity raises HardwareAffinityError — fail-closed, no silent reroute
            check_affinity(spec.intent, platform)

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
        """Execute one worker task.  Writes final event before exiting."""
        self._append_event(spec.job_id, {"status": JobStatus.RUNNING})
        job_dir = self._state_dir / "jobs" / spec.job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        try:
            result = await self._dispatch(spec)
            # Write result artifact BEFORE persisting final state.
            # Critical ordering from Anthropic spec: write checkpoint then kill,
            # never kill then write (data loss on crash during termination).
            (job_dir / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._append_event(spec.job_id, {
                "status": JobStatus.SUCCEEDED,
                "artifact": str(job_dir / "result.json"),
            })

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

        except Exception as exc:
            self._append_event(spec.job_id, {
                "status": JobStatus.FAILED,
                "error": str(exc),
            })

        finally:
            self._active.pop(spec.job_id, None)

    async def _dispatch(self, spec: JobSpec) -> dict:
        """Route spec to the correct backend worker and return its result dict."""
        from orchestrator.worker_registry import WORKER_REGISTRY, resolve_backend
        backend = resolve_backend(spec)
        worker_fn = WORKER_REGISTRY.get(backend, WORKER_REGISTRY["echo"])
        return await worker_fn(spec)

    def _append_event(self, job_id: str, event: dict) -> None:
        _append_event(self._jobs_file, job_id, event)

    @staticmethod
    def _backend_to_platform(backend_hint: str) -> str:
        h = backend_hint.lower()
        if "win" in h:
            return "win"
        return "mac"  # ollama, lmstudio-mac, codex (runs on Mac), gemini (cloud)

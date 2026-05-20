"""orchestrator/contracts.py — Five shared Pydantic v2 types.

Owner: Perpetua-Tools (PT). orama-system imports from here — never the reverse.
Shared contract for PT ↔ orama inter-process messaging (JSON wire format).
XML/tags are prompt-rendering only; this is the Python boundary.

See: orama-system/docs/2026-05-14--UNIFIED-ABSORPTION-PLAN.md §§ 3–5
Lockstep: any schema change must commit to both repos in the same session.

Python 3.9 compat: use Optional[X] / Dict / List / Any from typing, not X | Y syntax.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Supporting value types ─────────────────────────────────────────────────────

class AuditEvent(BaseModel):
    """Single entry in an OrchestrationSession audit log. Append-only."""

    model_config = ConfigDict(frozen=True)

    ts: datetime
    event: str                          # e.g. "worker.dispatched", "verifier.approved"
    actor: str                          # orchestrator_id or worker job_id
    detail: Dict[str, Any] = {}


class ArtifactPolicy(BaseModel):
    """Governs how a worker may write artifacts."""

    model_config = ConfigDict(frozen=True)

    allow_disk_write: bool = True
    max_artifact_bytes: int = 10 * 1024 * 1024   # 10 MiB default
    allowed_extensions: List[str] = []            # empty = any
    base_dir: Optional[str] = None                # None = .state/jobs/<id>/


class ArtifactRef(BaseModel):
    """Reference to an artifact on disk — never the raw content."""

    model_config = ConfigDict(frozen=True)

    path: str                           # relative to .state/jobs/<id>/
    mime_type: str = "application/octet-stream"
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None        # optional integrity check


class TokenUsage(BaseModel):
    """Token accounting from one worker call."""

    model_config = ConfigDict(frozen=True)

    prompt: int = 0
    completion: int = 0
    total: int = 0


# ── § 3.1  OrchestrationSession (PT-owned, durable) ───────────────────────────

class OrchestrationSession(BaseModel):
    """Durable session record owned by PT. orama is stateless — it never writes this.

    audit_log is append-only: workers emit events; PT validates and stores them.
    checkpoint is a freeform snapshot for resumability (v2 checkpointer hook).
    """

    model_config = ConfigDict(protected_namespaces=())

    session_id: str = Field(..., description="uuid4, immutable once set")
    created_at: datetime
    orchestrator_id: str
    objective: str
    constraints: List[str] = []
    acceptance_criteria: List[str] = []
    status: Literal["pending", "running", "verifying", "done", "failed", "cancelled"] = "pending"
    checkpoint: Optional[Dict[str, Any]] = None
    audit_log: List[AuditEvent] = []    # append-only, never remove entries
    windows_coder_pool: List[str] = Field(
        default_factory=lambda: list(
            filter(None, os.environ.get("WIN_CODER_ENDPOINTS", "").split(","))
        ),
        description="LM Studio endpoints for Windows coders. Checked before Mac-local dispatch.",
    )


# ── § 3.2  TaskEnvelope (generic worker input — all roles receive this) ────────

class TaskEnvelope(BaseModel):
    """Input contract for every worker. Overlay role-specific data in `metadata`.

    Hard invariant: depth is always 0 in V1. Workers cannot spawn sub-workers.
    Enforced server-side — not a convention.
    """

    model_config = ConfigDict(protected_namespaces=())

    job_id: str                         # uuid4, set by PT dispatcher
    session_id: str
    parent_orchestrator_id: str
    role: str                           # "executor", "verifier", "crystallizer", …
    specialization: Optional[str] = None   # "python-coding", "m&a-research", …
    intent: str
    prompt: str
    constraints: List[str] = []
    artifact_policy: ArtifactPolicy = Field(default_factory=ArtifactPolicy)
    metadata: Dict[str, Any] = {}
    handoff_summary: Optional[str] = None  # condensed output from previous worker
    depth: int = Field(default=0, ge=0, le=0)

    @field_validator("depth", mode="before")
    @classmethod
    def no_sub_workers(cls, v: int) -> int:
        """Workers cannot spawn sub-workers in V1. depth must always be 0."""
        if int(v) != 0:
            raise ValueError(
                f"Workers cannot spawn sub-workers in V1. depth must be 0, got {v}."
            )
        return int(v)


# ── § 3.3  WorkerAssignment (orama plan → bridge input) ───────────────────────

class WorkerAssignment(BaseModel):
    """Produced by orama's orchestrator; consumed by OramaToPTBridge in PT.

    This is the planning-layer object. OramaToPTBridge converts it into
    a TaskEnvelope before dispatching to a worker backend.
    """

    model_config = ConfigDict(protected_namespaces=())

    role: str
    specialization: Optional[str] = None
    intent: str
    constraints: List[str] = []
    expected_output_shape: str
    verification_rubric: Optional[str] = None
    parallel_group: Optional[str] = None   # same group → concurrent via asyncio.gather


# ── § 3.4  WorkerResult (compact — no raw transcripts) ────────────────────────

class WorkerResult(BaseModel):
    """Written to .state/jobs/<id>/result.json BEFORE the success event is emitted.

    Hard rule: summary must never contain raw session transcripts or model internals.
    Only condensed, human-readable output belongs here (~500 tokens max).
    Artifact content stays on disk; only ArtifactRefs are included.
    """

    model_config = ConfigDict(protected_namespaces=())

    job_id: str
    role: str
    status: Literal["done", "failed", "needs_revision"]
    summary: str                            # ≤~500 tokens, no raw session logs
    artifacts: List[ArtifactRef] = []       # file paths, never raw content
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    errors: List[str] = []
    verification_hints: List[str] = []      # low-confidence signals for verifier


# ── § 3.5  VerificationResult (gate before crystallization) ───────────────────

class VerificationResult(BaseModel):
    """Returned by verifier-agent. Only "approved" unlocks crystallization.

    Verdicts:
        "approved"        → crystallization may proceed
        "needs_revision"  → back to executor (NEVER directly to crystallizer)
        "failed"          → halts session; MAESTRO gate fires in v2
    """

    model_config = ConfigDict(protected_namespaces=())

    job_id: str
    target_job_ids: List[str]
    verdict: Literal["approved", "needs_revision", "failed"]
    findings: List[str]
    revision_instructions: Optional[str] = None


# ── Public re-exports ──────────────────────────────────────────────────────────

__all__ = [
    "AuditEvent",
    "ArtifactPolicy",
    "ArtifactRef",
    "TokenUsage",
    "OrchestrationSession",
    "TaskEnvelope",
    "WorkerAssignment",
    "WorkerResult",
    "VerificationResult",
]

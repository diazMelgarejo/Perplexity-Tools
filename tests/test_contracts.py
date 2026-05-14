"""tests/test_contracts.py — Unit tests for orchestrator/contracts.py.

Covers: all 5 shared types, depth validator, Pydantic v2 compatibility,
AuditEvent append-only semantics, and supporting value types.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from orchestrator.contracts import (
    AuditEvent,
    ArtifactPolicy,
    ArtifactRef,
    TokenUsage,
    OrchestrationSession,
    TaskEnvelope,
    WorkerAssignment,
    WorkerResult,
    VerificationResult,
)


_NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)


# ── AuditEvent ────────────────────────────────────────────────────────────────

class TestAuditEvent:
    def test_basic_construction(self):
        ev = AuditEvent(ts=_NOW, event="worker.dispatched", actor="orch-1")
        assert ev.event == "worker.dispatched"
        assert ev.actor == "orch-1"
        assert ev.detail == {}

    def test_with_detail(self):
        ev = AuditEvent(ts=_NOW, event="verifier.approved", actor="verifier-j1",
                        detail={"job_id": "j1", "score": 0.9})
        assert ev.detail["job_id"] == "j1"

    def test_frozen(self):
        ev = AuditEvent(ts=_NOW, event="test", actor="x")
        with pytest.raises(Exception):
            ev.event = "mutated"  # type: ignore[misc]


# ── ArtifactPolicy ────────────────────────────────────────────────────────────

class TestArtifactPolicy:
    def test_defaults(self):
        p = ArtifactPolicy()
        assert p.allow_disk_write is True
        assert p.max_artifact_bytes == 10 * 1024 * 1024
        assert p.allowed_extensions == []
        assert p.base_dir is None

    def test_custom(self):
        p = ArtifactPolicy(allow_disk_write=False, max_artifact_bytes=1024,
                           allowed_extensions=[".py", ".json"], base_dir="/tmp/jobs")
        assert p.allow_disk_write is False
        assert p.base_dir == "/tmp/jobs"


# ── TokenUsage ────────────────────────────────────────────────────────────────

class TestTokenUsage:
    def test_defaults(self):
        t = TokenUsage()
        assert t.prompt == 0
        assert t.completion == 0
        assert t.total == 0

    def test_custom(self):
        t = TokenUsage(prompt=100, completion=200, total=300)
        assert t.total == 300


# ── OrchestrationSession ──────────────────────────────────────────────────────

class TestOrchestrationSession:
    def _make(self, **kwargs):
        defaults = dict(
            session_id="sess-001",
            created_at=_NOW,
            orchestrator_id="orch-1",
            objective="Analyze codebase",
        )
        defaults.update(kwargs)
        return OrchestrationSession(**defaults)

    def test_defaults(self):
        s = self._make()
        assert s.status == "pending"
        assert s.constraints == []
        assert s.acceptance_criteria == []
        assert s.audit_log == []
        assert s.checkpoint is None

    def test_valid_statuses(self):
        for status in ("pending", "running", "verifying", "done", "failed", "cancelled"):
            s = self._make(status=status)
            assert s.status == status

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            self._make(status="unknown_state")

    def test_with_audit_events(self):
        ev = AuditEvent(ts=_NOW, event="started", actor="orch-1")
        s = self._make(audit_log=[ev])
        assert len(s.audit_log) == 1
        assert s.audit_log[0].event == "started"


# ── TaskEnvelope ──────────────────────────────────────────────────────────────

class TestTaskEnvelope:
    def _make(self, **kwargs):
        defaults = dict(
            job_id="job-001",
            session_id="sess-001",
            parent_orchestrator_id="orch-1",
            role="executor",
            intent="write-code",
            prompt="Implement the feature",
        )
        defaults.update(kwargs)
        return TaskEnvelope(**defaults)

    def test_defaults(self):
        e = self._make()
        assert e.depth == 0
        assert e.constraints == []
        assert e.metadata == {}
        assert e.handoff_summary is None
        assert e.specialization is None

    def test_depth_zero_accepted(self):
        e = self._make(depth=0)
        assert e.depth == 0

    def test_depth_one_raises(self):
        """Core V1 invariant: workers cannot spawn sub-workers."""
        with pytest.raises(ValidationError) as exc_info:
            self._make(depth=1)
        assert "sub-workers" in str(exc_info.value).lower()

    def test_depth_negative_raises(self):
        with pytest.raises(ValidationError):
            self._make(depth=-1)

    def test_depth_string_zero_coerces(self):
        """field_validator mode='before' coerces string '0' to int 0."""
        e = self._make(depth="0")
        assert e.depth == 0

    def test_depth_string_one_raises(self):
        with pytest.raises(ValidationError):
            self._make(depth="1")

    def test_full_envelope(self):
        policy = ArtifactPolicy(base_dir=".state/jobs/j1")
        e = self._make(
            role="verifier",
            specialization="python-coding",
            constraints=["max_tokens:4096"],
            artifact_policy=policy,
            metadata={"rubric": "no_imports"},
            handoff_summary="executor produced tests",
        )
        assert e.role == "verifier"
        assert e.specialization == "python-coding"
        assert e.artifact_policy.base_dir == ".state/jobs/j1"


# ── WorkerAssignment ──────────────────────────────────────────────────────────

class TestWorkerAssignment:
    def test_basic(self):
        wa = WorkerAssignment(
            role="executor",
            intent="write-tests",
            expected_output_shape="pytest file",
        )
        assert wa.parallel_group is None
        assert wa.verification_rubric is None

    def test_parallel_group(self):
        wa1 = WorkerAssignment(role="context", intent="research",
                               expected_output_shape="summary", parallel_group="pg-1")
        wa2 = WorkerAssignment(role="architect", intent="design",
                               expected_output_shape="adr", parallel_group="pg-1")
        assert wa1.parallel_group == wa2.parallel_group


# ── WorkerResult ──────────────────────────────────────────────────────────────

class TestWorkerResult:
    def _make(self, **kwargs):
        defaults = dict(job_id="j1", role="executor", status="done", summary="Done.")
        defaults.update(kwargs)
        return WorkerResult(**defaults)

    def test_defaults(self):
        r = self._make()
        assert r.artifacts == []
        assert r.errors == []
        assert r.verification_hints == []
        assert r.tokens.total == 0

    def test_valid_statuses(self):
        for s in ("done", "failed", "needs_revision"):
            r = self._make(status=s)
            assert r.status == s

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            self._make(status="unknown")

    def test_with_artifacts(self):
        ar = ArtifactRef(path="output.py", mime_type="text/x-python", size_bytes=1024)
        r = self._make(artifacts=[ar])
        assert r.artifacts[0].path == "output.py"

    def test_with_tokens(self):
        r = self._make(tokens=TokenUsage(prompt=50, completion=200, total=250))
        assert r.tokens.total == 250


# ── VerificationResult ────────────────────────────────────────────────────────

class TestVerificationResult:
    def _make(self, verdict: str = "approved", **kwargs):
        defaults = dict(
            job_id="j-verif",
            target_job_ids=["j-exec-1"],
            verdict=verdict,
            findings=["All tests pass"],
        )
        defaults.update(kwargs)
        return VerificationResult(**defaults)

    def test_approved(self):
        vr = self._make("approved")
        assert vr.verdict == "approved"
        assert vr.revision_instructions is None

    def test_needs_revision(self):
        vr = self._make("needs_revision",
                        findings=["Missing edge case"],
                        revision_instructions="Add test for empty input")
        assert vr.verdict == "needs_revision"
        assert "empty input" in vr.revision_instructions

    def test_failed(self):
        vr = self._make("failed", findings=["Security violation"])
        assert vr.verdict == "failed"

    def test_invalid_verdict_raises(self):
        with pytest.raises(ValidationError):
            self._make("partially_approved")

    def test_multiple_target_jobs(self):
        vr = self._make(target_job_ids=["j1", "j2", "j3"])
        assert len(vr.target_job_ids) == 3

    def test_verifier_gate_pattern(self):
        """Confirm the verdict=='approved' string check works as the gate uses it."""
        approved = self._make("approved")
        needs_rev = self._make("needs_revision")
        failed = self._make("failed")
        assert approved.verdict == "approved"
        assert needs_rev.verdict != "approved"
        assert failed.verdict != "approved"


# ── Cross-type integration ────────────────────────────────────────────────────

class TestCrossType:
    def test_pydantic_v2_field_validator_not_validator(self):
        """Ensure @field_validator (v2) is used, not @validator (v1 compat shim)."""
        import inspect
        from orchestrator import contracts
        src = inspect.getsource(contracts)
        assert "@field_validator" in src
        assert "@validator" not in src.replace("@field_validator", "")

    def test_all_exports_importable(self):
        from orchestrator.contracts import __all__
        import orchestrator.contracts as mod
        for name in __all__:
            assert hasattr(mod, name), f"Missing export: {name}"

"""tests/test_job_spec.py — Tests for JobSpec extended worker fields.

Verifies that the new role/specialization/session_id/depth fields added
in § 5.1 of the unified absorption plan are backward-compatible:
  - Old call sites that pass only intent/backend_hint/constraints still work.
  - New fields default correctly and are validated.
  - depth=0 validator fires on JobSpec too.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

# JobSpec lives in the supervisor module
from orchestrator.supervisor import JobSpec  # type: ignore[import]


class TestJobSpecBackwardCompat:
    """Old call sites must continue to pass unchanged."""

    def test_minimal_old_style(self):
        """Old-style: intent only."""
        spec = JobSpec(intent="research")
        assert spec.intent == "research"
        assert spec.role is None
        assert spec.specialization is None
        assert spec.depth == 0

    def test_with_backend_hint(self):
        spec = JobSpec(intent="code-review", backend_hint="codex")
        assert spec.backend_hint == "codex"

    def test_with_constraints_list(self):
        spec = JobSpec(intent="analyze", constraints=["max_tokens:2048"])
        assert spec.constraints == ["max_tokens:2048"]

    def test_with_metadata(self):
        spec = JobSpec(intent="research", metadata={"query": "Q3 results"})
        assert spec.metadata["query"] == "Q3 results"


class TestJobSpecNewWorkerFields:
    """New fields added for worker roles must work correctly."""

    def test_role_field(self):
        spec = JobSpec(intent="write-code", role="executor-agent")
        assert spec.role == "executor-agent"

    def test_specialization_field(self):
        spec = JobSpec(intent="write-code", role="executor-agent",
                       specialization="python-coding")
        assert spec.specialization == "python-coding"

    def test_artifact_policy_field(self):
        spec = JobSpec(intent="analyze", artifact_policy="default")
        assert spec.artifact_policy == "default"

    def test_session_id_field(self):
        spec = JobSpec(intent="research", session_id="sess-abc123")
        assert spec.session_id == "sess-abc123"

    def test_parent_orchestrator_id_field(self):
        spec = JobSpec(intent="crystallize", parent_orchestrator_id="orch-1")
        assert spec.parent_orchestrator_id == "orch-1"


class TestJobSpecDepthValidator:
    """depth=0 must be validated at the JobSpec level too."""

    def test_depth_zero_accepted(self):
        spec = JobSpec(intent="echo", depth=0)
        assert spec.depth == 0

    def test_depth_one_raises(self):
        """V1 invariant: workers do not spawn sub-workers."""
        with pytest.raises((ValidationError, ValueError)):
            JobSpec(intent="echo", depth=1)

    def test_depth_default_is_zero(self):
        spec = JobSpec(intent="echo")
        assert spec.depth == 0


class TestJobSpecFullWorkerPayload:
    """Full new-style payload round-trips correctly."""

    def test_full_payload(self):
        spec = JobSpec(
            intent="write-tests",
            role="executor-agent",
            specialization="test-writing",
            backend_hint="lmstudio-win",
            constraints=["max_tokens:4096", "no_external_api_without_approval"],
            metadata={"model": "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"},
            artifact_policy="default",
            session_id="sess-xyz",
            parent_orchestrator_id="orch-main",
            depth=0,
        )
        assert spec.role == "executor-agent"
        assert spec.depth == 0
        assert "no_external_api_without_approval" in spec.constraints

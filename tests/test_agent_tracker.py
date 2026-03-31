"""test_agent_tracker.py — Unit tests for orchestrator/agent_tracker.py

Tests AgentTracker lifecycle: register, update_status, find_existing,
detect_conflicts, destroy, destroy_stopped.
Runs offline — no Ollama, no network, no external state required.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root is on PYTHONPATH
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.agent_tracker import AgentRecord, AgentTracker


@pytest.fixture
def tracker(tmp_path):
    """Fresh in-memory AgentTracker backed by a temp dir."""
    t = AgentTracker(state_dir=str(tmp_path / ".state"))
    return t


def _register(tracker: AgentTracker, role: str = "coder", task_hash: str = "abc123") -> AgentRecord:
    return tracker.register(
        role=role,
        model="qwen3:8b",
        backend="ollama",
        host="localhost",
        port=11434,
        task_hash=task_hash,
    )


class TestRegister:
    def test_register_returns_agent_record(self, tracker):
        agent = _register(tracker)
        assert isinstance(agent, AgentRecord)
        assert agent.role == "coder"
        assert agent.status == "starting"
        assert agent.agent_id  # non-empty UUID

    def test_register_persists_to_disk(self, tracker):
        agent = _register(tracker)
        # Reload from disk
        tracker2 = AgentTracker(state_dir=str(tracker.state_dir))
        found = tracker2.find_existing("coder")
        assert found is not None
        assert found.agent_id == agent.agent_id

    def test_register_multiple_agents(self, tracker):
        a1 = _register(tracker, role="coder")
        a2 = _register(tracker, role="evaluator")
        agents = tracker.list_agents()
        assert len(agents) == 2
        ids = {a.agent_id for a in agents}
        assert a1.agent_id in ids
        assert a2.agent_id in ids

    def test_register_allows_custom_initial_status(self, tracker):
        agent = tracker.register(
            role="coder",
            model="qwen3:8b",
            backend="ollama",
            host="localhost",
            port=11434,
            status="idle",
        )

        assert agent.status == "idle"


class TestUpdateStatus:
    def test_update_status_changes_field(self, tracker):
        agent = _register(tracker)
        updated = tracker.update_status(agent.agent_id, "running")
        assert updated is not None
        assert updated.status == "running"

    def test_update_status_nonexistent_returns_none(self, tracker):
        result = tracker.update_status("nonexistent-id", "running")
        assert result is None

    def test_update_status_to_stopped(self, tracker):
        agent = _register(tracker)
        tracker.update_status(agent.agent_id, "stopped")
        stopped = tracker.list_agents(status="stopped")
        assert any(a.agent_id == agent.agent_id for a in stopped)


class TestFindExisting:
    def test_find_existing_starting_agent(self, tracker):
        agent = _register(tracker, role="coder")
        found = tracker.find_existing("coder")
        assert found is not None
        assert found.agent_id == agent.agent_id

    def test_find_existing_running_agent(self, tracker):
        agent = _register(tracker, role="coder")
        tracker.update_status(agent.agent_id, "running")
        found = tracker.find_existing("coder")
        assert found is not None

    def test_find_existing_stopped_agent_returns_none(self, tracker):
        agent = _register(tracker, role="coder")
        tracker.update_status(agent.agent_id, "stopped")
        found = tracker.find_existing("coder")
        assert found is None

    def test_find_existing_wrong_role_returns_none(self, tracker):
        _register(tracker, role="coder")
        found = tracker.find_existing("evaluator")
        assert found is None

    def test_find_existing_with_task_hash_match(self, tracker):
        agent = _register(tracker, role="coder", task_hash="xyz")
        found = tracker.find_existing("coder", task_hash="xyz")
        assert found is not None
        assert found.agent_id == agent.agent_id

    def test_find_existing_with_task_hash_mismatch(self, tracker):
        _register(tracker, role="coder", task_hash="xyz")
        found = tracker.find_existing("coder", task_hash="other")
        assert found is None


class TestDetectConflicts:
    def test_no_conflicts_single_role(self, tracker):
        agent = _register(tracker, role="coder")
        tracker.update_status(agent.agent_id, "running")
        assert tracker.detect_conflicts() == []

    def test_detect_duplicate_role_conflict(self, tracker):
        a1 = _register(tracker, role="coder", task_hash="t1")
        a2 = _register(tracker, role="coder", task_hash="t2")
        tracker.update_status(a1.agent_id, "running")
        tracker.update_status(a2.agent_id, "running")
        conflicts = tracker.detect_conflicts()
        conflict_ids = {c.agent_id for c in conflicts}
        assert a1.agent_id in conflict_ids
        assert a2.agent_id in conflict_ids


class TestDestroy:
    def test_destroy_existing_agent(self, tracker):
        agent = _register(tracker)
        result = tracker.destroy(agent.agent_id)
        assert result is True
        assert tracker.find_existing("coder") is None

    def test_destroy_nonexistent_returns_false(self, tracker):
        result = tracker.destroy("does-not-exist")
        assert result is False


class TestDestroyStopped:
    def test_destroy_stopped_removes_only_terminal(self, tracker):
        running = _register(tracker, role="coder", task_hash="r")
        stopped = _register(tracker, role="evaluator", task_hash="s")
        error = _register(tracker, role="orchestrator", task_hash="e")
        tracker.update_status(running.agent_id, "running")
        tracker.update_status(stopped.agent_id, "stopped")
        tracker.update_status(error.agent_id, "error")
        removed = tracker.destroy_stopped()
        assert removed == 2
        remaining = tracker.list_agents()
        assert len(remaining) == 1
        assert remaining[0].agent_id == running.agent_id

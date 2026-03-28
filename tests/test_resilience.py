from __future__ import annotations

from pathlib import Path


def test_cost_guard_falls_back_to_memory(monkeypatch, tmp_path):
    from orchestrator.cost_guard import CostGuard

    def raise_permission_error(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "write_text", raise_permission_error)
    guard = CostGuard(state_dir=str(tmp_path))

    snapshot = guard.snapshot()

    assert snapshot["daily_budget"] == 25.0
    assert snapshot["daily_spend"] == 0.0
    assert snapshot["remaining"] == 25.0


def test_agent_tracker_falls_back_to_memory(monkeypatch, tmp_path):
    from orchestrator.agent_tracker import AgentTracker

    def raise_permission_error(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "write_text", raise_permission_error)
    tracker = AgentTracker(state_dir=str(tmp_path))

    record = tracker.register(
        role="orchestrator",
        model="test-model",
        backend="local",
        host="127.0.0.1",
        port=8000,
    )

    assert tracker.list_agents()[0].agent_id == record.agent_id
    assert tracker.find_existing("orchestrator", task_hash=None).agent_id == record.agent_id


def test_sync_returns_structured_error_when_vendor_clone_unavailable(monkeypatch):
    import orchestrator.ecc_tools_sync as sync_mod

    monkeypatch.setattr(sync_mod, "_ensure_cloned", lambda: False)

    result = sync_mod.sync_ecc_tools(force=False)

    assert result["status"] == "error"
    assert "vendor clone unavailable" in result["message"]

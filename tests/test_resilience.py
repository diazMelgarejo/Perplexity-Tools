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



# ---------------------------------------------------------------------------
# Regression tests for bugs fixed in orchestrator.py (v0.9.7.0 hardening)
# ---------------------------------------------------------------------------

def test_call_ultrathink_appends_ultrathink_path(monkeypatch):
    """Bug fix: call_ultrathink must POST to <base>/ultrathink, not bare base URL.

    Before the fix: session.post(ULTRATHINK_ENDPOINT, ...)
    After the fix:  session.post(ULTRATHINK_ENDPOINT.rstrip('/') + '/ultrathink', ...)
    """
    import asyncio
    import sys
    import types

    captured_urls = []

    class _FakeResp:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def json(self):
            return {"result": "ok"}

    class _FakeSession:
        def post(self, url, **kwargs):
            captured_urls.append(url)
            return _FakeResp()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass

    # Patch aiohttp.ClientSession inside orchestrator module
    import orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "ULTRATHINK_ENDPOINT", "http://localhost:8001")
    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", _FakeSession)

    asyncio.run(orch_mod.call_ultrathink("test task"))

    assert len(captured_urls) == 1, "Expected exactly one POST"
    assert captured_urls[0] == "http://localhost:8001/ultrathink", (
        f"Expected /ultrathink suffix, got: {captured_urls[0]}"
    )


def test_orchestrate_returns_empty_string_when_all_backends_fail(monkeypatch):
    """Bug fix: result=None must be coerced to '' before building OrchestrationResponse.

    Before the fix: Pydantic raises ValidationError because result:str got None.
    After the fix:  status='success', result='' returned cleanly.
    """
    import asyncio
    import orchestrator as orch_mod

    # Make every backend return None
    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(orch_mod, "call_perplexity", _none)
    monkeypatch.setattr(orch_mod, "call_ollama", _none)
    monkeypatch.setattr(orch_mod, "call_ultrathink", _none)

    # Stub Redis so check_budget / spend reads don't hit a real server
    class _FakeRedis:
        async def get(self, *a): return None
        async def incr(self, *a): pass
        async def incrbyfloat(self, *a): pass
        async def keys(self, *a): return []
        async def setex(self, *a): pass

    monkeypatch.setattr(orch_mod, "r", _FakeRedis())

    from orchestrator import OrchestrationRequest
    req = OrchestrationRequest(
        task_description="test",
        is_finance_realtime=False,
        privacy_critical=False,
        enable_critic=False,
    )
    resp = asyncio.run(orch_mod.orchestrate(req))

    assert resp.result == "", f"Expected empty string, got: {resp.result!r}"
    assert resp.status == "success"
    assert any("All backends failed" in msg for msg in resp.routing_log)

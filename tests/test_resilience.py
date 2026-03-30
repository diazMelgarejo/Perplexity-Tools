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

    monkeypatch.setattr(sync_mod, "ECC_SYNC_ENABLED", True)
    monkeypatch.setattr(sync_mod, "_ensure_cloned", lambda: False)
    result = sync_mod.sync_ecc_tools(force=False)

    assert result["status"] == "error"
    assert "vendor clone unavailable" in result["message"]


# ---------------------------------------------------------------------------
# Regression tests for bugs fixed in orchestrator.py (v0.9.7.0 hardening)
#
# NOTE: 'orchestrator' resolves to the orchestrator/ *package* on the sys.path,
# not the top-level orchestrator.py module. Load the .py file explicitly via
# importlib so monkeypatching targets the right module object.
# ---------------------------------------------------------------------------

def _load_orchestrator_module():
    """Load the top-level orchestrator.py by absolute path, bypassing the
    orchestrator/ package that shadows it on sys.path."""
    import importlib.util
    import sys
    from pathlib import Path as _Path

    py_file = _Path(__file__).parent.parent / "orchestrator.py"
    spec = importlib.util.spec_from_file_location("orchestrator_module", py_file)
    mod = importlib.util.module_from_spec(spec)
    # Register under a unique name so re-use within a session is consistent
    sys.modules.setdefault("orchestrator_module", mod)
    spec.loader.exec_module(mod)
    return mod


def test_call_ultrathink_appends_ultrathink_path(monkeypatch):
    """Bug fix: call_ultrathink must POST to /ultrathink, not bare base URL.

    Before the fix: session.post(ULTRATHINK_ENDPOINT, ...)
    After the fix:  session.post(ULTRATHINK_ENDPOINT.rstrip('/') + '/ultrathink', ...)
    """
    import asyncio
    import aiohttp

    orch_mod = _load_orchestrator_module()
    captured_urls = []

    class _FakeResp:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def json(self): return {"result": "ok"}

    class _FakeSession:
        def post(self, url, **kwargs):
            captured_urls.append(url)
            return _FakeResp()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    monkeypatch.setattr(orch_mod, "ULTRATHINK_ENDPOINT", "http://localhost:8001")
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

    fix(tests): slowapi's @limiter.limit decorator does a strict isinstance check
    against starlette.requests.Request — a plain mock object won't pass.
    Call the unwrapped handler via __wrapped__ to bypass the rate-limit layer
    entirely. The `request` param is only consumed by the decorator; the
    function body never references it, so passing None is safe.
    """
    import asyncio

    orch_mod = _load_orchestrator_module()

    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(orch_mod, "call_perplexity", _none)
    monkeypatch.setattr(orch_mod, "call_ollama", _none)
    monkeypatch.setattr(orch_mod, "call_ultrathink", _none)

    class _FakeRedis:
        async def get(self, *a): return None
        async def incr(self, *a): pass
        async def incrbyfloat(self, *a): pass
        async def keys(self, *a): return []
        async def setex(self, *a): pass

    monkeypatch.setattr(orch_mod, "r", _FakeRedis())

    req = orch_mod.OrchestrationRequest(
        task_description="test",
        is_finance_realtime=False,
        privacy_critical=False,
        enable_critic=False,
    )
    # fix(tests): call __wrapped__ to skip slowapi's isinstance(request, Request)
    # check. The decorator is only needed for live HTTP traffic; unit tests
    # exercise the handler logic directly.
    handler = getattr(orch_mod.orchestrate, "__wrapped__", orch_mod.orchestrate)
    resp = asyncio.run(handler(req, None))

    assert resp.result == "", f"Expected empty string, got: {resp.result!r}"
    assert resp.status == "success"
    assert any("All backends failed" in msg for msg in resp.routing_log)


def test_orchestrator_starts_without_redis_package(monkeypatch):
    """redis package absent (ImportError) must not prevent orchestrator from loading.

    Simulates an environment where redis is not installed at all by setting
    _redis_mod to None before the connection block runs.
    The handler must still return a valid response (r=None path).
    """
    import asyncio

    orch_mod = _load_orchestrator_module()

    # Simulate redis package absent: _redis_mod=None forces r=None
    monkeypatch.setattr(orch_mod, "_redis_mod", None)
    monkeypatch.setattr(orch_mod, "r", None)

    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(orch_mod, "call_perplexity", _none)
    monkeypatch.setattr(orch_mod, "call_ollama", _none)
    monkeypatch.setattr(orch_mod, "call_ultrathink", _none)

    req = orch_mod.OrchestrationRequest(
        task_description="redis-absent test",
        is_finance_realtime=False,
        privacy_critical=False,
        enable_critic=False,
    )
    handler = getattr(orch_mod.orchestrate, "__wrapped__", orch_mod.orchestrate)
    resp = asyncio.run(handler(req, None))

    # Must succeed gracefully without Redis
    assert resp.status == "success"
    assert resp.result == ""

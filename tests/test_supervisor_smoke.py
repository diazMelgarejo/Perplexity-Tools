"""Mac-only smoke tests for OrchestrationSupervisor V1 (file-based persistence).

Acceptance: ``pytest -k supervisor_smoke`` → green on Mac with no Windows box reachable.
No live LLM calls — echo backend only.  All tests use a tmp_path fixture so the
real .state/ directory is never touched.

Reference: orama-system/docs/2026-05-08-v1-supervisor-brainstorm.md §6 step 6
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from orchestrator.supervisor import (
    JobSpec,
    JobStatus,
    OrchestrationSupervisor,
    _append_event,
    _load_events,
    _latest_status_per_job,
    _new_id,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _echo_spec(prompt: str = "hello") -> JobSpec:
    return JobSpec(
        job_id=_new_id(),
        intent="echo",
        prompt=prompt,
        backend_hint="echo",
    )


def _make_sup(tmp_path: Path) -> OrchestrationSupervisor:
    return OrchestrationSupervisor(state_dir=tmp_path)


# ── Basic lifecycle ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_echo_job_succeeds(tmp_path):
    """submit_job() fires worker; job reaches SUCCEEDED."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("hello supervisor")
    job_id = await sup.submit_job(spec)
    assert job_id == spec.job_id

    await asyncio.sleep(0.2)

    status = await sup.get_status(job_id)
    assert status is not None
    assert status["status"] == JobStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_artifact_file_written(tmp_path):
    """result.json is written under .state/jobs/<id>/."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("artifact test")
    job_id = await sup.submit_job(spec)
    await asyncio.sleep(0.2)

    result_path = tmp_path / "jobs" / job_id / "result.json"
    assert result_path.exists(), f"Expected artifact at {result_path}"
    data = json.loads(result_path.read_text())
    assert data["backend"] == "echo"
    assert "artifact test" in data["output"]


@pytest.mark.asyncio
async def test_status_has_artifact_key(tmp_path):
    """get_status() returns artifact path after job succeeds."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("status artifact")
    job_id = await sup.submit_job(spec)
    await asyncio.sleep(0.2)

    status = await sup.get_status(job_id)
    assert status["artifact"] is not None
    assert "result.json" in status["artifact"]


# ── Event log ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_jobs_jsonl_event_log(tmp_path):
    """All three mandatory transitions appear in jobs.jsonl."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec()
    await sup.submit_job(spec)
    await asyncio.sleep(0.2)

    events = _load_events(tmp_path / "jobs.jsonl")
    job_events = [e for e in events if e.get("job_id") == spec.job_id]
    statuses = {e["status"] for e in job_events}

    assert JobStatus.QUEUED.value in statuses
    assert JobStatus.RUNNING.value in statuses
    assert JobStatus.SUCCEEDED.value in statuses


def test_load_events_missing_file(tmp_path):
    """_load_events() returns [] when jobs.jsonl does not exist."""
    missing = tmp_path / "nonexistent.jsonl"
    assert _load_events(missing) == []


def test_append_event_creates_file(tmp_path):
    """_append_event() creates jobs.jsonl if it does not exist."""
    jobs_file = tmp_path / "jobs.jsonl"
    assert not jobs_file.exists()
    _append_event(jobs_file, "test-id", {"status": "queued"})
    assert jobs_file.exists()
    events = _load_events(jobs_file)
    assert len(events) == 1
    assert events[0]["status"] == "queued"


def test_latest_status_per_job_last_wins(tmp_path):
    """_latest_status_per_job() returns the last event for each job_id."""
    jobs_file = tmp_path / "jobs.jsonl"
    _append_event(jobs_file, "j1", {"status": "queued"})
    _append_event(jobs_file, "j1", {"status": "running"})
    _append_event(jobs_file, "j1", {"status": "succeeded"})
    _append_event(jobs_file, "j2", {"status": "queued"})

    events = _load_events(jobs_file)
    states = _latest_status_per_job(events)
    assert states["j1"]["status"] == "succeeded"
    assert states["j2"]["status"] == "queued"


# ── Guard rails ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_depth_limit_enforced(tmp_path):
    """depth != 0 is rejected at JobSpec construction (V1 invariant: workers never
    spawn sub-workers).  ValidationError or ValueError raised at model creation time,
    NOT at submit_job time — the Pydantic @field_validator catches it first."""
    from pydantic import ValidationError
    with pytest.raises((ValidationError, ValueError)):
        JobSpec(
            job_id=_new_id(),
            intent="echo",
            prompt="nested",
            backend_hint="echo",
            depth=1,  # depth=0 is the only valid value in V1
        )


@pytest.mark.asyncio
async def test_cancel_running_job(tmp_path):
    """cancel() returns True and job reaches CANCELLED state."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("slow")

    async def _slow(s):
        await asyncio.sleep(60)
        return {"output": "never"}

    sup._dispatch = _slow
    job_id = await sup.submit_job(spec)
    await asyncio.sleep(0.05)  # let task start

    cancelled = await sup.cancel(job_id)
    assert cancelled is True
    await asyncio.sleep(0.1)

    status = await sup.get_status(job_id)
    assert status["status"] == JobStatus.CANCELLED.value


# ── Replay ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_creates_new_job(tmp_path):
    """replay() creates a new job_id; new job reaches SUCCEEDED."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("replay me")
    original_id = await sup.submit_job(spec)
    await asyncio.sleep(0.2)

    # Inject a FAILED event so replay is valid (replay works on any terminal state)
    _append_event(
        tmp_path / "jobs.jsonl",
        original_id,
        {"status": JobStatus.FAILED.value, "spec": spec.to_dict(), "error": "injected"},
    )

    new_id = await sup.replay(original_id)
    assert new_id != original_id
    await asyncio.sleep(0.2)

    new_status = await sup.get_status(new_id)
    assert new_status["status"] == JobStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_replay_unknown_job_raises(tmp_path):
    """replay() raises ValueError for an unknown job_id."""
    sup = _make_sup(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        await sup.replay("no-such-id")


# ── list_jobs ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_jobs_filtered_by_status(tmp_path):
    """list_jobs(SUCCEEDED) returns only succeeded jobs."""
    sup = _make_sup(tmp_path)
    s1 = _echo_spec("job one")
    s2 = _echo_spec("job two")
    await sup.submit_job(s1)
    await sup.submit_job(s2)
    await asyncio.sleep(0.3)

    succeeded = sup.list_jobs(status=JobStatus.SUCCEEDED)
    ids = {j["job_id"] for j in succeeded}
    assert s1.job_id in ids
    assert s2.job_id in ids


@pytest.mark.asyncio
async def test_list_jobs_no_filter(tmp_path):
    """list_jobs() with no filter returns all jobs."""
    sup = _make_sup(tmp_path)
    s1 = _echo_spec("a")
    s2 = _echo_spec("b")
    await sup.submit_job(s1)
    await sup.submit_job(s2)
    await asyncio.sleep(0.3)

    all_jobs = sup.list_jobs()
    ids = {j["job_id"] for j in all_jobs}
    assert s1.job_id in ids
    assert s2.job_id in ids


# ── Windows coder pool dispatch ───────────────────────────────────────────────
# _get_reachable_windows_coder is now async (uses httpx.AsyncClient).
# Tests mock the method directly instead of patching the sync connectivity helper.

@pytest.mark.asyncio
async def test_dispatch_prefers_windows_coder_when_reachable(tmp_path, monkeypatch):
    """When a Windows coder endpoint is reachable, _dispatch routes to it before Mac-local."""
    from unittest.mock import AsyncMock
    import orchestrator.worker_registry as reg_mod

    async def fake_win_worker(spec):
        # Verify the dispatcher injects the pre-probed endpoint into metadata.
        assert spec.metadata.get("_win_endpoint") == "http://192.168.254.103:1234"
        return {"backend": "lmstudio-win", "output": "fake win result"}

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value="http://192.168.254.103:1234"),
    )
    monkeypatch.setitem(reg_mod.WORKER_REGISTRY, "lmstudio-win", fake_win_worker)

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="code review",
        prompt="review this file",
        backend_hint="lmstudio-mac",
    )
    result = await sup._dispatch(spec)
    assert result.get("routed_to_windows") is True, (
        f"Expected Windows coder routing but got: {result}"
    )
    assert result.get("windows_endpoint") == "http://192.168.254.103:1234"


@pytest.mark.asyncio
async def test_submit_then_win_preempt_uses_windows_model_not_mac_default(
    tmp_path, monkeypatch,
):
    """submit_job affinity must not pin Mac metadata before Windows preemption.

    Injecting metadata.model at QUEUED time left the Windows coder pool posting
    Qwen3.5-9B-MLX-4bit instead of the Windows coder default.
    """
    from unittest.mock import AsyncMock

    import orchestrator.worker_registry as reg_mod
    from utils.dispatch_models import lmstudio_win_default_model, mac_lmstudio_default_model

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value="http://192.168.254.103:1234"),
    )
    captured: dict[str, str] = {}

    async def fake_win_worker(spec):
        captured["model"] = (spec.metadata or {}).get("model", "")
        return {"backend": "lmstudio-win", "output": "ok"}

    monkeypatch.setitem(reg_mod.WORKER_REGISTRY, "lmstudio-win", fake_win_worker)

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="code review",
        prompt="review",
        backend_hint="lmstudio-mac",
        metadata={},
    )
    await sup.submit_job(spec)
    assert (spec.metadata or {}).get("model") in (None, ""), (
        "submit_job must not inject Mac model before dispatch"
    )

    await sup._active[spec.job_id]
    assert captured["model"] == lmstudio_win_default_model()
    assert captured["model"] != mac_lmstudio_default_model()


@pytest.mark.asyncio
async def test_dispatch_injects_win_endpoint_for_explicit_lmstudio_win(tmp_path, monkeypatch):
    """Explicit lmstudio-win routes (via role map / backend_hint) get _win_endpoint
    injected from WIN_CODER_ENDPOINTS, not just Mac-local preemption routes.

    This guards against the regression where environments that only set
    WIN_CODER_ENDPOINTS (not LM_STUDIO_WIN_ENDPOINTS) would fail on explicit
    Windows routes because _get_reachable_windows_coder() was never called.
    """
    from unittest.mock import AsyncMock
    import orchestrator.worker_registry as reg_mod

    endpoint_injected = {}

    async def fake_win_worker(spec):
        endpoint_injected["value"] = spec.metadata.get("_win_endpoint")
        return {"backend": "lmstudio-win", "output": "explicit win result"}

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value="http://192.168.254.101:1234"),
    )
    monkeypatch.setitem(reg_mod.WORKER_REGISTRY, "lmstudio-win", fake_win_worker)

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="code review",
        prompt="review this file",
        backend_hint="lmstudio-win",  # explicit Windows route — NOT Mac-local
    )
    result = await sup._dispatch(spec)

    # Explicit lmstudio-win does NOT set routed_to_windows (no preemption occurred)
    assert result.get("routed_to_windows") is not True, (
        "Explicit lmstudio-win should not set routed_to_windows flag"
    )
    # But _win_endpoint MUST be injected so the worker skips LM_STUDIO_WIN_ENDPOINTS
    assert endpoint_injected.get("value") == "http://192.168.254.101:1234", (
        f"_win_endpoint was not injected; got: {endpoint_injected}"
    )


@pytest.mark.asyncio
async def test_dispatch_skips_windows_coder_when_unreachable(tmp_path, monkeypatch):
    """When Windows coder is unreachable, _dispatch falls through to normal routing."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value=None),
    )

    sup = _make_sup(tmp_path)
    spec = _echo_spec("fallthrough test")
    result = await sup._dispatch(spec)
    assert result.get("routed_to_windows") is not True
    assert "echo" in str(result).lower() or result.get("status") == "ok"


@pytest.mark.asyncio
async def test_dispatch_skips_windows_coder_when_pool_empty(tmp_path, monkeypatch):
    """When WIN_CODER_ENDPOINTS is empty, _get_reachable_windows_coder returns None."""
    monkeypatch.setenv("WIN_CODER_ENDPOINTS", "")

    sup = _make_sup(tmp_path)
    # Call the method directly to confirm it returns None for empty pool.
    result = await OrchestrationSupervisor._get_reachable_windows_coder()
    assert result is None

    # Also confirm _dispatch falls through to normal routing.
    spec = _echo_spec("empty pool test")
    dispatch_result = await sup._dispatch(spec)
    assert dispatch_result.get("routed_to_windows") is not True


# ── _try_skill_envelope dispatch gate ─────────────────────────────────────────

def test_try_skill_envelope_raises_for_missing_skill_tree():
    """Mapped task_type with missing openclaw-skills tree raises RuntimeError (fail-closed).

    _DEFAULT_OPENCLAW_SKILLS_ROOT is computed at module import time, so patching
    ORAMA_SYSTEM_ROOT after import has no effect.  Instead we patch
    _find_skills_root directly to raise SkillResolutionError as it would on a
    fresh machine where the submodule is not yet checked out.
    """
    from unittest.mock import patch
    from orchestrator.openclaw_skill_resolver import SkillResolutionError
    spec = JobSpec(
        job_id=_new_id(),
        intent="add channel",
        prompt="add webhook",
        backend_hint="echo",
        task_type="add_channel",
    )

    def _raise_resolution_error():
        raise SkillResolutionError(
            "openclaw-skills folder not found (injected for test)"
        )

    with patch(
        "orchestrator.openclaw_skill_resolver._find_skills_root",
        side_effect=_raise_resolution_error,
    ):
        with pytest.raises(RuntimeError, match="Skill routing failed"):
            OrchestrationSupervisor._try_skill_envelope(spec)


def test_get_constraint_safe_with_list_constraints():
    """_get_constraint must not raise AttributeError when constraints is a list of tags."""
    from orchestrator.worker_registry import _get_constraint

    class _FakeSpec:
        constraints = ["gpu-required", "no-streaming"]

    assert _get_constraint(_FakeSpec(), "max_seconds", 300) == 300
    assert _get_constraint(_FakeSpec(), "max_tokens", 4096) == 4096
    assert _get_constraint(_FakeSpec(), "any_key", "default_val") == "default_val"


def test_get_constraint_reads_dict_constraints():
    """_get_constraint returns the keyed value when constraints is a dict."""
    from orchestrator.worker_registry import _get_constraint

    class _FakeSpec:
        constraints = {"max_seconds": 600, "max_tokens": 8192}

    assert _get_constraint(_FakeSpec(), "max_seconds", 300) == 600
    assert _get_constraint(_FakeSpec(), "max_tokens", 4096) == 8192
    assert _get_constraint(_FakeSpec(), "missing_key", "fallback") == "fallback"


def test_try_skill_envelope_returns_none_for_unknown_task_type():
    """_try_skill_envelope returns None for task_types not in the skill map."""
    spec = JobSpec(
        job_id=_new_id(),
        intent="general coding",
        prompt="write a function",
        backend_hint="echo",
        task_type="general",
    )
    result = OrchestrationSupervisor._try_skill_envelope(spec)
    assert result is None


def test_try_skill_envelope_returns_none_when_no_task_type():
    """_try_skill_envelope returns None gracefully when task_type is empty."""
    spec = JobSpec(
        job_id=_new_id(),
        intent="echo",
        prompt="hello",
        backend_hint="echo",
    )
    result = OrchestrationSupervisor._try_skill_envelope(spec)
    assert result is None


# ── replay() preserves task_type ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_preserves_task_type(tmp_path):
    """replay() must carry task_type forward so retried skill-mapped jobs route correctly."""
    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="add channel",
        prompt="add a webhook channel",
        backend_hint="echo",
        task_type="add_channel",
    )
    original_id = spec.job_id

    # Inject a FAILED event so replay() has something to replay.
    _append_event(
        tmp_path / "jobs.jsonl",
        original_id,
        {
            "status": JobStatus.FAILED.value,
            "spec": spec.model_dump(),
            "error": "injected failure",
        },
    )

    new_id = await sup.replay(original_id)
    assert new_id != original_id

    # Load the replayed job's spec from the event log and assert task_type survived.
    events = _load_events(tmp_path / "jobs.jsonl")
    states = _latest_status_per_job(events)
    replayed_state = states.get(new_id) or {}
    replayed_spec = replayed_state.get("spec", {})
    assert replayed_spec.get("task_type") == "add_channel", (
        f"task_type was lost during replay; got: {replayed_spec.get('task_type')!r}"
    )


# ── SkillEnvelope.to_dict() ───────────────────────────────────────────────────

def test_skill_envelope_to_dict_is_json_serialisable():
    """SkillEnvelope.to_dict() must return plain JSON-serialisable types (no Path objects)."""
    import json
    import os
    from pathlib import Path as P
    from orchestrator.openclaw_skill_resolver import SkillEnvelope

    envelope = SkillEnvelope(
        skill_id="openclaw-status",
        skill_path=P("/some/path/SKILL.md"),
        args={"key": "value"},
        agent_id="test-agent",
        openclaw_home=P("/home/openclaw"),
        parent_chain=["openclaw-new-agent"],
    )
    d = envelope.to_dict()
    # Must not raise — all values must be JSON-serialisable.
    serialised = json.dumps(d)
    parsed = json.loads(serialised)
    assert parsed["skill_id"] == "openclaw-status"
    assert parsed["skill_path"] == os.path.normpath("/some/path/SKILL.md")
    assert parsed["openclaw_home"] == os.path.normpath("/home/openclaw")
    assert parsed["depth"] == 1


# ── Anti-mirror: lmstudio-mac must use explicit default model ─────────────────

@pytest.mark.asyncio
async def test_dispatch_lmstudio_mac_empty_metadata_uses_explicit_default_not_loaded_model(
    tmp_path, monkeypatch,
):
    """lmstudio-mac with empty metadata must inject MAC_LMS default before the worker runs."""
    from unittest.mock import AsyncMock

    import orchestrator.worker_registry as reg_mod
    from utils.dispatch_models import mac_lmstudio_default_model

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value=None),
    )
    captured: dict[str, str] = {}

    async def _capture_mac_worker(spec):
        captured["model"] = (spec.metadata or {}).get("model", "")
        return {"backend": "lmstudio-mac", "output": "ok"}

    monkeypatch.setitem(reg_mod.WORKER_REGISTRY, "lmstudio-mac", _capture_mac_worker)

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="freeform",
        prompt="mac mlx task",
        backend_hint="lmstudio-mac",
        metadata={},
    )
    await sup._dispatch(spec)
    assert captured["model"] == mac_lmstudio_default_model()
    assert captured["model"].strip() != ""


@pytest.mark.asyncio
async def test_dispatch_lmstudio_mac_rejects_windows_only_model_in_metadata(
    tmp_path, monkeypatch,
):
    from unittest.mock import AsyncMock

    import orchestrator.worker_registry as reg_mod
    from utils.hardware_policy import HardwareAffinityError

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value=None),
    )
    monkeypatch.setitem(
        reg_mod.WORKER_REGISTRY,
        "lmstudio-mac",
        AsyncMock(return_value={"backend": "lmstudio-mac", "output": "must not run"}),
    )

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="freeform",
        prompt="illegal on mac mirror",
        backend_hint="lmstudio-mac",
        metadata={"model": "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"},
    )
    with pytest.raises(HardwareAffinityError, match="NEVER_MAC"):
        await sup._dispatch(spec)


# ── Hardware affinity re-check after Windows preemption ───────────────────────

@pytest.mark.asyncio
async def test_dispatch_raises_affinity_error_on_mac_fallthrough_with_windows_only_model(
    tmp_path, monkeypatch,
):
    """When the Windows pool is down, Mac-local routing must still fail-closed.

    A freeform job with a windows_only model in metadata must not reach the Mac
    Ollama worker when WIN_CODER_ENDPOINTS is unreachable — that path caused GPU
    OOM / double-barrel risk (policy: config/model_hardware_policy.yml).
    """
    from unittest.mock import AsyncMock

    import orchestrator.worker_registry as reg_mod
    from utils.hardware_policy import HardwareAffinityError

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value=None),
    )
    ollama_called: dict[str, bool] = {"value": False}

    async def _ollama_should_not_run(_spec):
        ollama_called["value"] = True
        return {"backend": "ollama-mac", "output": "must not run"}

    monkeypatch.setitem(reg_mod.WORKER_REGISTRY, "ollama", _ollama_should_not_run)

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="freeform",
        prompt="run heavy model",
        metadata={"model": "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled-v2"},
    )

    with pytest.raises(HardwareAffinityError, match="NEVER_MAC"):
        await sup._dispatch(spec)

    assert ollama_called["value"] is False


@pytest.mark.asyncio
async def test_dispatch_raises_affinity_error_when_windows_preemption_blocked(
    tmp_path, monkeypatch
):
    """check_affinity("win") is called before dispatching to the Windows coder.

    When a Mac-local job is preempted by the Windows pool, the dispatcher must
    re-run the hardware-affinity gate for platform="win".  If affinity blocks
    the Windows platform, the job must fail with HardwareAffinityError rather
    than silently proceeding with a platform-constrained model on the wrong host.
    """
    from unittest.mock import AsyncMock, patch
    from utils.hardware_policy import HardwareAffinityError
    import orchestrator.worker_registry as reg_mod

    monkeypatch.setattr(
        OrchestrationSupervisor,
        "_get_reachable_windows_coder",
        AsyncMock(return_value="http://192.168.254.103:1234"),
    )
    monkeypatch.setitem(reg_mod.WORKER_REGISTRY, "lmstudio-win", AsyncMock(
        return_value={"backend": "lmstudio-win", "output": "should not reach here"}
    ))

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="mac-only-task",
        prompt="test",
        backend_hint="lmstudio-mac",
        metadata={"model": "mac-only-model"}
    )

    with patch(
        "orchestrator.supervisor.check_affinity",
        side_effect=HardwareAffinityError("mac-only-model is not allowed on win"),
    ) as mock_check:
        with pytest.raises(HardwareAffinityError, match="mac-only-model"):
            await sup._dispatch(spec)

    # check_affinity must have been called with the Windows platform
    calls = [(c.args[1] if c.args else c.kwargs.get("platform")) for c in mock_check.call_args_list]
    assert "win" in calls, f"check_affinity was not called with 'win'; calls: {calls}"
    # check_affinity must have been called with the model
    model_calls = [(c.args[0] if c.args else c.kwargs.get("model_id")) for c in mock_check.call_args_list]
    assert "mac-only-model" in model_calls, f"check_affinity was not called with 'mac-only-model'; calls: {model_calls}"


# ── task_type forwarded through the HTTP submission model ─────────────────────

def test_job_submit_request_has_task_type_field():
    """_JobSubmitRequest must expose task_type so skill routing works via the API."""
    from orchestrator.fastapi_app import _JobSubmitRequest

    req = _JobSubmitRequest(prompt="hello")
    assert req.task_type == "", "default task_type must be empty string"

    req2 = _JobSubmitRequest(prompt="spawn agent", task_type="new_agent")
    assert req2.task_type == "new_agent"


# ── _inject_memory_context (Item 7 — RAG wiring) ─────────────────────────────

@pytest.mark.asyncio
async def test_inject_memory_context_prepends_block(tmp_path):
    """When retrieve_context returns hits, prompt gets [MEMORY CONTEXT] prefix."""
    from unittest.mock import AsyncMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("tell me about Q3")

    mock_hits = [{"text": "Q3 revenue was $10M"}, {"text": "Q3 costs were $8M"}]
    with patch(
        "orchestrator.memory_node.retrieve_context", AsyncMock(return_value=mock_hits)
    ):
        enriched = await sup._inject_memory_context(spec)

    assert enriched.prompt.startswith("[MEMORY CONTEXT]")
    assert "Q3 revenue was $10M" in enriched.prompt
    assert "tell me about Q3" in enriched.prompt


@pytest.mark.asyncio
async def test_inject_memory_context_no_hits_unchanged(tmp_path):
    """When retrieve_context returns [], spec is returned unchanged."""
    from unittest.mock import AsyncMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("original prompt")

    with patch(
        "orchestrator.memory_node.retrieve_context", AsyncMock(return_value=[])
    ):
        enriched = await sup._inject_memory_context(spec)

    assert enriched is spec  # identity — no copy made


@pytest.mark.asyncio
async def test_inject_memory_context_disabled_by_metadata(tmp_path):
    """use_memory=False in metadata bypasses injection entirely."""
    from unittest.mock import AsyncMock, patch

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        prompt="prompt",
        backend_hint="echo",
        metadata={"use_memory": False},
    )
    mock_retrieve = AsyncMock(return_value=[{"text": "should not appear"}])
    with patch("orchestrator.memory_node.retrieve_context", mock_retrieve):
        enriched = await sup._inject_memory_context(spec)

    mock_retrieve.assert_not_called()
    assert enriched is spec


@pytest.mark.asyncio
async def test_inject_memory_context_degrades_on_exception(tmp_path):
    """If retrieve_context raises, original spec is returned unchanged."""
    from unittest.mock import AsyncMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("safe prompt")

    with patch(
        "orchestrator.memory_node.retrieve_context",
        AsyncMock(side_effect=RuntimeError("store down")),
    ):
        enriched = await sup._inject_memory_context(spec)

    assert enriched is spec

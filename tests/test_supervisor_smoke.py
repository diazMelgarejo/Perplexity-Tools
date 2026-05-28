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

def test_submit_job_strips_client_win_endpoint(tmp_path):
    """Clients must not inject _win_endpoint; only the dispatcher sets it after probe."""
    sup = _make_sup(tmp_path)

    async def _run() -> str:
        spec = JobSpec(
            job_id=_new_id(),
            intent="echo",
            prompt="probe bypass",
            backend_hint="echo",
            metadata={"_win_endpoint": "http://10.0.0.99:1234"},
        )
        job_id = await sup.submit_job(spec)
        await sup.cancel(job_id)
        return job_id

    job_id = asyncio.run(_run())
    events = _load_events(sup._jobs_file)
    queued = next(
        e for e in events if e.get("job_id") == job_id and e.get("status") == JobStatus.QUEUED
    )
    assert "_win_endpoint" not in (queued.get("spec", {}).get("metadata") or {})


@pytest.mark.asyncio
async def test_submit_echo_job_succeeds(tmp_path):
    """submit_job() fires worker; job reaches SUCCEEDED."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("hello supervisor")
    job_id = await sup.submit_job(spec)
    assert job_id == spec.job_id

    task = sup._active.get(job_id)
    assert task is not None
    await task

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


@pytest.mark.asyncio
async def test_inject_memory_context_uses_gossip_payload_text(tmp_path):
    """End-to-end: FTS hits from GossipBus must reach the injected prompt block."""
    from unittest.mock import AsyncMock, patch

    from orchestrator.gossip_bus import GossipBus
    from orchestrator.memory_node import reset_singletons

    bus = GossipBus(str(tmp_path / "gossip.db"))
    await bus.init_db()
    with patch.object(bus, "_embed_and_store", new_callable=AsyncMock):
        await bus.emit("dispatch", {"prompt": "prior Q3 revenue was $10M"})

    sup = _make_sup(tmp_path)
    spec = _echo_spec("Q3 revenue")

    reset_singletons()
    with (
        patch("orchestrator.memory_store.lancedb_available", return_value=False),
        patch("orchestrator.memory_node._get_default_bus", return_value=bus),
    ):
        enriched = await sup._inject_memory_context(spec)

    assert "prior Q3 revenue was $10M" in enriched.prompt
    assert enriched.prompt.startswith("[MEMORY CONTEXT]")


@pytest.mark.asyncio
async def test_completed_job_populates_gossip_for_later_injection(tmp_path, monkeypatch):
    """Jobs must emit to GossipBus on completion so a later job can recall context."""
    from unittest.mock import AsyncMock, patch

    from orchestrator.memory_node import reset_singletons

    monkeypatch.setenv("PT_STATE_DIR", str(tmp_path))
    reset_singletons()

    sup = _make_sup(tmp_path)
    marker = "unique_recall_marker_7f3a"

    job_id = await sup.submit_job(_echo_spec(f"store fact: {marker} revenue was $10M"))
    task = sup._active.get(job_id)
    assert task is not None
    await task

    # Query must share FTS terms with the stored row (FTS5 ANDs tokens by default).
    spec2 = _echo_spec(f"{marker} revenue")
    with patch("orchestrator.memory_store.lancedb_available", return_value=False):
        enriched = await sup._inject_memory_context(spec2)

    assert "$10M" in enriched.prompt
    assert enriched.prompt.startswith("[MEMORY CONTEXT]")


# ── OrchestrationSupervisor.__init__ new fields (PR change) ──────────────────

def test_supervisor_init_sets_pt_state_dir(tmp_path):
    """Supervisor __init__ must export PT_STATE_DIR so memory_node can resolve the db path."""
    import os

    sup = _make_sup(tmp_path)
    assert os.environ.get("PT_STATE_DIR") == str(tmp_path.resolve())


def test_supervisor_init_gossip_bus_starts_none(tmp_path):
    """_gossip_bus must be None at construction — bus is created lazily."""
    sup = _make_sup(tmp_path)
    assert sup._gossip_bus is None


def test_supervisor_init_gossip_warned_starts_false(tmp_path):
    """_gossip_warned must be False at construction."""
    sup = _make_sup(tmp_path)
    assert sup._gossip_warned is False


# ── _record_to_gossip (PR change: new method) ─────────────────────────────────

@pytest.mark.asyncio
async def test_record_to_gossip_emits_core_payload(tmp_path):
    """_record_to_gossip must emit at minimum job_id, prompt, and intent."""
    from unittest.mock import AsyncMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("test the gossip payload")
    spec = spec.model_copy(update={"intent": "test-intent"})

    emitted: list[tuple] = []

    async def _fake_emit(event_type, payload):
        """
        Record a gossip event by appending its (event_type, payload) tuple to the captured `emitted` list.
        
        This test helper mutates the surrounding `emitted` list by adding a tuple containing the event type and its payload.
        
        Parameters:
            event_type (str): The name/type of the event to record.
            payload (dict): The event payload to record.
        """
        emitted.append((event_type, payload))

    with (
        patch.object(sup, "_gossip_bus", create=True),
        patch("orchestrator.memory_node.ensure_gossip_db_ready", AsyncMock()),
    ):
        # Inject a pre-initialized fake bus
        from unittest.mock import MagicMock
        fake_bus = MagicMock()
        fake_bus.emit = _fake_emit
        sup._gossip_bus = fake_bus

        await sup._record_to_gossip("result", spec)

    assert len(emitted) == 1
    event_type, payload = emitted[0]
    assert event_type == "result"
    assert payload["job_id"] == spec.job_id
    assert payload["prompt"] == spec.prompt
    assert payload["intent"] == spec.intent


@pytest.mark.asyncio
async def test_record_to_gossip_includes_role_when_set(tmp_path):
    """When spec.role is set, role must be present in the emitted payload."""
    from unittest.mock import AsyncMock, MagicMock

    sup = _make_sup(tmp_path)
    spec = JobSpec(
        job_id=_new_id(),
        intent="coder task",
        prompt="write a sort function",
        backend_hint="echo",
        role="coder",
    )

    emitted: list[dict] = []

    async def _fake_emit(event_type, payload):
        """
        Record a gossip emit by appending the provided payload to the captured `emitted` list.
        
        Parameters:
            event_type (str): The type of event being emitted (accepted for signature compatibility; ignored).
            payload (dict): The payload object to append to the `emitted` list.
        """
        emitted.append(payload)

    fake_bus = MagicMock()
    fake_bus.emit = _fake_emit
    sup._gossip_bus = fake_bus

    from unittest.mock import patch
    with patch("orchestrator.memory_node.ensure_gossip_db_ready", AsyncMock()):
        await sup._record_to_gossip("result", spec)

    assert emitted[0].get("role") == "coder"


@pytest.mark.asyncio
async def test_record_to_gossip_omits_role_when_none(tmp_path):
    """When spec.role is None, 'role' key must NOT appear in the emitted payload."""
    from unittest.mock import AsyncMock, MagicMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("no role here")
    assert spec.role is None

    emitted: list[dict] = []

    async def _fake_emit(event_type, payload):
        """
        Record a gossip emit by appending the provided payload to the captured `emitted` list.
        
        Parameters:
            event_type (str): The type of event being emitted (accepted for signature compatibility; ignored).
            payload (dict): The payload object to append to the `emitted` list.
        """
        emitted.append(payload)

    fake_bus = MagicMock()
    fake_bus.emit = _fake_emit
    sup._gossip_bus = fake_bus

    with patch("orchestrator.memory_node.ensure_gossip_db_ready", AsyncMock()):
        await sup._record_to_gossip("result", spec)

    assert "role" not in emitted[0]


@pytest.mark.asyncio
async def test_record_to_gossip_merges_extra_dict(tmp_path):
    """Extra kwargs must be merged into the emitted payload."""
    from unittest.mock import AsyncMock, MagicMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("merge extra")

    emitted: list[dict] = []

    async def _fake_emit(event_type, payload):
        """
        Record a gossip emit by appending the provided payload to the captured `emitted` list.
        
        Parameters:
            event_type (str): The type of event being emitted (accepted for signature compatibility; ignored).
            payload (dict): The payload object to append to the `emitted` list.
        """
        emitted.append(payload)

    fake_bus = MagicMock()
    fake_bus.emit = _fake_emit
    sup._gossip_bus = fake_bus

    with patch("orchestrator.memory_node.ensure_gossip_db_ready", AsyncMock()):
        await sup._record_to_gossip("error", spec, {"detail": "timeout", "policy": True})

    assert emitted[0]["detail"] == "timeout"
    assert emitted[0]["policy"] is True


@pytest.mark.asyncio
async def test_record_to_gossip_lazily_initializes_gossip_bus(tmp_path, monkeypatch):
    """_gossip_bus must be None before first call and set after."""
    from unittest.mock import AsyncMock, MagicMock, patch

    monkeypatch.delenv("GOSSIP_DB_PATH", raising=False)
    sup = _make_sup(tmp_path)
    assert sup._gossip_bus is None

    spec = _echo_spec("lazy init")

    fake_bus = MagicMock()
    fake_bus.emit = AsyncMock()

    with (
        patch("orchestrator.gossip_bus.GossipBus", return_value=fake_bus),
        patch("orchestrator.memory_node.ensure_gossip_db_ready", AsyncMock()),
    ):
        await sup._record_to_gossip("result", spec)

    assert sup._gossip_bus is fake_bus


@pytest.mark.asyncio
async def test_record_to_gossip_reuses_existing_gossip_bus(tmp_path):
    """_gossip_bus is not re-created on the second call."""
    from unittest.mock import AsyncMock, MagicMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("reuse bus")

    first_bus = MagicMock()
    first_bus.emit = AsyncMock()
    sup._gossip_bus = first_bus

    with patch("orchestrator.memory_node.ensure_gossip_db_ready", AsyncMock()):
        await sup._record_to_gossip("result", spec)
        await sup._record_to_gossip("result", spec)

    # The bus must not have been replaced.
    assert sup._gossip_bus is first_bus


@pytest.mark.asyncio
async def test_record_to_gossip_never_raises(tmp_path):
    """_record_to_gossip must swallow all exceptions — job worker must not crash."""
    from unittest.mock import AsyncMock, MagicMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("must not raise")

    failing_bus = MagicMock()
    failing_bus.emit = AsyncMock(side_effect=RuntimeError("db unavailable"))
    sup._gossip_bus = failing_bus

    with patch("orchestrator.memory_node.ensure_gossip_db_ready", AsyncMock()):
        # Must not raise
        await sup._record_to_gossip("result", spec)


@pytest.mark.asyncio
async def test_run_worker_calls_record_to_gossip_on_success(tmp_path):
    """After a successful job, _record_to_gossip must be called with event_type='result'."""
    from unittest.mock import AsyncMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("gossip on success")

    calls: list[tuple] = []

    async def _capture(event_type, spec_, extra=None):
        """
        Record a gossip event into the shared `calls` capture list for test assertions.
        
        Parameters:
            event_type (str): The type of event being emitted (e.g., "result", "error").
            spec_ (Any): The job spec or payload associated with the event.
            extra (Optional[dict]): Additional payload data merged into the emitted event; may be None.
        """
        calls.append((event_type, spec_, extra))

    with patch.object(sup, "_record_to_gossip", side_effect=_capture):
        job_id = await sup.submit_job(spec)
        task = sup._active.get(job_id)
        assert task is not None
        await task

    result_calls = [(et, s) for et, s, _ in calls if et == "result"]
    assert len(result_calls) == 1
    assert result_calls[0][1].job_id == spec.job_id


@pytest.mark.asyncio
async def test_run_worker_calls_record_to_gossip_on_generic_exception(tmp_path, monkeypatch):
    """When _dispatch raises a generic Exception, _record_to_gossip is called with 'error'."""
    from unittest.mock import AsyncMock, patch

    sup = _make_sup(tmp_path)
    spec = _echo_spec("error gossip")

    calls: list[tuple] = []

    async def _capture(event_type, spec_, extra=None):
        """
        Record a gossip event into the shared `calls` capture list for test assertions.
        
        Parameters:
            event_type (str): The type of event being emitted (e.g., "result", "error").
            spec_ (Any): The job spec or payload associated with the event.
            extra (Optional[dict]): Additional payload data merged into the emitted event; may be None.
        """
        calls.append((event_type, spec_, extra))

    async def _explode(s):
        """
        Raise a RuntimeError with message "boom".
        
        Parameters:
            s: Ignored parameter retained for signature compatibility.
        
        Raises:
            RuntimeError: Always raised with the message "boom".
        """
        raise RuntimeError("boom")

    with (
        patch.object(sup, "_dispatch", side_effect=_explode),
        patch.object(sup, "_record_to_gossip", side_effect=_capture),
    ):
        job_id = await sup.submit_job(spec)
        task = sup._active.get(job_id)
        assert task is not None
        await task

    error_calls = [(et, ex) for et, _, ex in calls if et == "error"]
    assert len(error_calls) == 1
    assert error_calls[0][1] is not None
    assert "boom" in error_calls[0][1].get("detail", "")


@pytest.mark.asyncio
async def test_run_worker_calls_record_to_gossip_on_hardware_affinity_error(tmp_path, monkeypatch):
    """HardwareAffinityError must trigger _record_to_gossip with 'error' and policy=True."""
    from unittest.mock import patch
    from utils.hardware_policy import HardwareAffinityError

    sup = _make_sup(tmp_path)
    spec = _echo_spec("affinity gossip")

    calls: list[tuple] = []

    async def _capture(event_type, spec_, extra=None):
        """
        Record a gossip event into the shared `calls` capture list for test assertions.
        
        Parameters:
            event_type (str): The type of event being emitted (e.g., "result", "error").
            spec_ (Any): The job spec or payload associated with the event.
            extra (Optional[dict]): Additional payload data merged into the emitted event; may be None.
        """
        calls.append((event_type, spec_, extra))

    async def _affinity_error(s):
        """
        Raise a HardwareAffinityError indicating the provided model is not allowed on mac hosts.
        
        Parameters:
            s: Ignored input (kept for signature compatibility).
        
        Raises:
            HardwareAffinityError: Always raised with message "NEVER_MAC: model not allowed here".
        """
        raise HardwareAffinityError("NEVER_MAC: model not allowed here")

    with (
        patch.object(sup, "_dispatch", side_effect=_affinity_error),
        patch.object(sup, "_record_to_gossip", side_effect=_capture),
    ):
        job_id = await sup.submit_job(spec)
        task = sup._active.get(job_id)
        assert task is not None
        await task

    error_calls = [(et, ex) for et, _, ex in calls if et == "error"]
    assert len(error_calls) == 1
    assert error_calls[0][1].get("policy") is True


# ── _append_event durability (hardened 2026-05-28) ───────────────────────────

def test_append_event_produces_valid_jsonl(tmp_path):
    """Each line written by _append_event must be independently parseable JSON."""
    jobs_file = tmp_path / "jobs.jsonl"
    _append_event(jobs_file, "job-durability-1", {"status": "queued"})
    _append_event(jobs_file, "job-durability-1", {"status": "running"})
    _append_event(jobs_file, "job-durability-1", {"status": "succeeded"})

    raw_lines = [
        ln for ln in jobs_file.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    assert len(raw_lines) == 3, "Expected exactly 3 lines"
    for line in raw_lines:
        parsed = json.loads(line)  # must not raise
        assert "ts" in parsed, "Each line must contain a timestamp field"
        assert "job_id" in parsed, "Each line must contain job_id"


def test_append_event_multiple_appends_are_separate_lines(tmp_path):
    """Multiple _append_event calls must not merge or overwrite — each produces one line."""
    jobs_file = tmp_path / "jobs.jsonl"
    n = 5
    for i in range(n):
        _append_event(jobs_file, f"job-{i}", {"status": "queued", "seq": i})

    events = _load_events(jobs_file)
    assert len(events) == n
    job_ids = {e["job_id"] for e in events}
    assert job_ids == {f"job-{i}" for i in range(n)}


def test_append_event_serialises_jobstatus_enum(tmp_path):
    """JobStatus enum values must be serialised as strings, not raw enum objects."""
    jobs_file = tmp_path / "jobs.jsonl"
    _append_event(jobs_file, "enum-job", {"status": JobStatus.SUCCEEDED})

    events = _load_events(jobs_file)
    assert len(events) == 1
    assert events[0]["status"] == JobStatus.SUCCEEDED.value  # "succeeded"
    assert isinstance(events[0]["status"], str)


def test_append_event_creates_file_in_existing_parent(tmp_path):
    """_append_event must create a missing .jsonl file when its parent directory already exists."""
    # tmp_path always exists (pytest fixture); only the target file is absent.
    # This verifies open("a") creates the file without requiring the parent to be missing.
    jobs_file = tmp_path / "jobs.jsonl"
    assert jobs_file.parent.exists()
    assert not jobs_file.exists()
    _append_event(jobs_file, "new-job", {"status": "queued"})
    assert jobs_file.exists()
    events = _load_events(jobs_file)
    assert events[0]["job_id"] == "new-job"


# ── Result size cap (2 MiB, 2026-05-28 v1 audit HIGH 5) ──────────────────────

@pytest.mark.asyncio
async def test_run_worker_result_cap_truncates_oversized_result(tmp_path):
    """A result whose JSON serialization exceeds 2 MiB must be replaced with a
    truncation marker dict; the original artifact content must not be written.
    """
    sup = _make_sup(tmp_path)
    spec = _echo_spec("overflow job")

    # Produce a result that, when JSON-serialised, is clearly > 2 MiB.
    big_string = "x" * (3 * 1024 * 1024)  # 3 MiB raw characters

    async def _oversized_dispatch(s):
        return {"output": big_string, "backend": "echo"}

    sup._dispatch = _oversized_dispatch
    job_id = await sup.submit_job(spec)
    task = sup._active.get(job_id)
    assert task is not None
    await task

    result_path = tmp_path / "jobs" / job_id / "result.json"
    assert result_path.exists(), "result.json must always be written"

    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved.get("status") == "truncated", (
        f"Expected truncated marker, got: {list(saved.keys())}"
    )
    assert "reason" in saved
    assert "original_size_bytes" in saved
    assert saved["original_size_bytes"] > 2 * 1024 * 1024


@pytest.mark.asyncio
async def test_run_worker_result_within_cap_written_verbatim(tmp_path):
    """A result whose JSON serialization is under 2 MiB must be written as-is."""
    sup = _make_sup(tmp_path)
    spec = _echo_spec("normal job")

    expected_output = "hello world"

    async def _small_dispatch(s):
        return {"output": expected_output, "backend": "echo"}

    sup._dispatch = _small_dispatch
    job_id = await sup.submit_job(spec)
    task = sup._active.get(job_id)
    assert task is not None
    await task

    result_path = tmp_path / "jobs" / job_id / "result.json"
    assert result_path.exists()
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved.get("output") == expected_output
    assert saved.get("status") != "truncated"


@pytest.mark.asyncio
async def test_run_worker_truncated_result_still_records_succeeded(tmp_path):
    """Even when the result is truncated, the job must be marked SUCCEEDED in the event log.

    The cap only affects the artifact; the lifecycle transition must still complete.
    """
    sup = _make_sup(tmp_path)
    spec = _echo_spec("truncated but succeeded")

    big_string = "y" * (3 * 1024 * 1024)

    async def _oversized(s):
        return {"output": big_string, "backend": "echo"}

    sup._dispatch = _oversized
    job_id = await sup.submit_job(spec)
    task = sup._active.get(job_id)
    assert task is not None
    await task

    status = await sup.get_status(job_id)
    assert status is not None
    assert status["status"] == JobStatus.SUCCEEDED.value, (
        "Oversized result must not cause the job to appear FAILED"
    )


@pytest.mark.asyncio
async def test_run_worker_result_safely_under_cap_is_preserved(tmp_path):
    """A result whose UTF-8 byte length is safely under _MAX_RESULT_BYTES must not be truncated.

    Uses _MAX_RESULT_BYTES - 20 as payload size (well inside the 2 MiB cap).
    The cap is strictly > (not >=), so any under-cap result must pass through unchanged.
    """
    sup = _make_sup(tmp_path)
    spec = _echo_spec("boundary job")

    _MAX_RESULT_BYTES = 2 * 1024 * 1024
    # Construct a result that, after json.dumps(indent=2), is safely under 2 MiB.
    # json.dumps({"output": "a"*N, "backend": "echo"}, indent=2) has ~40 bytes overhead.
    # Use a 200-byte margin so the serialized result is comfortably under the cap.
    _JSON_OVERHEAD = 40
    payload_size = _MAX_RESULT_BYTES - _JSON_OVERHEAD - 200  # serialized ≈ 2 MiB - 200 B
    small_string = "a" * payload_size

    async def _boundary_dispatch(s):
        return {"output": small_string, "backend": "echo"}

    sup._dispatch = _boundary_dispatch
    job_id = await sup.submit_job(spec)
    task = sup._active.get(job_id)
    assert task is not None
    await task

    result_path = tmp_path / "jobs" / job_id / "result.json"
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved.get("status") != "truncated", "Under-cap result must not be truncated"
    assert saved.get("output") == small_string
